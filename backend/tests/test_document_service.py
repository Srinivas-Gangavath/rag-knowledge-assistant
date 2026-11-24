from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.db.database import SessionLocal
from app.db.models import DocumentStatus
from app.repositories.chunk_repository import ChunkRepository
from app.repositories.document_repository import DocumentRepository
from app.services.ai.errors import AIAuthenticationError, EmbeddingDimensionError
from app.services.document_errors import (
    DocumentNotFoundError,
    EmptyPdfError,
    InvalidPdfError,
    StorageError,
)
from app.services.chunker import RecursiveChunker
from app.services.document_service import DocumentService
from app.services.embedding_service import EmbeddingService
from app.services.storage import LocalDocumentStorage
from tests.conftest import make_settings, postgres_available
from tests.helpers.db import delete_document
from tests.helpers.pdfs import build_pdf


def _service(db_session, tmp_path: Path, embedding_service: EmbeddingService) -> DocumentService:
    settings = make_settings(storage_path=str(tmp_path), chunk_size=50, chunk_overlap=5)
    return DocumentService(
        session=db_session,
        settings=settings,
        embedding_service=embedding_service,
        storage=LocalDocumentStorage(str(tmp_path)),
        autocommit=False,
    )


def _provider_vectors() -> MagicMock:
    provider = MagicMock()
    provider.create_embedding.side_effect = lambda text, task: [0.25] * 768
    return provider


def test_successful_ingestion_flow(db_session, tmp_path: Path):
    embedding_service = EmbeddingService(_provider_vectors(), make_settings())
    service = _service(db_session, tmp_path, embedding_service)
    pdf = build_pdf(["Ingestion works on page one.", "Page two has more words for chunks."])

    document = service.ingest_pdf("handbook.pdf", "application/pdf", pdf)

    assert document.status is DocumentStatus.COMPLETED
    assert document.page_count == 2
    assert document.original_filename == "handbook.pdf"
    assert document.filename == "original.pdf"
    assert Path(document.file_path).is_file()
    assert Path(document.file_path).name == "original.pdf"
    assert str(document.id) in document.file_path

    chunks = service._chunks.list_by_document(document.id)
    assert len(chunks) >= 1
    assert chunks[0].chunk_index == 0
    assert chunks[0].content
    assert chunks[0].page_number in {1, 2}
    assert len(chunks[0].embedding) == 768
    assert chunks[0].chunk_metadata["document_id"] == str(document.id)
    assert chunks[0].chunk_metadata["filename"] == "handbook.pdf"
    assert "page_number" in chunks[0].chunk_metadata
    assert "chunk_index" in chunks[0].chunk_metadata
    assert chunks[0].chunk_metadata["chunking_strategy"] == "fixed_word_window"
    assert document.category is None
    assert document.source is None
    assert document.tags == []
    assert "category" not in chunks[0].chunk_metadata
    assert "source" not in chunks[0].chunk_metadata
    assert "tags" not in chunks[0].chunk_metadata


def test_ingestion_records_recursive_strategy_in_metadata(db_session, tmp_path: Path):
    settings = make_settings(
        storage_path=str(tmp_path),
        chunking_strategy="recursive",
        chunk_size=50,
        chunk_overlap=5,
    )
    embedding_service = EmbeddingService(_provider_vectors(), settings)
    service = DocumentService(
        session=db_session,
        settings=settings,
        embedding_service=embedding_service,
        storage=LocalDocumentStorage(str(tmp_path)),
        autocommit=False,
    )
    pdf = build_pdf(["Recursive ingestion writes strategy metadata."])

    document = service.ingest_pdf("policy.pdf", "application/pdf", pdf)
    chunks = service._chunks.list_by_document(document.id)

    assert isinstance(service._chunker, RecursiveChunker)
    assert chunks[0].chunk_metadata["chunking_strategy"] == "recursive"
    assert chunks[0].chunk_metadata["filename"] == "policy.pdf"


def _created_after(service, before_ids: set) -> list:
    return [item for item in service.list_documents() if item.id not in before_ids]


def test_storage_failure_marks_failed(db_session, tmp_path: Path):
    storage = MagicMock()
    storage.save_original.side_effect = StorageError()
    service = DocumentService(
        session=db_session,
        settings=make_settings(storage_path=str(tmp_path)),
        embedding_service=EmbeddingService(_provider_vectors(), make_settings()),
        storage=storage,
        autocommit=False,
    )

    before = {item.id for item in service.list_documents()}
    with pytest.raises(StorageError):
        service.ingest_pdf("doc.pdf", "application/pdf", build_pdf(["hello"]))

    created = _created_after(service, before)
    assert len(created) == 1
    assert created[0].status is DocumentStatus.FAILED


def test_parsing_failure_marks_failed(db_session, tmp_path: Path):
    parser = MagicMock()
    parser.parse_path.side_effect = InvalidPdfError()
    service = DocumentService(
        session=db_session,
        settings=make_settings(storage_path=str(tmp_path)),
        parser=parser,
        embedding_service=EmbeddingService(_provider_vectors(), make_settings()),
        storage=LocalDocumentStorage(str(tmp_path)),
        autocommit=False,
    )

    before = {item.id for item in service.list_documents()}
    with pytest.raises(InvalidPdfError):
        service.ingest_pdf("doc.pdf", "application/pdf", build_pdf(["hello"]))

    created = _created_after(service, before)
    assert len(created) == 1
    assert created[0].status is DocumentStatus.FAILED


def test_empty_pdf_marks_failed(db_session, tmp_path: Path):
    service = _service(
        db_session,
        tmp_path,
        EmbeddingService(_provider_vectors(), make_settings()),
    )

    before = {item.id for item in service.list_documents()}
    with pytest.raises(EmptyPdfError):
        service.ingest_pdf("empty.pdf", "application/pdf", build_pdf(["", ""]))

    created = _created_after(service, before)
    assert len(created) == 1
    assert created[0].status is DocumentStatus.FAILED
    assert service._chunks.list_by_document(created[0].id) == []


def test_chunking_failure_marks_failed(db_session, tmp_path: Path):
    chunker = MagicMock()
    chunker.chunk.side_effect = ValueError("chunking exploded")
    service = DocumentService(
        session=db_session,
        settings=make_settings(storage_path=str(tmp_path)),
        chunker=chunker,
        embedding_service=EmbeddingService(_provider_vectors(), make_settings()),
        storage=LocalDocumentStorage(str(tmp_path)),
        autocommit=False,
    )

    before = {item.id for item in service.list_documents()}
    with pytest.raises(Exception):
        service.ingest_pdf("doc.pdf", "application/pdf", build_pdf(["hello there"]))

    created = _created_after(service, before)
    assert len(created) == 1
    assert created[0].status is DocumentStatus.FAILED


def test_embedding_failure_marks_failed(db_session, tmp_path: Path):
    provider = MagicMock()
    provider.create_embedding.side_effect = AIAuthenticationError("Gemini authentication failed.")
    service = _service(
        db_session,
        tmp_path,
        EmbeddingService(provider, make_settings()),
    )

    before = {item.id for item in service.list_documents()}
    with pytest.raises(AIAuthenticationError):
        service.ingest_pdf("doc.pdf", "application/pdf", build_pdf(["hello"]))

    created = _created_after(service, before)
    assert len(created) == 1
    assert created[0].status is DocumentStatus.FAILED
    assert service._chunks.list_by_document(created[0].id) == []


def test_dimension_mismatch_marks_failed(db_session, tmp_path: Path):
    provider = MagicMock()
    provider.create_embedding.return_value = [0.1] * 8
    service = _service(
        db_session,
        tmp_path,
        EmbeddingService(provider, make_settings()),
    )

    before = {item.id for item in service.list_documents()}
    with pytest.raises(EmbeddingDimensionError):
        service.ingest_pdf("doc.pdf", "application/pdf", build_pdf(["hello"]))

    created = _created_after(service, before)
    assert len(created) == 1
    assert created[0].status is DocumentStatus.FAILED


def test_database_failure_marks_failed(db_session, tmp_path: Path):
    service = _service(
        db_session,
        tmp_path,
        EmbeddingService(_provider_vectors(), make_settings()),
    )
    service._chunks.add_many = MagicMock(side_effect=SQLAlchemyError("write failed"))

    before = {item.id for item in service.list_documents()}
    with pytest.raises(Exception):
        service.ingest_pdf("doc.pdf", "application/pdf", build_pdf(["hello"]))

    created = _created_after(service, before)
    assert len(created) == 1
    assert created[0].status is DocumentStatus.FAILED


def _committed_service(tmp_path: Path, embedding_service: EmbeddingService) -> tuple[DocumentService, object]:
    session = SessionLocal()
    settings = make_settings(storage_path=str(tmp_path), chunk_size=50, chunk_overlap=5)
    service = DocumentService(
        session=session,
        settings=settings,
        embedding_service=embedding_service,
        storage=LocalDocumentStorage(str(tmp_path)),
        autocommit=True,
    )
    return service, session


def test_successful_ingestion_is_visible_in_a_new_session(tmp_path: Path):
    if not postgres_available():
        pytest.skip("PostgreSQL is not available for database tests.")

    document_id = None
    service, session = _committed_service(
        tmp_path,
        EmbeddingService(_provider_vectors(), make_settings()),
    )
    try:
        document = service.ingest_pdf(
            "handbook.pdf",
            "application/pdf",
            build_pdf(["Persisted page one.", "Persisted page two."]),
        )
        document_id = document.id
    finally:
        session.close()

    try:
        other = SessionLocal()
        try:
            loaded = DocumentRepository(other).get_by_id(document_id)
            assert loaded is not None
            assert loaded.status is DocumentStatus.COMPLETED
            assert loaded.page_count == 2
            assert loaded.original_filename == "handbook.pdf"
            assert loaded.file_type == "application/pdf"

            chunks = ChunkRepository(other).list_by_document(document_id)
            assert len(chunks) >= 1
            assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))
            assert all(chunk.content for chunk in chunks)
            assert all(len(chunk.embedding) == 768 for chunk in chunks)
            assert all(chunk.chunk_metadata["document_id"] == str(document_id) for chunk in chunks)
        finally:
            other.close()
    finally:
        if document_id is not None:
            delete_document(document_id)


def test_embedding_failure_persists_failed_without_partial_chunks(tmp_path: Path):
    if not postgres_available():
        pytest.skip("PostgreSQL is not available for database tests.")

    provider = MagicMock()
    provider.create_embedding.side_effect = AIAuthenticationError(
        "Gemini authentication failed."
    )
    document_id = None
    service, session = _committed_service(
        tmp_path,
        EmbeddingService(provider, make_settings()),
    )
    try:
        before = {item.id for item in service.list_documents()}
        with pytest.raises(AIAuthenticationError):
            service.ingest_pdf(
                "doc.pdf",
                "application/pdf",
                build_pdf(["hello there", "second page text"]),
            )
        created = _created_after(service, before)
        assert len(created) == 1
        document_id = created[0].id
        assert created[0].status is DocumentStatus.FAILED
    finally:
        session.close()

    try:
        other = SessionLocal()
        try:
            loaded = DocumentRepository(other).get_by_id(document_id)
            assert loaded is not None
            assert loaded.status is DocumentStatus.FAILED
            assert ChunkRepository(other).list_by_document(document_id) == []
        finally:
            other.close()
    finally:
        if document_id is not None:
            delete_document(document_id)


def test_successful_ingestion_after_failed_ingestion(db_session, tmp_path: Path):
    failing_provider = MagicMock()
    failing_provider.create_embedding.side_effect = AIAuthenticationError(
        "Gemini authentication failed."
    )
    before = {
        item.id
        for item in _service(
            db_session,
            tmp_path,
            EmbeddingService(failing_provider, make_settings()),
        ).list_documents()
    }

    with pytest.raises(AIAuthenticationError):
        _service(
            db_session,
            tmp_path,
            EmbeddingService(failing_provider, make_settings()),
        ).ingest_pdf("fail.pdf", "application/pdf", build_pdf(["this upload fails"]))

    document = _service(
        db_session,
        tmp_path,
        EmbeddingService(_provider_vectors(), make_settings()),
    ).ingest_pdf("ok.pdf", "application/pdf", build_pdf(["this upload succeeds"]))

    created = {
        item.original_filename: item
        for item in _service(
            db_session,
            tmp_path,
            EmbeddingService(_provider_vectors(), make_settings()),
        ).list_documents()
        if item.id not in before
    }
    assert created["fail.pdf"].status is DocumentStatus.FAILED
    assert created["ok.pdf"].status is DocumentStatus.COMPLETED
    assert document.status is DocumentStatus.COMPLETED
    assert document.original_filename == "ok.pdf"
    assert document.id not in before


def test_delete_document_removes_row_chunks_and_file(db_session, tmp_path: Path):
    service = _service(
        db_session,
        tmp_path,
        EmbeddingService(_provider_vectors(), make_settings()),
    )
    document = service.ingest_pdf(
        "handbook.pdf",
        "application/pdf",
        build_pdf(["Delete removes this page."]),
    )
    stored = Path(document.file_path)
    assert stored.is_file()
    assert service._chunks.list_by_document(document.id)

    service.delete_document(document.id)

    assert service._documents.get_by_id(document.id) is None
    assert service._chunks.list_by_document(document.id) == []
    assert not stored.exists()
    assert not stored.parent.exists()


def test_delete_missing_document_returns_not_found(db_session, tmp_path: Path):
    service = _service(
        db_session,
        tmp_path,
        EmbeddingService(_provider_vectors(), make_settings()),
    )
    with pytest.raises(DocumentNotFoundError):
        service.delete_document(uuid4())


def test_ingest_accepts_optional_metadata(db_session, tmp_path: Path):
    service = _service(
        db_session,
        tmp_path,
        EmbeddingService(_provider_vectors(), make_settings()),
    )
    document = service.ingest_pdf(
        "policy.pdf",
        "application/pdf",
        build_pdf(["Policy page with metadata."]),
        category="policy",
        source="internal",
        tags=["refunds", "benefits"],
    )
    assert document.category == "policy"
    assert document.source == "internal"
    assert document.tags == ["refunds", "benefits"]
    chunks = service._chunks.list_by_document(document.id)
    assert "category" not in chunks[0].chunk_metadata
    assert chunks[0].chunk_metadata["chunking_strategy"] == "fixed_word_window"


def test_update_metadata_does_not_touch_chunks_or_embeddings(db_session, tmp_path: Path):
    service = _service(
        db_session,
        tmp_path,
        EmbeddingService(_provider_vectors(), make_settings()),
    )
    document = service.ingest_pdf(
        "policy.pdf",
        "application/pdf",
        build_pdf(["Unchanged chunk text."]),
        category="policy",
        source="internal",
        tags=["refunds"],
    )
    before_chunks = service._chunks.list_by_document(document.id)
    before = [
        (chunk.id, chunk.content, list(chunk.embedding), dict(chunk.chunk_metadata), chunk.page_number)
        for chunk in before_chunks
    ]
    before_path = document.file_path
    before_status = document.status
    before_filename = document.original_filename

    updated = service.update_metadata(
        document.id,
        {"category": "finance", "source": "vendor", "tags": ["pricing"]},
    )
    assert updated.category == "finance"
    assert updated.source == "vendor"
    assert updated.tags == ["pricing"]
    assert updated.file_path == before_path
    assert updated.status is before_status
    assert updated.original_filename == before_filename

    after_chunks = service._chunks.list_by_document(document.id)
    after = [
        (chunk.id, chunk.content, list(chunk.embedding), dict(chunk.chunk_metadata), chunk.page_number)
        for chunk in after_chunks
    ]
    assert after == before

