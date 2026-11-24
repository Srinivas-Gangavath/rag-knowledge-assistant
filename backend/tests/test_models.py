import uuid

from sqlalchemy import text

from app.core.config import get_settings
from app.db.models import (
    Conversation,
    Document,
    DocumentChunk,
    DocumentStatus,
    Message,
    MessageRole,
)
from app.repositories.chunk_repository import ChunkRepository
from app.repositories.conversation_repository import ConversationRepository, MessageRepository
from app.repositories.document_repository import DocumentRepository


def _document(**overrides) -> Document:
    values = {
        "filename": f"{uuid.uuid4()}.pdf",
        "original_filename": "handbook.pdf",
        "file_path": f"/storage/documents/{uuid.uuid4()}.pdf",
        "file_type": "application/pdf",
        "file_size": 2048,
        "status": DocumentStatus.UPLOADED,
        "page_count": 3,
    }
    values.update(overrides)
    return Document(**values)


def _zero_embedding() -> list[float]:
    return [0.0] * get_settings().embedding_dimension


def test_document_model_creation(db_session):
    repository = DocumentRepository(db_session)
    document = repository.add(_document())

    stored = repository.get_by_id(document.id)

    assert stored is not None
    assert stored.id == document.id
    assert stored.original_filename == "handbook.pdf"
    assert stored.status is DocumentStatus.UPLOADED
    assert stored.category is None
    assert stored.source is None
    assert stored.tags == []
    assert stored.created_at is not None
    assert stored.updated_at is not None


def test_document_status_values(db_session):
    repository = DocumentRepository(db_session)

    for status in DocumentStatus:
        document = repository.add(_document(status=status, filename=f"{status.value}.pdf"))
        stored = repository.get_by_id(document.id)
        assert stored is not None
        assert stored.status is status
        assert stored.status.value == status.value


def test_document_chunk_relationship_and_metadata(db_session):
    documents = DocumentRepository(db_session)
    chunks = ChunkRepository(db_session)
    document = documents.add(_document(page_count=1))

    metadata = {
        "document_id": str(document.id),
        "filename": document.original_filename,
        "page_number": 1,
        "chunk_index": 0,
    }
    chunk = chunks.add(
        DocumentChunk(
            document_id=document.id,
            chunk_index=0,
            content="RAG stores embeddings in PostgreSQL.",
            page_number=1,
            embedding=_zero_embedding(),
            chunk_metadata=metadata,
        )
    )

    db_session.refresh(document)

    assert chunk.document_id == document.id
    assert document.chunks[0].id == chunk.id
    assert document.chunks[0].chunk_metadata == metadata
    assert len(chunks.list_by_document(document.id)) == 1
    generated = db_session.execute(
        text("SELECT content_tsv FROM document_chunks WHERE id = :id"),
        {"id": chunk.id},
    ).scalar()
    assert generated is not None


def test_content_tsv_is_stored_generated_column_with_gin(db_session):
    generated = db_session.execute(
        text(
            """
            SELECT attgenerated
            FROM pg_attribute
            WHERE attrelid = 'document_chunks'::regclass
              AND attname = 'content_tsv'
            """
        )
    ).scalar()
    assert generated == "s"
    indexdef = db_session.execute(
        text(
            """
            SELECT indexdef FROM pg_indexes
            WHERE indexname = 'ix_document_chunks_content_tsv'
            """
        )
    ).scalar()
    assert indexdef is not None
    assert "gin" in indexdef.lower()
    assert "content_tsv" in indexdef


def test_migration_0005_is_reversible_generated_tsvector():
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "0005_chunk_content_tsv.py"
    ).read_text(encoding="utf-8")
    assert "GENERATED ALWAYS AS" in source
    assert "to_tsvector('simple'" in source
    assert "ix_document_chunks_content_tsv" in source
    assert "def downgrade" in source
    assert "drop_index" in source
    assert 'drop_column("document_chunks", "content_tsv")' in source
    assert "0004_document_metadata" in source


def test_embedding_column_uses_configured_dimension(db_session):
    documents = DocumentRepository(db_session)
    chunks = ChunkRepository(db_session)
    document = documents.add(_document())
    embedding = _zero_embedding()

    chunk = chunks.add(
        DocumentChunk(
            document_id=document.id,
            chunk_index=0,
            content="dimension check",
            page_number=1,
            embedding=embedding,
            chunk_metadata={"document_id": str(document.id), "chunk_index": 0},
        )
    )

    stored = chunks.get_by_id(chunk.id)

    assert stored is not None
    assert len(stored.embedding) == get_settings().embedding_dimension
    assert get_settings().embedding_dimension == 768


def test_deleting_document_removes_chunks(db_session):
    documents = DocumentRepository(db_session)
    chunks = ChunkRepository(db_session)
    document = documents.add(_document())
    chunks.add(
        DocumentChunk(
            document_id=document.id,
            chunk_index=0,
            content="orphan check",
            page_number=1,
            embedding=_zero_embedding(),
            chunk_metadata={"document_id": str(document.id), "chunk_index": 0},
        )
    )

    db_session.delete(document)
    db_session.flush()

    assert chunks.list_by_document(document.id) == []


def test_conversation_and_message_relationship(db_session):
    conversations = ConversationRepository(db_session)
    messages = MessageRepository(db_session)
    conversation = conversations.add(Conversation(title="Refund questions"))

    user = messages.add(
        Message(
            conversation_id=conversation.id,
            role=MessageRole.USER,
            content="What is the refund period?",
        )
    )
    assistant = messages.add(
        Message(
            conversation_id=conversation.id,
            role=MessageRole.ASSISTANT,
            content="The refund period is 30 days.",
            sources=[{"filename": "company-policy.pdf", "page_number": 1}],
        )
    )

    stored = messages.list_by_conversation(conversation.id)
    assert [item.id for item in stored] == [user.id, assistant.id]
    assert stored[0].role is MessageRole.USER
    assert stored[1].sources[0]["filename"] == "company-policy.pdf"


def test_deleting_conversation_removes_messages(db_session):
    conversations = ConversationRepository(db_session)
    messages = MessageRepository(db_session)
    conversation = conversations.add(Conversation())
    messages.add(
        Message(
            conversation_id=conversation.id,
            role=MessageRole.USER,
            content="Hello",
        )
    )

    conversations.delete(conversation.id)

    assert conversations.get_by_id(conversation.id) is None
    assert messages.list_by_conversation(conversation.id) == []
