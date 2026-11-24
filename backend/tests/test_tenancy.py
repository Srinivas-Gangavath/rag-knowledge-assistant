"""Tenancy data model, scoping, and consistency tests for Phase 1.1."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from app.core.workspace_context import WorkspaceContext, WorkspaceContextProvider
from app.db.models import (
    Conversation,
    Document,
    DocumentChunk,
    DocumentStatus,
    Message,
    MessageRole,
    Organization,
    Workspace,
)
from app.repositories.chunk_repository import ChunkRepository
from app.repositories.conversation_repository import ConversationRepository, MessageRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.organization_repository import OrganizationRepository
from app.repositories.workspace_repository import WorkspaceRepository


def _zero_embedding() -> list[float]:
    return [0.0] * get_settings().embedding_dimension


def test_organization_creation(db_session):
    repo = OrganizationRepository(db_session)
    slug = f"org-{uuid.uuid4().hex[:8]}"
    org = repo.add(Organization(name="Acme Corp", slug=slug))

    stored = repo.get_by_id(org.id)
    assert stored is not None
    assert stored.name == "Acme Corp"
    assert stored.slug == slug
    assert stored.created_at is not None
    assert stored.updated_at is not None


def test_workspace_creation(db_session):
    org_repo = OrganizationRepository(db_session)
    ws_repo = WorkspaceRepository(db_session)

    org = org_repo.add(Organization(name="Org For WS", slug=f"org-{uuid.uuid4().hex[:8]}"))
    ws_slug = f"ws-{uuid.uuid4().hex[:8]}"
    workspace = ws_repo.add(
        Workspace(
            organization_id=org.id,
            name="Engineering Workspace",
            slug=ws_slug,
            settings={"retrieval_mode": "hybrid"},
        )
    )

    stored = ws_repo.get_by_id(workspace.id)
    assert stored is not None
    assert stored.organization_id == org.id
    assert stored.name == "Engineering Workspace"
    assert stored.slug == ws_slug
    assert stored.settings == {"retrieval_mode": "hybrid"}


def test_organization_workspace_relationship_and_cascade(db_session):
    org_repo = OrganizationRepository(db_session)
    ws_repo = WorkspaceRepository(db_session)

    org = org_repo.add(Organization(name="Org Cascade", slug=f"org-{uuid.uuid4().hex[:8]}"))
    ws1 = ws_repo.add(Workspace(organization_id=org.id, name="WS 1", slug="ws-1"))
    ws2 = ws_repo.add(Workspace(organization_id=org.id, name="WS 2", slug="ws-2"))

    db_session.refresh(org)
    assert len(org.workspaces) == 2
    assert {ws.id for ws in org.workspaces} == {ws1.id, ws2.id}

    # Delete organization -> cascades to workspaces
    org_repo.delete(org.id)
    assert ws_repo.get_by_id(ws1.id) is None
    assert ws_repo.get_by_id(ws2.id) is None


def test_document_workspace_scoping_and_cascade(db_session):
    org_repo = OrganizationRepository(db_session)
    ws_repo = WorkspaceRepository(db_session)
    doc_repo = DocumentRepository(db_session)

    org = org_repo.add(Organization(name="Org Doc", slug=f"org-{uuid.uuid4().hex[:8]}"))
    ws = ws_repo.add(Workspace(organization_id=org.id, name="WS Doc", slug="ws-doc"))

    doc = Document(
        workspace_id=ws.id,
        filename="test.pdf",
        original_filename="test.pdf",
        file_path="/storage/test.pdf",
        file_type="application/pdf",
        file_size=1024,
        status=DocumentStatus.UPLOADED,
    )
    doc_repo.add(doc)

    stored = doc_repo.get_by_id(doc.id, workspace_id=ws.id)
    assert stored is not None
    assert stored.workspace_id == ws.id
    assert stored.workspace.id == ws.id

    # Deleting workspace cascades to documents
    ws_repo.delete(ws.id)
    assert doc_repo.get_by_id(doc.id) is None


def test_chunk_workspace_scoping_and_cascade(db_session):
    org_repo = OrganizationRepository(db_session)
    ws_repo = WorkspaceRepository(db_session)
    doc_repo = DocumentRepository(db_session)
    chunk_repo = ChunkRepository(db_session)

    org = org_repo.add(Organization(name="Org Chunk", slug=f"org-{uuid.uuid4().hex[:8]}"))
    ws = ws_repo.add(Workspace(organization_id=org.id, name="WS Chunk", slug="ws-chunk"))

    doc = doc_repo.add(
        Document(
            workspace_id=ws.id,
            filename="chunk_test.pdf",
            original_filename="chunk_test.pdf",
            file_path="/storage/chunk_test.pdf",
            file_type="application/pdf",
            file_size=1024,
            status=DocumentStatus.COMPLETED,
        )
    )

    chunk = chunk_repo.add(
        DocumentChunk(
            workspace_id=ws.id,
            document_id=doc.id,
            chunk_index=0,
            content="Chunk content for tenancy test.",
            page_number=1,
            embedding=_zero_embedding(),
            chunk_metadata={"test": True},
        )
    )

    stored_chunk = chunk_repo.get_by_id(chunk.id)
    assert stored_chunk is not None
    assert stored_chunk.workspace_id == ws.id
    assert stored_chunk.document_id == doc.id
    assert stored_chunk.workspace.id == ws.id

    # Deleting workspace cascades to chunks
    ws_repo.delete(ws.id)
    assert chunk_repo.get_by_id(chunk.id) is None


def test_conversation_workspace_scoping_and_cascade(db_session):
    org_repo = OrganizationRepository(db_session)
    ws_repo = WorkspaceRepository(db_session)
    conv_repo = ConversationRepository(db_session)
    msg_repo = MessageRepository(db_session)

    org = org_repo.add(Organization(name="Org Conv", slug=f"org-{uuid.uuid4().hex[:8]}"))
    ws = ws_repo.add(Workspace(organization_id=org.id, name="WS Conv", slug="ws-conv"))

    conv = conv_repo.add(Conversation(workspace_id=ws.id, title="Tenant Conversation"))
    msg = msg_repo.add(
        Message(
            conversation_id=conv.id,
            role=MessageRole.USER,
            content="Hello tenant workspace",
        )
    )

    stored_conv = conv_repo.get_by_id(conv.id, workspace_id=ws.id)
    assert stored_conv is not None
    assert stored_conv.workspace_id == ws.id

    stored_msgs = msg_repo.list_by_conversation(conv.id)
    assert len(stored_msgs) == 1
    assert stored_msgs[0].id == msg.id

    # Deleting workspace cascades to conversations and their messages
    ws_repo.delete(ws.id)
    assert conv_repo.get_by_id(conv.id) is None
    assert msg_repo.list_by_conversation(conv.id) == []


def test_message_inherits_conversation_scope(db_session):
    conv_repo = ConversationRepository(db_session)
    msg_repo = MessageRepository(db_session)

    conv = conv_repo.add(Conversation(title="Scope Inheritance"))
    msg = msg_repo.add(
        Message(
            conversation_id=conv.id,
            role=MessageRole.USER,
            content="Message deriving scope from conversation",
        )
    )

    # Message does not have direct workspace_id column; derives via conversation
    assert not hasattr(Message, "workspace_id")
    assert msg.conversation.workspace_id == conv.workspace_id


def test_constraint_organization_slug_unique(db_session):
    org_repo = OrganizationRepository(db_session)
    slug = f"unique-org-{uuid.uuid4().hex[:8]}"
    org_repo.add(Organization(name="First Org", slug=slug))

    with pytest.raises(IntegrityError):
        org_repo.add(Organization(name="Second Org Duplicate", slug=slug))
    db_session.rollback()


def test_constraint_workspace_org_slug_unique(db_session):
    org_repo = OrganizationRepository(db_session)
    ws_repo = WorkspaceRepository(db_session)

    org = org_repo.add(Organization(name="Org Unique WS", slug=f"org-{uuid.uuid4().hex[:8]}"))
    ws_repo.add(Workspace(organization_id=org.id, name="WS 1", slug="shared-slug"))

    # Same organization, duplicate workspace slug must fail
    with pytest.raises(IntegrityError):
        ws_repo.add(Workspace(organization_id=org.id, name="WS 2", slug="shared-slug"))
    db_session.rollback()


def test_constraint_invalid_workspace_foreign_key(db_session):
    doc_repo = DocumentRepository(db_session)
    fake_ws_id = uuid.uuid4()

    doc = Document(
        workspace_id=fake_ws_id,
        filename="orphan.pdf",
        original_filename="orphan.pdf",
        file_path="/storage/orphan.pdf",
        file_type="application/pdf",
        file_size=100,
        status=DocumentStatus.UPLOADED,
    )
    with pytest.raises(IntegrityError):
        doc_repo.add(doc)
    db_session.rollback()


def test_chunk_document_workspace_id_consistency_invariant(db_session):
    """Verify that chunk.workspace_id cannot diverge from document.workspace_id."""
    org_repo = OrganizationRepository(db_session)
    ws_repo = WorkspaceRepository(db_session)
    doc_repo = DocumentRepository(db_session)

    org = org_repo.add(Organization(name="Org Invariant", slug=f"org-{uuid.uuid4().hex[:8]}"))
    ws1 = ws_repo.add(Workspace(organization_id=org.id, name="WS 1", slug="ws-1"))
    ws2 = ws_repo.add(Workspace(organization_id=org.id, name="WS 2", slug="ws-2"))

    doc = doc_repo.add(
        Document(
            workspace_id=ws1.id,
            filename="invariant.pdf",
            original_filename="invariant.pdf",
            file_path="/storage/invariant.pdf",
            file_type="application/pdf",
            file_size=100,
            status=DocumentStatus.COMPLETED,
        )
    )

    # Attempt to insert a chunk pointing to doc in ws1, but specifying ws2
    mismatched_chunk = DocumentChunk(
        workspace_id=ws2.id,
        document_id=doc.id,
        chunk_index=0,
        content="Mismatched chunk",
        page_number=1,
        embedding=_zero_embedding(),
        chunk_metadata={},
    )
    with pytest.raises((IntegrityError, ValueError)):
        db_session.add(mismatched_chunk)
        db_session.flush()
    db_session.rollback()


def test_workspace_context_provider(db_session):
    ctx = WorkspaceContextProvider.get_context(db_session)
    assert isinstance(ctx, WorkspaceContext)
    assert ctx.workspace_slug == "default"
    assert ctx.organization_slug == "default"
    assert ctx.workspace_id is not None
    assert ctx.organization_id is not None

    default_ws = WorkspaceContextProvider.get_default_workspace(db_session)
    assert default_ws.id == ctx.workspace_id
    assert default_ws.slug == "default"


def test_repository_workspace_filtering(db_session):
    org_repo = OrganizationRepository(db_session)
    ws_repo = WorkspaceRepository(db_session)
    doc_repo = DocumentRepository(db_session)
    chunk_repo = ChunkRepository(db_session)
    conv_repo = ConversationRepository(db_session)

    org = org_repo.add(Organization(name="Org Filter", slug=f"org-{uuid.uuid4().hex[:8]}"))
    ws1 = ws_repo.add(Workspace(organization_id=org.id, name="WS A", slug="ws-a"))
    ws2 = ws_repo.add(Workspace(organization_id=org.id, name="WS B", slug="ws-b"))

    # Documents
    doc1 = doc_repo.add(
        Document(
            workspace_id=ws1.id,
            filename="a.pdf",
            original_filename="a.pdf",
            file_path="/storage/a.pdf",
            file_type="application/pdf",
            file_size=100,
            status=DocumentStatus.COMPLETED,
        )
    )
    doc2 = doc_repo.add(
        Document(
            workspace_id=ws2.id,
            filename="b.pdf",
            original_filename="b.pdf",
            file_path="/storage/b.pdf",
            file_type="application/pdf",
            file_size=100,
            status=DocumentStatus.COMPLETED,
        )
    )

    # Chunks
    chunk1 = chunk_repo.add(
        DocumentChunk(
            workspace_id=ws1.id,
            document_id=doc1.id,
            chunk_index=0,
            content="Alpha knowledge for workspace A",
            page_number=1,
            embedding=_zero_embedding(),
            chunk_metadata={},
        )
    )
    chunk2 = chunk_repo.add(
        DocumentChunk(
            workspace_id=ws2.id,
            document_id=doc2.id,
            chunk_index=0,
            content="Beta knowledge for workspace B",
            page_number=1,
            embedding=_zero_embedding(),
            chunk_metadata={},
        )
    )

    # Conversations
    conv1 = conv_repo.add(Conversation(workspace_id=ws1.id, title="Conv A"))
    conv2 = conv_repo.add(Conversation(workspace_id=ws2.id, title="Conv B"))

    # Filter documents by workspace
    docs_ws1 = doc_repo.list_all(workspace_id=ws1.id)
    assert doc1.id in [d.id for d in docs_ws1]
    assert doc2.id not in [d.id for d in docs_ws1]

    # Filter conversations by workspace
    convs_ws1 = conv_repo.list_all(workspace_id=ws1.id)
    assert conv1.id in [c.id for c in convs_ws1]
    assert conv2.id not in [c.id for c in convs_ws1]

    # Filter similar search by workspace
    results_ws1 = chunk_repo.search_similar(
        _zero_embedding(),
        top_k=10,
        similarity_threshold=-1.0,
        workspace_id=ws1.id,
    )
    chunk_ids_ws1 = [c.id for c, _, _ in results_ws1]
    assert chunk1.id in chunk_ids_ws1
    assert chunk2.id not in chunk_ids_ws1

    # Filter lexical search by workspace
    lex_ws1 = chunk_repo.search_lexical(
        "knowledge",
        _zero_embedding(),
        top_k=10,
        workspace_id=ws1.id,
    )
    lex_chunk_ids_ws1 = [c.id for c, _, _, _, _ in lex_ws1]
    assert chunk1.id in lex_chunk_ids_ws1
    assert chunk2.id not in lex_chunk_ids_ws1


def test_migration_0006_structure():
    source = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "0006_orgs_and_workspaces.py"
    ).read_text(encoding="utf-8")

    assert "0006_orgs_and_workspaces" in source
    assert "0005_chunk_content_tsv" in source
    assert "create_table(\n        \"organizations\"" in source or "create_table(\n        'organizations'" in source or 'create_table("organizations"' in source or "create_table('organizations'" in source or '"organizations"' in source
    assert '"workspaces"' in source
    assert "fk_document_chunks_document_workspace" in source
    assert "uq_documents_id_workspace_id" in source
    assert "ix_documents_workspace_id" in source
    assert "ix_document_chunks_workspace_id" in source
    assert "ix_conversations_workspace_id" in source
    assert "def downgrade" in source
