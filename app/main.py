from __future__ import annotations

import logging
from typing import Optional

import requests
from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from google.api_core import exceptions as google_exceptions
from google.cloud import documentai
from google.protobuf.json_format import MessageToDict
from pydantic import BaseModel, ConfigDict, HttpUrl, field_validator

logger = logging.getLogger(__name__)

SUPPORTED_MIME_TYPES = {
    "image/jpeg",
    "image/png",
    "application/pdf",
}


class ProcessRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    file_url: HttpUrl
    mime_type: str
    project_id: str
    location: str
    processor_id: str
    processor_version: Optional[str] = None

    @field_validator("mime_type")
    @classmethod
    def validate_mime_type(cls, value: str) -> str:
        if value not in SUPPORTED_MIME_TYPES:
            raise ValueError(
                "mime_type must be one of image/jpeg, image/png, or application/pdf"
            )
        return value


class ErrorResponse(BaseModel):
    error: bool = True
    message: str


app = FastAPI(
    title="Document AI Relay API",
    version="1.0.0",
    description="Relay API for Bubble to Google Document AI processing.",
)


def build_processor_name(
    client: documentai.DocumentProcessorServiceClient,
    project_id: str,
    location: str,
    processor_id: str,
    processor_version: Optional[str],
) -> str:
    if processor_version:
        return client.processor_version_path(
            project=project_id,
            location=location,
            processor=processor_id,
            processor_version=processor_version,
        )

    return client.processor_path(
        project=project_id,
        location=location,
        processor=processor_id,
    )


def fetch_file_bytes(file_url: str) -> bytes:
    try:
        response = requests.get(file_url, timeout=30)
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.exception("Failed to fetch file from URL")
        raise HTTPException(status_code=400, detail=f"Failed to fetch file: {exc}") from exc

    if not response.content:
        raise HTTPException(status_code=400, detail="Failed to fetch file: empty content")

    return response.content


def process_document(payload: ProcessRequestBody) -> dict:
    file_bytes = fetch_file_bytes(str(payload.file_url))

    client = documentai.DocumentProcessorServiceClient()
    processor_name = build_processor_name(
        client=client,
        project_id=payload.project_id,
        location=payload.location,
        processor_id=payload.processor_id,
        processor_version=payload.processor_version,
    )

    raw_document = documentai.RawDocument(content=file_bytes, mime_type=payload.mime_type)
    request = documentai.ProcessRequest(name=processor_name, raw_document=raw_document)

    try:
        response = client.process_document(request=request)
    except (
        google_exceptions.GoogleAPICallError,
        google_exceptions.RetryError,
        ValueError,
    ) as exc:
        logger.exception("Document AI processing failed")
        raise HTTPException(status_code=400, detail=f"Document AI processing failed: {exc}") from exc

    return MessageToDict(response.document._pb)


@app.exception_handler(HTTPException)
async def http_exception_handler(_, exc: HTTPException):
    detail = exc.detail
    if isinstance(detail, dict) and detail.get("error") is True:
        payload = detail
    else:
        payload = {"error": True, "message": str(detail)}

    return JSONResponse(status_code=exc.status_code, content=payload)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(_, exc: RequestValidationError):
    messages = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error.get("loc", []))
        messages.append(f"{location}: {error.get('msg', 'Invalid value')}")

    return JSONResponse(
        status_code=422,
        content={"error": True, "message": "; ".join(messages)},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(_, exc: Exception):
    logger.exception("Unhandled server error")
    return JSONResponse(
        status_code=500,
        content={"error": True, "message": f"Internal server error: {exc}"},
    )


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.post(
    "/document-ai/process",
    responses={400: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
def document_ai_process(payload: ProcessRequestBody) -> dict:
    document = process_document(payload)
    return {"document": document}
