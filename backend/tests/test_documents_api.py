from pathlib import Path
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.v1.documents import get_document_service
from app.db.database import get_db
from app.main import app
from app.repositories.chunk_repository import ChunkRepository
from app.services.document_service import DocumentService
from app.services.embedding_service import EmbeddingService
from app.services.storage import LocalDocumentStorage
from tests.conftest import make_settings, postgres_available
from tests.helpers.pdfs import build_pdf


@pytest.fixture
def api_client(db_session, tmp_path: Path) -> TestClient:
    if not postgres_available():
        pytest.skip("PostgreSQL is not available for API tests.")

    provider = MagicMock()
    provider.create_embedding.side_effect = lambda text, task: [0.2] * 768
    settings = make_settings(
        storage_path=str(tmp_path),
        max_upload_size_mb=1,
        chunk_size=50,
        chunk_overlap=5,
    )
    service = DocumentService(
        session=db_session,
        settings=settings,
        embedding_service=EmbeddingService(provider, settings),
        storage=LocalDocumentStorage(str(tmp_path)),
        autocommit=False,
    )

    def override_service() -> DocumentService:
        return service

    def override_db():
        yield db_session

    app.dependency_overrides[get_document_service] = override_service
    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def test_upload_valid_pdf(api_client: TestClient):
    pdf = build_pdf(["API upload page one", "API upload page two"])
    response = api_client.post(
        "/api/v1/documents",
        files={"file": ("guide.pdf", pdf, "application/pdf")},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "COMPLETED"
    assert body["original_filename"] == "guide.pdf"
    assert body["filename"] == "original.pdf"
    assert body["file_type"] == "application/pdf"
    assert body["file_size"] == len(pdf)
    assert body["page_count"] == 2
    assert body["category"] is None
    assert body["source"] is None
    assert body["tags"] == []
    assert "file_path" not in body
    assert "created_at" in body
    assert "updated_at" in body
    assert len(body["id"]) > 0


def _document_ids(api_client: TestClient) -> set[str]:
    return {item["id"] for item in api_client.get("/api/v1/documents").json()["documents"]}


def test_upload_missing_file(api_client: TestClient):
    response = api_client.post("/api/v1/documents")
    assert response.status_code == 422


def test_upload_invalid_extension(api_client: TestClient):
    before = _document_ids(api_client)
    response = api_client.post(
        "/api/v1/documents",
        files={"file": ("notes.txt", build_pdf(["hello"]), "application/pdf")},
    )
    assert response.status_code == 415
    assert response.json()["detail"] == "Only PDF files are supported."
    assert _document_ids(api_client) == before


def test_upload_invalid_content(api_client: TestClient):
    before = _document_ids(api_client)
    response = api_client.post(
        "/api/v1/documents",
        files={"file": ("notes.pdf", b"hello world", "application/pdf")},
    )
    assert response.status_code == 400
    assert "valid PDF" in response.json()["detail"]
    assert _document_ids(api_client) == before


def test_upload_empty_file(api_client: TestClient):
    before = _document_ids(api_client)
    response = api_client.post(
        "/api/v1/documents",
        files={"file": ("empty.pdf", b"", "application/pdf")},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "The uploaded file is empty."
    assert _document_ids(api_client) == before


def test_upload_wrong_content_type(api_client: TestClient):
    before = _document_ids(api_client)
    response = api_client.post(
        "/api/v1/documents",
        files={"file": ("notes.pdf", build_pdf(["hello"]), "image/png")},
    )
    assert response.status_code == 415
    assert _document_ids(api_client) == before


def test_upload_malformed_pdf(api_client: TestClient):
    before = _document_ids(api_client)
    response = api_client.post(
        "/api/v1/documents",
        files={"file": ("notes.pdf", b"%PDF-1.4\nnot a real document", "application/pdf")},
    )
    assert response.status_code == 400
    assert _document_ids(api_client) == before


def test_upload_oversized_file(api_client: TestClient):
    oversized = b"%PDF-1.4\n" + (b"x" * (1024 * 1024 + 1))
    response = api_client.post(
        "/api/v1/documents",
        files={"file": ("big.pdf", oversized, "application/pdf")},
    )
    assert response.status_code == 413


def test_upload_empty_pdf_fails(api_client: TestClient):
    before = _document_ids(api_client)
    response = api_client.post(
        "/api/v1/documents",
        files={"file": ("empty.pdf", build_pdf(["", ""]), "application/pdf")},
    )
    assert response.status_code == 422
    assert "extractable text" in response.json()["detail"]
    listed = api_client.get("/api/v1/documents").json()["documents"]
    created = [item for item in listed if item["id"] not in before]
    assert len(created) == 1
    assert created[0]["status"] == "FAILED"


def test_list_documents_empty_then_populated(api_client: TestClient):
    before = api_client.get("/api/v1/documents")
    assert before.status_code == 200
    before_ids = {item["id"] for item in before.json()["documents"]}

    created = api_client.post(
        "/api/v1/documents",
        files={"file": ("one.pdf", build_pdf(["content"]), "application/pdf")},
    )
    assert created.status_code == 201
    listed = api_client.get("/api/v1/documents")
    assert listed.status_code == 200
    after_ids = {item["id"] for item in listed.json()["documents"]}
    assert created.json()["id"] in after_ids
    assert after_ids - before_ids == {created.json()["id"]}


def test_list_documents_newest_first(api_client: TestClient):
    first = api_client.post(
        "/api/v1/documents",
        files={"file": ("older.pdf", build_pdf(["older"]), "application/pdf")},
    ).json()
    second = api_client.post(
        "/api/v1/documents",
        files={"file": ("newer.pdf", build_pdf(["newer"]), "application/pdf")},
    ).json()

    listed = api_client.get("/api/v1/documents")
    assert listed.status_code == 200
    documents = listed.json()["documents"]
    ids = [item["id"] for item in documents]
    assert ids.index(second["id"]) < ids.index(first["id"])
    assert all("file_path" not in item for item in documents)


def test_get_document_existing_and_missing(api_client: TestClient):
    created = api_client.post(
        "/api/v1/documents",
        files={"file": ("one.pdf", build_pdf(["content"]), "application/pdf")},
    ).json()

    found = api_client.get(f"/api/v1/documents/{created['id']}")
    assert found.status_code == 200
    assert found.json()["id"] == created["id"]
    assert found.json()["status"] == "COMPLETED"
    assert found.json()["file_type"] == "application/pdf"
    assert "file_path" not in found.json()

    missing = api_client.get(f"/api/v1/documents/{uuid4()}")
    assert missing.status_code == 404
    assert missing.json()["detail"] == "Document not found."


def test_get_document_rejects_malformed_id(api_client: TestClient):
    response = api_client.get("/api/v1/documents/not-a-uuid")
    assert response.status_code == 422
    assert "detail" in response.json()
    assert "Traceback" not in str(response.json())


def test_upload_path_traversal_filename_is_metadata_only(api_client: TestClient):
    pdf = build_pdf(["safe content"])
    response = api_client.post(
        "/api/v1/documents",
        files={"file": ("../../secret.pdf", pdf, "application/pdf")},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["original_filename"] == "secret.pdf"
    assert "file_path" not in body
    assert ".." not in body["original_filename"]


def test_upload_windows_path_filename_is_metadata_only(api_client: TestClient):
    pdf = build_pdf(["windows path content"])
    response = api_client.post(
        "/api/v1/documents",
        files={"file": (r"C:\Windows\System32\policy.pdf", pdf, "application/pdf")},
    )
    assert response.status_code == 201
    assert response.json()["original_filename"] == "policy.pdf"
    assert "file_path" not in response.json()


def test_delete_document_returns_204_and_removes_it(api_client: TestClient, tmp_path: Path):
    created = api_client.post(
        "/api/v1/documents",
        files={"file": ("one.pdf", build_pdf(["content to delete"]), "application/pdf")},
    ).json()
    stored = tmp_path / created["id"] / "original.pdf"
    assert stored.is_file()

    response = api_client.delete(f"/api/v1/documents/{created['id']}")
    assert response.status_code == 204
    assert response.content == b""
    assert api_client.get(f"/api/v1/documents/{created['id']}").status_code == 404
    listed_ids = {item["id"] for item in api_client.get("/api/v1/documents").json()["documents"]}
    assert created["id"] not in listed_ids
    assert not stored.exists()
    assert not stored.parent.exists()


def test_delete_missing_document_returns_404(api_client: TestClient):
    response = api_client.delete(f"/api/v1/documents/{uuid4()}")
    assert response.status_code == 404
    assert response.json()["detail"] == "Document not found."


def test_upload_with_optional_metadata(api_client: TestClient):
    pdf = build_pdf(["Metadata upload page"])
    response = api_client.post(
        "/api/v1/documents",
        files={"file": ("guide.pdf", pdf, "application/pdf")},
        data={
            "category": "policy",
            "source": "internal",
            "tags": '["benefits","leave"]',
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["category"] == "policy"
    assert body["source"] == "internal"
    assert body["tags"] == ["benefits", "leave"]

    listed = api_client.get("/api/v1/documents")
    found = next(item for item in listed.json()["documents"] if item["id"] == body["id"])
    assert found["category"] == "policy"
    assert found["tags"] == ["benefits", "leave"]


def test_upload_rejects_invalid_metadata(api_client: TestClient):
    pdf = build_pdf(["Invalid metadata page"])
    response = api_client.post(
        "/api/v1/documents",
        files={"file": ("guide.pdf", pdf, "application/pdf")},
        data={"category": "Not Valid"},
    )
    assert response.status_code == 422


def test_patch_document_metadata(api_client: TestClient, db_session):
    created = api_client.post(
        "/api/v1/documents",
        files={"file": ("guide.pdf", build_pdf(["Patch me"]), "application/pdf")},
    ).json()

    before_chunks = ChunkRepository(db_session).list_by_document(UUID(created["id"]))
    before = [
        (chunk.id, chunk.content, list(chunk.embedding), dict(chunk.chunk_metadata))
        for chunk in before_chunks
    ]

    patched = api_client.patch(
        f"/api/v1/documents/{created['id']}",
        json={"category": "finance", "source": "internal", "tags": ["pricing"]},
    )
    assert patched.status_code == 200
    body = patched.json()
    assert body["category"] == "finance"
    assert body["source"] == "internal"
    assert body["tags"] == ["pricing"]
    assert body["original_filename"] == "guide.pdf"
    assert body["status"] == "COMPLETED"
    assert "file_path" not in body

    after_chunks = ChunkRepository(db_session).list_by_document(UUID(created["id"]))
    after = [
        (chunk.id, chunk.content, list(chunk.embedding), dict(chunk.chunk_metadata))
        for chunk in after_chunks
    ]
    assert after == before


def test_patch_missing_document_returns_404(api_client: TestClient):
    response = api_client.patch(
        f"/api/v1/documents/{uuid4()}",
        json={"category": "policy"},
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Document not found."


def test_patch_rejects_unknown_field(api_client: TestClient):
    created = api_client.post(
        "/api/v1/documents",
        files={"file": ("guide.pdf", build_pdf(["x"]), "application/pdf")},
    ).json()
    response = api_client.patch(
        f"/api/v1/documents/{created['id']}",
        json={"filename": "hacked.pdf"},
    )
    assert response.status_code == 422


def test_get_document_source_evidence_success(api_client: TestClient):
    pdf = build_pdf(["This is passage one for citation testing.", "This is passage two for citation testing."])
    upload_res = api_client.post(
        "/api/v1/documents",
        files={"file": ("evidence_doc.pdf", pdf, "application/pdf")},
    )
    assert upload_res.status_code == 201
    doc_id = upload_res.json()["id"]

    res = api_client.get(f"/api/v1/documents/{doc_id}/sources/0")
    assert res.status_code == 200
    data = res.json()
    assert data["document_id"] == doc_id
    assert data["filename"] == "evidence_doc.pdf"
    assert data["chunk_index"] == 0
    assert "passage" in data["content"]
    assert "embedding" not in data
    assert "content_tsv" not in data
    assert "workspace_id" not in data


def test_get_document_source_evidence_invalid_chunk_index(api_client: TestClient):
    pdf = build_pdf(["Single page document content"])
    upload_res = api_client.post(
        "/api/v1/documents",
        files={"file": ("single.pdf", pdf, "application/pdf")},
    )
    doc_id = upload_res.json()["id"]

    res = api_client.get(f"/api/v1/documents/{doc_id}/sources/999")
    assert res.status_code == 404
    assert "not found" in res.json()["detail"].lower()

    # Negative index returns safe 404
    res_neg = api_client.get(f"/api/v1/documents/{doc_id}/sources/-1")
    assert res_neg.status_code == 404
    assert "not found" in res_neg.json()["detail"].lower()


def test_get_document_source_evidence_missing_doc(api_client: TestClient):
    res = api_client.get(f"/api/v1/documents/{uuid4()}/sources/0")
    assert res.status_code == 404
    assert res.json()["detail"] == "Document not found."


def test_get_document_source_evidence_truncation(api_client: TestClient, db_session):
    pdf = build_pdf(["Small passage for testing normal and truncated source evidence."])
    upload_res = api_client.post(
        "/api/v1/documents",
        files={"file": ("evidence_test.pdf", pdf, "application/pdf")},
    )
    assert upload_res.status_code == 201
    doc_id = upload_res.json()["id"]

    # 1. Test normal non-truncated response
    res_normal = api_client.get(f"/api/v1/documents/{doc_id}/sources/0")
    assert res_normal.status_code == 200
    data_normal = res_normal.json()
    assert data_normal["is_truncated"] is False
    assert "Small passage" in data_normal["content"]

    # 2. Directly update chunk content to exceed MAX_SOURCE_EVIDENCE_CHARS (3000)
    chunks = ChunkRepository(db_session).list_by_document(UUID(doc_id))
    assert len(chunks) > 0
    target_chunk = chunks[0]
    large_passage = "DeterministicSafePrefix " + ("Text " * 700)  # > 3500 chars
    target_chunk.content = large_passage
    db_session.flush()

    res_truncated = api_client.get(f"/api/v1/documents/{doc_id}/sources/{target_chunk.chunk_index}")
    assert res_truncated.status_code == 200
    data_truncated = res_truncated.json()
    assert data_truncated["is_truncated"] is True
    assert len(data_truncated["content"]) == 3000
    assert data_truncated["content"] == large_passage[:3000]
    assert data_truncated["content"].startswith("DeterministicSafePrefix")
    # Verify response schema strictly contains only allowed fields
    assert set(data_truncated.keys()) == {
        "document_id",
        "filename",
        "page_number",
        "chunk_index",
        "content",
        "is_truncated",
    }

