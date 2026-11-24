"""API ingestion through real DocumentService wiring. Only Gemini is mocked."""

from pathlib import Path
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.db.database import SessionLocal
from app.db.models import DocumentStatus
from app.main import app
from app.repositories.chunk_repository import ChunkRepository
from app.repositories.document_repository import DocumentRepository
from app.services.ai.errors import AIAuthenticationError
from app.services.ai.provider import EmbeddingTask
from tests.conftest import make_settings, postgres_available
from tests.helpers.db import delete_document
from tests.helpers.pdfs import build_pdf


@pytest.fixture
def e2e_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    if not postgres_available():
        pytest.skip("PostgreSQL is not available for API tests.")

    settings = make_settings(
        storage_path=str(tmp_path),
        max_upload_size_mb=1,
        chunk_size=50,
        chunk_overlap=5,
    )
    provider = MagicMock()
    provider.create_embedding.side_effect = lambda text, task: [0.11] * 768
    monkeypatch.setattr("app.services.document_service.get_settings", lambda: settings)
    monkeypatch.setattr("app.services.document_service.get_ai_provider", lambda: provider)

    created_ids: list[UUID] = []
    with SessionLocal() as session:
        from app.core.bootstrap import bootstrap_default_admin
        from app.core.security import create_access_token
        admin = bootstrap_default_admin(
            session,
            email="e2e_admin@example.com",
            password="e2eadminpassword123",
            full_name="E2E Admin",
        )
        token = create_access_token(admin.id, admin.email)

    with TestClient(app, headers={"Authorization": f"Bearer {token}"}) as client:
        yield client, provider, created_ids, tmp_path

    for document_id in created_ids:
        delete_document(document_id)


def test_api_ingestion_end_to_end_with_mocked_gemini(e2e_client):
    client, provider, created_ids, tmp_path = e2e_client
    pdf = build_pdf(["End to end page one", "End to end page two"])

    response = client.post(
        "/api/v1/documents",
        files={"file": ("guide.pdf", pdf, "application/pdf")},
    )

    assert response.status_code == 201
    body = response.json()
    created_ids.append(UUID(body["id"]))
    assert body["status"] == "COMPLETED"
    assert body["original_filename"] == "guide.pdf"
    assert body["filename"] == "original.pdf"
    assert body["file_type"] == "application/pdf"
    assert body["file_size"] == len(pdf)
    assert body["page_count"] == 2
    assert "file_path" not in body
    assert "GEMINI" not in str(body)
    assert "Traceback" not in str(body)

    assert provider.create_embedding.called
    for call in provider.create_embedding.call_args_list:
        assert call.args[1] is EmbeddingTask.DOCUMENT

    detail = client.get(f"/api/v1/documents/{body['id']}")
    assert detail.status_code == 200
    assert detail.json()["status"] == "COMPLETED"
    assert detail.json()["page_count"] == 2

    stored = tmp_path / body["id"] / "original.pdf"
    assert stored.is_file()

    session = SessionLocal()
    try:
        loaded = DocumentRepository(session).get_by_id(UUID(body["id"]))
        assert loaded is not None
        assert loaded.status is DocumentStatus.COMPLETED
        chunks = ChunkRepository(session).list_by_document(UUID(body["id"]))
        assert len(chunks) >= 1
        assert all(len(chunk.embedding) == 768 for chunk in chunks)
        assert all(chunk.content for chunk in chunks)
    finally:
        session.close()


def test_api_processing_failure_returns_safe_error_and_failed_status(e2e_client):
    client, provider, created_ids, _tmp_path = e2e_client
    provider.create_embedding.side_effect = AIAuthenticationError(
        "Gemini authentication failed."
    )

    before_ids = {
        item["id"] for item in client.get("/api/v1/documents").json()["documents"]
    }

    response = client.post(
        "/api/v1/documents",
        files={"file": ("guide.pdf", build_pdf(["hello there"]), "application/pdf")},
    )

    assert response.status_code == 502
    assert response.json()["detail"] == (
        "The AI service is temporarily unavailable. Please try again later."
    )
    assert "authentication" not in response.json()["detail"].lower()
    assert "api_key" not in str(response.json()).lower()

    listed = client.get("/api/v1/documents").json()["documents"]
    created = [item for item in listed if item["id"] not in before_ids]
    assert len(created) == 1
    created_ids.append(UUID(created[0]["id"]))
    assert created[0]["status"] == "FAILED"

    session = SessionLocal()
    try:
        chunks = ChunkRepository(session).list_by_document(UUID(created[0]["id"]))
        assert chunks == []
    finally:
        session.close()


def test_api_missing_document_is_404(e2e_client):
    client, _provider, _created_ids, _tmp_path = e2e_client
    response = client.get(f"/api/v1/documents/{uuid4()}")
    assert response.status_code == 404
    assert response.json() == {"detail": "Document not found."}
