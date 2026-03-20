from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_process_document_success(monkeypatch):
    monkeypatch.setattr(
        "app.main.fetch_file_bytes",
        lambda _: b"binary-image-content",
    )

    mock_doc = SimpleNamespace(_pb={
        "text": "Hello World",
        "entities": [{"type": "invoice_id", "mention_text": "123"}],
    })
    mock_client = Mock()
    mock_client.processor_path.return_value = (
        "projects/test-project/locations/us/processors/processor-123"
    )
    mock_client.process_document.return_value = SimpleNamespace(document=mock_doc)
    monkeypatch.setattr("app.main.documentai.DocumentProcessorServiceClient", lambda: mock_client)
    monkeypatch.setattr("app.main.MessageToDict", lambda pb: pb)

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
    assert response.json() == {
        "document": {
            "text": "Hello World",
            "entities": [{"type": "invoice_id", "mention_text": "123"}],
        }
    }
    mock_client.processor_path.assert_called_once_with(
        project="test-project",
        location="us",
        processor="processor-123",
    )
    mock_client.process_document.assert_called_once()


def test_process_document_uses_processor_version(monkeypatch):
    monkeypatch.setattr("app.main.fetch_file_bytes", lambda _: b"pdf")

    mock_doc = SimpleNamespace(_pb={"text": "versioned"})
    mock_client = Mock()
    mock_client.processor_version_path.return_value = (
        "projects/test-project/locations/us/processors/processor-123/processorVersions/version-1"
    )
    mock_client.process_document.return_value = SimpleNamespace(document=mock_doc)
    monkeypatch.setattr("app.main.documentai.DocumentProcessorServiceClient", lambda: mock_client)
    monkeypatch.setattr("app.main.MessageToDict", lambda pb: pb)

    response = client.post(
        "/document-ai/process",
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
    assert response.json() == {"document": {"text": "versioned"}}
    mock_client.processor_version_path.assert_called_once_with(
        project="test-project",
        location="us",
        processor="processor-123",
        processor_version="version-1",
    )


def test_invalid_mime_type_returns_validation_error():
    response = client.post(
        "/document-ai/process",
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


def test_file_fetch_failure_returns_error(monkeypatch):
    def raise_http_exception(_):
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail="Failed to fetch file: boom")

    monkeypatch.setattr("app.main.fetch_file_bytes", raise_http_exception)

    response = client.post(
        "/document-ai/process",
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
