from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

from google.api_core.client_options import ClientOptions

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def mock_document_client(monkeypatch, document_payload):
    mock_doc = SimpleNamespace(_pb=document_payload)
    mock_client = Mock()
    mock_client.processor_path.return_value = (
        "projects/test-project/locations/us/processors/processor-123"
    )
    mock_client.processor_version_path.return_value = (
        "projects/test-project/locations/us/processors/processor-123/processorVersions/version-1"
    )
    mock_client.process_document.return_value = SimpleNamespace(document=mock_doc)

    client_factory = Mock(return_value=mock_client)
    monkeypatch.setattr("app.main.documentai.DocumentProcessorServiceClient", client_factory)
    monkeypatch.setattr("app.main.MessageToDict", lambda pb: pb)
    return mock_client, client_factory


def test_process_raw_document_success_from_json(monkeypatch):
    monkeypatch.setattr("app.main.fetch_file_bytes", lambda _: b"binary-image-content")
    mock_client, _ = mock_document_client(
        monkeypatch,
        {
            "text": "Hello World",
            "entities": [{"type": "invoice_id", "mentionText": "123", "confidence": 0.98}],
        },
    )

    response = client.post(
        "/document-ai/process/raw",
        json={
            "file_url": "https://example.com/sample.jpg",
            "mime_type": "image/jpeg",
            "project_id": "test-project",
            "location": "us",
            "processor_id": "processor-123",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "document": {
            "text": "Hello World",
            "entities": [{"type": "invoice_id", "mentionText": "123", "confidence": 0.98}],
        }
    }
    mock_client.processor_path.assert_called_once_with(
        project="test-project",
        location="us",
        processor="processor-123",
    )


def test_process_fields_success_from_json(monkeypatch):
    monkeypatch.setattr("app.main.fetch_file_bytes", lambda _: b"binary-image-content")
    _, _ = mock_document_client(
        monkeypatch,
        {
            "text": "Invoice Number 123",
            "entities": [
                {"type": "invoice_id", "mentionText": "123", "confidence": 0.98},
                {
                    "type": "supplier",
                    "mentionText": "OpenAI",
                    "confidence": 0.91,
                    "properties": [
                        {"type": "name", "mentionText": "OpenAI", "confidence": 0.91}
                    ],
                },
            ],
        },
    )

    response = client.post(
        "/document-ai/process/fields",
        json={
            "file_url": "https://example.com/sample.jpg",
            "mime_type": "image/jpeg",
            "project_id": "test-project",
            "location": "us",
            "processor_id": "processor-123",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "fields": {
            "invoice_id": {"value": "123", "confidence": 0.98},
            "supplier": {"value": "OpenAI", "confidence": 0.91},
            "supplier.name": {"value": "OpenAI", "confidence": 0.91},
        }
    }


def test_process_fields_groups_duplicate_field_names(monkeypatch):
    monkeypatch.setattr("app.main.fetch_file_bytes", lambda _: b"binary-image-content")
    _, _ = mock_document_client(
        monkeypatch,
        {
            "text": "Line items",
            "entities": [
                {"type": "line_item", "mentionText": "Taxi", "confidence": 0.95},
                {"type": "line_item", "mentionText": "Train", "confidence": 0.9},
            ],
        },
    )

    response = client.post(
        "/document-ai/process/fields",
        json={
            "file_url": "https://example.com/sample.jpg",
            "mime_type": "image/jpeg",
            "project_id": "test-project",
            "location": "us",
            "processor_id": "processor-123",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "fields": {
            "line_item": [
                {"value": "Taxi", "confidence": 0.95},
                {"value": "Train", "confidence": 0.9},
            ]
        }
    }


def test_process_fields_success_from_multipart(monkeypatch):
    _, _ = mock_document_client(
        monkeypatch,
        {
            "text": "Receipt Total 1999",
            "entities": [{"type": "total_amount", "mentionText": "1999", "confidence": 0.88}],
        },
    )

    response = client.post(
        "/document-ai/process/fields",
        data={
            "project_id": "test-project",
            "location": "us",
            "processor_id": "processor-123",
        },
        files={"file": ("sample.jpg", b"binary-image-content", "image/jpeg")},
    )

    assert response.status_code == 200
    assert response.json() == {
        "fields": {
            "total_amount": {"value": "1999", "confidence": 0.88},
        }
    }


def test_process_document_uses_processor_version(monkeypatch):
    monkeypatch.setattr("app.main.fetch_file_bytes", lambda _: b"pdf")
    mock_client, client_factory = mock_document_client(monkeypatch, {"text": "versioned", "entities": []})

    response = client.post(
        "/document-ai/process/raw",
        json={
            "file_url": "https://example.com/sample.pdf",
            "mime_type": "application/pdf",
            "project_id": "test-project",
            "location": "us",
            "processor_id": "processor-123",
            "processor_version": "version-1",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"document": {"text": "versioned", "entities": []}}
    mock_client.processor_version_path.assert_called_once_with(
        project="test-project",
        location="us",
        processor="processor-123",
        processor_version="version-1",
    )

    client_factory.assert_called_once()
    client_options = client_factory.call_args.kwargs["client_options"]
    assert isinstance(client_options, ClientOptions)
    assert client_options.api_endpoint == "us-documentai.googleapis.com"


def test_process_document_uses_regional_endpoint(monkeypatch):
    monkeypatch.setattr("app.main.fetch_file_bytes", lambda _: b"pdf")
    _, client_factory = mock_document_client(monkeypatch, {"text": "regional", "entities": []})

    response = client.post(
        "/document-ai/process/raw",
        json={
            "file_url": "https://example.com/sample.pdf",
            "mime_type": "application/pdf",
            "project_id": "test-project",
            "location": "asia-southeast1",
            "processor_id": "processor-123",
        },
    )

    assert response.status_code == 200
    client_factory.assert_called_once()
    client_options = client_factory.call_args.kwargs["client_options"]
    assert isinstance(client_options, ClientOptions)
    assert client_options.api_endpoint == "asia-southeast1-documentai.googleapis.com"


def test_invalid_mime_type_returns_validation_error_for_json():
    response = client.post(
        "/document-ai/process/raw",
        json={
            "file_url": "https://example.com/sample.gif",
            "mime_type": "image/gif",
            "project_id": "test-project",
            "location": "us",
            "processor_id": "processor-123",
        },
    )

    assert response.status_code == 422
    payload = response.json()
    assert payload["error"] is True
    assert "mime_type" in payload["message"]


def test_invalid_mime_type_returns_validation_error_for_multipart():
    response = client.post(
        "/document-ai/process/fields",
        data={
            "project_id": "test-project",
            "location": "us",
            "processor_id": "processor-123",
            "mime_type": "image/gif",
        },
        files={"file": ("sample.jpg", b"binary-image-content", "image/jpeg")},
    )

    assert response.status_code == 422
    payload = response.json()
    assert payload["error"] is True
    assert "mime_type must be one of image/jpeg, image/png, or application/pdf" in payload["message"]


def test_file_fetch_failure_returns_error(monkeypatch):
    def raise_http_exception(_):
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail="Failed to fetch file: boom")

    monkeypatch.setattr("app.main.fetch_file_bytes", raise_http_exception)

    response = client.post(
        "/document-ai/process/raw",
        json={
            "file_url": "https://example.com/missing.jpg",
            "mime_type": "image/jpeg",
            "project_id": "test-project",
            "location": "us",
            "processor_id": "processor-123",
        },
    )

    assert response.status_code == 400
    assert response.json() == {
        "error": True,
        "message": "Failed to fetch file: boom",
    }


def test_unsupported_content_type_returns_error():
    response = client.post(
        "/document-ai/process/fields",
        data={
            "project_id": "test-project",
            "location": "us",
            "processor_id": "processor-123",
        },
    )

    assert response.status_code == 415
    assert response.json() == {
        "error": True,
        "message": "Content-Type must be application/json or multipart/form-data",
    }


def test_legacy_process_path_returns_raw_document(monkeypatch):
    monkeypatch.setattr("app.main.fetch_file_bytes", lambda _: b"binary-image-content")
    mock_document_client(monkeypatch, {"text": "legacy", "entities": []})

    response = client.post(
        "/document-ai/process",
        json={
            "file_url": "https://example.com/sample.jpg",
            "mime_type": "image/jpeg",
            "project_id": "test-project",
            "location": "us",
            "processor_id": "processor-123",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"document": {"text": "legacy", "entities": []}}
