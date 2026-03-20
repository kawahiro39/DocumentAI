from __future__ import annotations

import logging
from typing import Any, Optional

import requests
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from google.api_core import exceptions as google_exceptions
from google.cloud import documentai
from google.protobuf.json_format import MessageToDict
from pydantic import BaseModel, ConfigDict, HttpUrl, ValidationError, field_validator

logger = logging.getLogger(__name__)

SUPPORTED_MIME_TYPES = {
    "image/jpeg",
    "image/png",
    "application/pdf",
}


class JsonProcessRequestBody(BaseModel):
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
        return validate_mime_type(value)


class FormProcessRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str
    location: str
    processor_id: str
    processor_version: Optional[str] = None
    mime_type: Optional[str] = None

    @field_validator("mime_type")
    @classmethod
    def validate_optional_mime_type(cls, value: Optional[str]) -> Optional[str]:
        if value is None or value == "":
            return None
        return validate_mime_type(value)


class ErrorResponse(BaseModel):
    error: bool = True
    message: str


app = FastAPI(
    title="Document AI Relay API",
    version="1.2.0",
    description="Relay API for Bubble to Google Document AI processing.",
)


def validate_mime_type(value: str) -> str:
    if value not in SUPPORTED_MIME_TYPES:
        raise ValueError(
            "mime_type must be one of image/jpeg, image/png, or application/pdf"
        )
    return value


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


async def fetch_upload_bytes(upload: Any) -> tuple[bytes, str]:
    if upload is None or not hasattr(upload, "read"):
        raise HTTPException(status_code=422, detail="file is required for multipart/form-data")

    file_bytes = await upload.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    if not upload.content_type:
        raise HTTPException(status_code=422, detail="Uploaded file content_type is missing")

    return file_bytes, upload.content_type


def process_document_bytes(
    *,
    file_bytes: bytes,
    mime_type: str,
    project_id: str,
    location: str,
    processor_id: str,
    processor_version: Optional[str],
) -> dict:
    client = documentai.DocumentProcessorServiceClient()
    processor_name = build_processor_name(
        client=client,
        project_id=project_id,
        location=location,
        processor_id=processor_id,
        processor_version=processor_version,
    )

    raw_document = documentai.RawDocument(content=file_bytes, mime_type=mime_type)
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


def process_document_from_url(payload: JsonProcessRequestBody) -> dict:
    file_bytes = fetch_file_bytes(str(payload.file_url))
    return process_document_bytes(
        file_bytes=file_bytes,
        mime_type=payload.mime_type,
        project_id=payload.project_id,
        location=payload.location,
        processor_id=payload.processor_id,
        processor_version=payload.processor_version,
    )


async def process_document_from_form(request: Request) -> dict:
    form = await request.form()
    upload = form.get("file")

    try:
        form_fields = {key: value for key, value in form.items() if key != "file"}
        payload = FormProcessRequestBody.model_validate(form_fields)
    except ValidationError as exc:
        raise RequestValidationError(exc.errors()) from exc

    file_bytes, upload_mime_type = await fetch_upload_bytes(upload)
    mime_type = payload.mime_type or upload_mime_type

    try:
        mime_type = validate_mime_type(mime_type)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return process_document_bytes(
        file_bytes=file_bytes,
        mime_type=mime_type,
        project_id=payload.project_id,
        location=payload.location,
        processor_id=payload.processor_id,
        processor_version=payload.processor_version,
    )


def extract_text_from_text_anchor(text_anchor: dict[str, Any], full_text: str) -> str:
    text_segments = text_anchor.get("textSegments", [])
    parts: list[str] = []

    for segment in text_segments:
        start_index = int(segment.get("startIndex", 0) or 0)
        end_index = int(segment.get("endIndex", 0) or 0)
        if end_index > start_index:
            parts.append(full_text[start_index:end_index])

    return "".join(parts).strip()



def collect_entity_fields(
    entities: list[dict[str, Any]],
    full_text: str,
    *,
    parent: Optional[str] = None,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []

    for entity in entities:
        field_name = entity.get("type") or entity.get("mentionText") or "unknown"
        if parent:
            field_name = f"{parent}.{field_name}"

        value = (
            entity.get("mentionText")
            or entity.get("normalizedValue", {}).get("text")
            or extract_text_from_text_anchor(entity.get("textAnchor", {}), full_text)
            or ""
        )

        items.append(
            {
                "field": field_name,
                "value": value,
                "confidence": entity.get("confidence"),
            }
        )

        properties = entity.get("properties", [])
        if properties:
            items.extend(collect_entity_fields(properties, full_text, parent=field_name))

    return items



def summarize_document_fields(document: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    fields = collect_entity_fields(document.get("entities", []), document.get("text", ""))
    return {"fields": fields}


async def resolve_document_from_request(request: Request) -> dict:
    content_type = request.headers.get("content-type", "")

    if content_type.startswith("application/json"):
        try:
            payload = JsonProcessRequestBody.model_validate(await request.json())
        except ValidationError as exc:
            raise RequestValidationError(exc.errors()) from exc

        return process_document_from_url(payload)

    if content_type.startswith("multipart/form-data"):
        return await process_document_from_form(request)

    raise HTTPException(
        status_code=415,
        detail="Content-Type must be application/json or multipart/form-data",
    )


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
    responses={400: {"model": ErrorResponse}, 415: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
async def document_ai_process(request: Request) -> dict:
    document = await resolve_document_from_request(request)
    return {"document": document}


@app.post(
    "/document-ai/process/raw",
    responses={400: {"model": ErrorResponse}, 415: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
async def document_ai_process_raw(request: Request) -> dict:
    document = await resolve_document_from_request(request)
    return {"document": document}


@app.post(
    "/document-ai/process/fields",
    responses={400: {"model": ErrorResponse}, 415: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
async def document_ai_process_fields(request: Request) -> dict:
    document = await resolve_document_from_request(request)
    return summarize_document_fields(document)
