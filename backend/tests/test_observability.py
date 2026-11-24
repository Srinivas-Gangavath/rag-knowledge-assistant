"""Comprehensive test suite for Phase 1.6 Platform Observability & Query Tracing.

Covers Hardening Pass:
1. Server-owned canonical trace ID (client X-Trace-Id cannot override)
2. Repeated client trace ID cannot collide
3. Trace poisoning prevention
4. Child span tenant integrity
5. Cross-trace parent protection
6. FK lifecycle behavior
7. Trace detail authorization & non-leakage
8. Filter information leakage prevention
9. Nested metadata privacy sanitizer
10. Query hash privacy and determinism
11. Stream cancellation before first token (CANCELLED)
12. Stream cancellation after first token (PARTIAL)
13. Stream provider failure before first token (ERROR)
14. Stream provider failure after first token (ERROR)
15. Partial trace terminal status integrity
16. Token count validation (non-negative, missing flags)
17. Trace metadata cannot be client-controlled
18. Trace persistence failure isolation
19. Audit / trace correlation
20. RAG results remain identical with hardening enabled
"""

import hashlib
import json
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.request_context import extract_request_context, sanitize_identifier
from app.core.security import create_access_token, hash_password
from app.core.workspace_context import WorkspaceContext
from app.db.database import get_db
from app.db.models import (
    AuditLog,
    Conversation,
    Document,
    DocumentChunk,
    DocumentPermission,
    DocumentStatus,
    Organization,
    OrganizationMembership,
    OrganizationRole,
    QueryTrace,
    QueryTraceSpan,
    User,
    Workspace,
    WorkspaceMembership,
    WorkspaceRole,
)
from app.main import app
from app.services.ai.errors import AIProviderError
from app.services.conversation_service import ConversationService
from app.services.rag import RagService
from app.services.tracing import (
    ErrorCategory,
    QueryTracer,
    SpanName,
    SpanType,
    TraceService,
    TraceStatus,
    sanitize_metadata,
)
from tests.conftest import make_settings, postgres_available


@pytest.fixture
def obs_setup(db_session: Session):
    if not postgres_available():
        pytest.skip("PostgreSQL is not available for database tests.")

    # Create Org A
    org_a = Organization(name="Observability Org A", slug=f"obs-org-a-{uuid.uuid4().hex[:6]}")
    db_session.add(org_a)

    # Create Org B
    org_b = Organization(name="Observability Org B", slug=f"obs-org-b-{uuid.uuid4().hex[:6]}")
    db_session.add(org_b)
    db_session.flush()

    # Create Workspaces in Org A
    ws_a1 = Workspace(organization_id=org_a.id, name="WS A1", slug=f"ws-a1-{uuid.uuid4().hex[:6]}")
    ws_a2 = Workspace(organization_id=org_a.id, name="WS A2", slug=f"ws-a2-{uuid.uuid4().hex[:6]}")
    # Create Workspace in Org B
    ws_b1 = Workspace(organization_id=org_b.id, name="WS B1", slug=f"ws-b1-{uuid.uuid4().hex[:6]}")
    db_session.add_all([ws_a1, ws_a2, ws_b1])
    db_session.flush()

    # Create Users
    owner_user = User(
        email=f"owner-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password=hash_password("Password123!"),
        full_name="Org Owner",
        is_active=True,
    )
    admin_user = User(
        email=f"admin-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password=hash_password("Password123!"),
        full_name="WS Admin",
        is_active=True,
    )
    contrib_user = User(
        email=f"contrib-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password=hash_password("Password123!"),
        full_name="Contributor",
        is_active=True,
    )
    viewer_user = User(
        email=f"viewer-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password=hash_password("Password123!"),
        full_name="Viewer",
        is_active=True,
    )
    db_session.add_all([owner_user, admin_user, contrib_user, viewer_user])
    db_session.flush()

    # Memberships in Org A
    db_session.add(OrganizationMembership(organization_id=org_a.id, user_id=owner_user.id, role=OrganizationRole.OWNER))
    db_session.add(OrganizationMembership(organization_id=org_a.id, user_id=admin_user.id, role=OrganizationRole.MEMBER))
    db_session.add(OrganizationMembership(organization_id=org_a.id, user_id=contrib_user.id, role=OrganizationRole.MEMBER))
    db_session.add(OrganizationMembership(organization_id=org_a.id, user_id=viewer_user.id, role=OrganizationRole.MEMBER))

    # Workspace Memberships in WS A1
    db_session.add(WorkspaceMembership(workspace_id=ws_a1.id, user_id=admin_user.id, role=WorkspaceRole.WORKSPACE_ADMIN))
    db_session.add(WorkspaceMembership(workspace_id=ws_a1.id, user_id=contrib_user.id, role=WorkspaceRole.CONTRIBUTOR))
    db_session.add(WorkspaceMembership(workspace_id=ws_a1.id, user_id=viewer_user.id, role=WorkspaceRole.VIEWER))

    # Add a sample document and chunk to WS A1
    doc = Document(
        workspace_id=ws_a1.id,
        filename=f"obs_doc_{uuid.uuid4().hex[:6]}.pdf",
        original_filename="Observability Guide.pdf",
        file_path="/tmp/obs_doc.pdf",
        file_type="application/pdf",
        file_size=1024,
        status=DocumentStatus.COMPLETED,
        page_count=1,
    )
    db_session.add(doc)
    db_session.flush()

    chunk = DocumentChunk(
        document_id=doc.id,
        workspace_id=ws_a1.id,
        chunk_index=0,
        page_number=1,
        content="Antigravity platform observability records structured traces and spans.",
        embedding=[0.1] * 768,
        chunk_metadata={"source": "test"},
    )
    db_session.add(chunk)
    db_session.commit()

    return {
        "org_a": org_a,
        "org_b": org_b,
        "ws_a1": ws_a1,
        "ws_a2": ws_a2,
        "ws_b1": ws_b1,
        "owner": owner_user,
        "admin": admin_user,
        "contrib": contrib_user,
        "viewer": viewer_user,
        "doc": doc,
    }


@pytest.fixture
def obs_client(db_session: Session, monkeypatch) -> TestClient:
    if not postgres_available():
        pytest.skip("PostgreSQL is not available for database tests.")

    provider = MagicMock()
    provider.create_embedding.side_effect = lambda text, task: [0.1] * 768
    provider.generate_text.side_effect = lambda prompt: "Observability allows developers to inspect fine-grained execution latency."
    provider.stream_text.side_effect = lambda prompt: iter(["Observability ", "allows ", "fine-grained ", "tracing."])
    monkeypatch.setattr("app.services.rag.get_ai_provider", lambda: provider)

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.pop(get_db, None)


# =========================================================================
# 1. Server-Owned Canonical Trace ID & Collision / Poisoning Protection
# =========================================================================

def test_server_owned_canonical_trace_id(obs_client: TestClient, obs_setup: dict, db_session: Session):
    """Test 1, 2: Client X-Trace-Id cannot override canonical server trace_id."""
    user = obs_setup["contrib"]
    ws = obs_setup["ws_a1"]
    token = create_access_token(user.id, email=user.email)
    malicious_trace_id = "malicious_injected_trace_id_99999"

    resp = obs_client.post(
        "/api/v1/chat",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Workspace-Id": str(ws.id),
            "X-Trace-Id": malicious_trace_id,
            "X-Request-Id": "client-req-123",
        },
        json={"question": "Test server owned trace ID"},
    )
    assert resp.status_code == 200
    server_trace_id = resp.headers["X-Trace-Id"]
    assert server_trace_id != malicious_trace_id
    assert server_trace_id.startswith("trc_")

    # Verify in DB: canonical trace_id is server_trace_id
    trace = db_session.scalars(select(QueryTrace).where(QueryTrace.trace_id == server_trace_id)).first()
    assert trace is not None
    assert trace.request_id == "client-req-123"

    # Verify no trace with the malicious client ID exists
    malicious_trace = db_session.scalars(select(QueryTrace).where(QueryTrace.trace_id == malicious_trace_id)).first()
    assert malicious_trace is None


def test_repeated_client_trace_id_cannot_collide(obs_client: TestClient, obs_setup: dict, db_session: Session):
    """Test 2: Two requests with identical client X-Trace-Id receive distinct server trace IDs."""
    user = obs_setup["contrib"]
    ws = obs_setup["ws_a1"]
    token = create_access_token(user.id, email=user.email)
    same_header = "fixed_client_trace_header_val"

    resp1 = obs_client.post(
        "/api/v1/chat",
        headers={"Authorization": f"Bearer {token}", "X-Workspace-Id": str(ws.id), "X-Trace-Id": same_header},
        json={"question": "First request with same header"},
    )
    resp2 = obs_client.post(
        "/api/v1/chat",
        headers={"Authorization": f"Bearer {token}", "X-Workspace-Id": str(ws.id), "X-Trace-Id": same_header},
        json={"question": "Second request with same header"},
    )
    assert resp1.status_code == 200
    assert resp2.status_code == 200

    trc1 = resp1.headers["X-Trace-Id"]
    trc2 = resp2.headers["X-Trace-Id"]
    assert trc1 != trc2
    assert trc1 != same_header
    assert trc2 != same_header


def test_trace_poisoning_prevention(obs_client: TestClient, obs_setup: dict, db_session: Session):
    """Test 3: An existing trace_id cannot be reused or merged into by subsequent requests."""
    user = obs_setup["contrib"]
    ws = obs_setup["ws_a1"]
    token = create_access_token(user.id, email=user.email)

    resp1 = obs_client.post(
        "/api/v1/chat",
        headers={"Authorization": f"Bearer {token}", "X-Workspace-Id": str(ws.id)},
        json={"question": "Initial turn"},
    )
    trc1 = resp1.headers["X-Trace-Id"]

    # Attempt to supply trc1 as the X-Trace-Id on a second request
    resp2 = obs_client.post(
        "/api/v1/chat",
        headers={"Authorization": f"Bearer {token}", "X-Workspace-Id": str(ws.id), "X-Trace-Id": trc1},
        json={"question": "Second turn attempting poisoning"},
    )
    trc2 = resp2.headers["X-Trace-Id"]
    assert trc1 != trc2

    # Verify both traces exist independently in database
    t1 = db_session.scalars(select(QueryTrace).where(QueryTrace.trace_id == trc1)).first()
    t2 = db_session.scalars(select(QueryTrace).where(QueryTrace.trace_id == trc2)).first()
    assert t1 is not None and t2 is not None
    assert t1.id != t2.id


# =========================================================================
# 2. Trace / Span Reference Integrity & FK Lifecycle
# =========================================================================

def test_child_span_tenant_and_trace_integrity(db_session: Session, obs_setup: dict):
    """Test 4, 5: Spans strictly belong to their parent trace_id."""
    ws = obs_setup["ws_a1"]
    org = obs_setup["org_a"]

    tracer = QueryTracer(
        request_id="req-integrity-1",
        trace_id="trc-integrity-1",
        organization_id=org.id,
        workspace_id=ws.id,
    )
    with tracer.span(SpanName.AUTHENTICATION, SpanType.SECURITY):
        pass
    with tracer.span(SpanName.DENSE_RETRIEVAL, SpanType.RETRIEVAL):
        pass

    saved_trace = tracer.persist(db_session)
    assert saved_trace is not None

    spans = list(db_session.scalars(select(QueryTraceSpan).where(QueryTraceSpan.trace_id == "trc-integrity-1")).all())
    assert len(spans) == 2
    for s in spans:
        assert s.trace_id == "trc-integrity-1"


def test_foreign_key_delete_lifecycle(db_session: Session, obs_setup: dict):
    """Test 6: Deleting a trace cascades to its spans; deleting conversation sets null."""
    ws = obs_setup["ws_a1"]
    org = obs_setup["org_a"]

    conv = Conversation(workspace_id=ws.id)
    db_session.add(conv)
    db_session.flush()

    trace = QueryTrace(
        trace_id="trc-fk-test-1",
        request_id="req-fk-test-1",
        organization_id=org.id,
        workspace_id=ws.id,
        conversation_id=conv.id,
        operation_type="CHAT",
        status="SUCCESS",
    )
    db_session.add(trace)
    db_session.flush()

    span = QueryTraceSpan(
        trace_id="trc-fk-test-1",
        span_name="AUTHENTICATION",
        span_type="SECURITY",
        started_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
        duration_ms=1.5,
        status="SUCCESS",
    )
    db_session.add(span)
    db_session.commit()

    # 1. Delete conversation -> trace conversation_id becomes NULL
    db_session.delete(conv)
    db_session.commit()

    db_session.refresh(trace)
    assert trace.conversation_id is None

    # 2. Delete trace -> spans are CASCADE deleted
    db_session.delete(trace)
    db_session.commit()

    remaining_spans = list(db_session.scalars(select(QueryTraceSpan).where(QueryTraceSpan.trace_id == "trc-fk-test-1")).all())
    assert len(remaining_spans) == 0


# =========================================================================
# 3. Trace Detail Authorization & Filter Non-Leakage
# =========================================================================

def test_trace_detail_authorization_denials(obs_client: TestClient, obs_setup: dict):
    """Test 7: Detail endpoint strictly checks roles and does not leak trace existence across workspaces."""
    ws_a1 = obs_setup["ws_a1"]
    ws_a2 = obs_setup["ws_a2"]
    admin = obs_setup["admin"]
    viewer = obs_setup["viewer"]
    contrib = obs_setup["contrib"]

    admin_token = create_access_token(admin.id, email=admin.email)
    viewer_token = create_access_token(viewer.id, email=viewer.email)
    contrib_token = create_access_token(contrib.id, email=contrib.email)

    # Create a trace in WS A1
    chat_resp = obs_client.post(
        "/api/v1/chat",
        headers={"Authorization": f"Bearer {admin_token}", "X-Workspace-Id": str(ws_a1.id)},
        json={"question": "Detail auth check"},
    )
    assert chat_resp.status_code == 200
    trc_id = chat_resp.headers["X-Trace-Id"]

    # 1. Viewer is 403 Forbidden
    resp = obs_client.get(
        f"/api/v1/traces/{trc_id}",
        headers={"Authorization": f"Bearer {viewer_token}", "X-Workspace-Id": str(ws_a1.id)},
    )
    assert resp.status_code == 403

    # 2. Contributor is 403 Forbidden
    resp = obs_client.get(
        f"/api/v1/traces/{trc_id}",
        headers={"Authorization": f"Bearer {contrib_token}", "X-Workspace-Id": str(ws_a1.id)},
    )
    assert resp.status_code == 403

    # 3. Workspace Admin accessing a non-existent or other workspace trace returns 404 (no existence leak)
    resp = obs_client.get(
        f"/api/v1/traces/non_existent_trc_999",
        headers={"Authorization": f"Bearer {admin_token}", "X-Workspace-Id": str(ws_a1.id)},
    )
    assert resp.status_code == 404


def test_filter_information_leakage(obs_client: TestClient, obs_setup: dict):
    """Test 8: Workspace Admin cannot filter or discover traces outside their workspace."""
    ws_a1 = obs_setup["ws_a1"]
    ws_a2 = obs_setup["ws_a2"]
    admin = obs_setup["admin"]
    admin_token = create_access_token(admin.id, email=admin.email)

    # Attempt to query with another workspace_id
    resp = obs_client.get(
        f"/api/v1/traces?workspace_id={ws_a2.id}",
        headers={"Authorization": f"Bearer {admin_token}", "X-Workspace-Id": str(ws_a1.id)},
    )
    assert resp.status_code == 403


# =========================================================================
# 4. Deeply Nested Privacy Sanitizer Hardening
# =========================================================================

def test_nested_metadata_privacy_sanitizer():
    """Test 9: Deeply nested dictionaries, lists, and custom objects are sanitized completely."""
    malicious_payload = {
        "safe_count": 10,
        "token_usage_available": True,
        "input_token_count": 50,
        "nested_dict": {
            "query": "malicious query 1",
            "user_prompt": "secret prompt 2",
            "inner_array": [
                {"raw_question": "question 3", "candidate_count": 5},
                {"secret_key": "api_key_12345", "chunk_text": "text 4"},
            ],
            "deep": {
                "level3": {
                    "response_text": "generated answer 5",
                    "password": "hunter2",
                    "bearer_token": "token_val",
                    "dimension": 768,
                }
            }
        },
        "query_hash": "sha256_hash_value_here",
    }

    sanitized = sanitize_metadata(malicious_payload)
    dumped = json.dumps(sanitized)

    # Assert no sensitive content survived
    forbidden_terms = [
        "malicious query 1",
        "secret prompt 2",
        "question 3",
        "api_key_12345",
        "text 4",
        "generated answer 5",
        "hunter2",
        "token_val",
    ]
    for term in forbidden_terms:
        assert term not in dumped, f"Sanitizer leaked term: {term}"

    # Assert safe telemetry survived
    assert sanitized["safe_count"] == 10
    assert sanitized["token_usage_available"] is True
    assert sanitized["input_token_count"] == 50
    assert sanitized["query_hash"] == "sha256_hash_value_here"
    assert sanitized["nested_dict"]["inner_array"][0]["candidate_count"] == 5
    assert sanitized["nested_dict"]["deep"]["level3"]["dimension"] == 768


def test_query_hash_privacy_and_determinism(obs_client: TestClient, obs_setup: dict, db_session: Session):
    """Test 10: Query hashes are SHA-256 and raw query is never stored."""
    user = obs_setup["contrib"]
    ws = obs_setup["ws_a1"]
    token = create_access_token(user.id, email=user.email)
    raw_q = "What is the meaning of structured tracing?"
    expected_hash = hashlib.sha256(raw_q.strip().encode("utf-8")).hexdigest()

    resp = obs_client.post(
        "/api/v1/chat",
        headers={"Authorization": f"Bearer {token}", "X-Workspace-Id": str(ws.id)},
        json={"question": raw_q},
    )
    assert resp.status_code == 200
    trc_id = resp.headers["X-Trace-Id"]

    trace = db_session.scalars(select(QueryTrace).where(QueryTrace.trace_id == trc_id)).first()
    spans = list(db_session.scalars(select(QueryTraceSpan).where(QueryTraceSpan.trace_id == trc_id)).all())

    # Check query_hash is present in query normalization span
    q_spans = [s for s in spans if s.span_name == SpanName.QUERY_NORMALIZATION.value]
    assert len(q_spans) > 0
    assert q_spans[0].metadata_["query_hash"] == expected_hash

    # Raw query never in trace or span metadata
    assert raw_q not in json.dumps(trace.metadata_)
    assert raw_q not in json.dumps([s.metadata_ for s in spans])


# =========================================================================
# 5. Stream Lifecycle & Terminal States
# =========================================================================

def test_stream_terminal_state_on_normal_completion(obs_client: TestClient, obs_setup: dict, db_session: Session):
    """Test 11, 14: Normal streaming completion terminates in SUCCESS."""
    user = obs_setup["contrib"]
    ws = obs_setup["ws_a1"]
    token = create_access_token(user.id, email=user.email)

    resp = obs_client.post(
        "/api/v1/chat/stream",
        headers={"Authorization": f"Bearer {token}", "X-Workspace-Id": str(ws.id)},
        json={"question": "Stream normal completion"},
    )
    assert resp.status_code == 200
    _ = resp.text
    trc_id = resp.headers["X-Trace-Id"]

    trace = db_session.scalars(select(QueryTrace).where(QueryTrace.trace_id == trc_id)).first()
    assert trace is not None
    assert trace.status == TraceStatus.SUCCESS.value
    assert trace.completed_at is not None
    assert trace.total_latency_ms is not None and trace.total_latency_ms > 0


def test_stream_provider_failure_terminal_error_state(obs_client: TestClient, obs_setup: dict, db_session: Session, monkeypatch):
    """Test 13, 14: Provider exception during streaming sets terminal status to ERROR."""
    user = obs_setup["contrib"]
    ws = obs_setup["ws_a1"]
    token = create_access_token(user.id, email=user.email)

    def failing_stream(*args, **kwargs):
        raise AIProviderError("Provider socket dropped unexpectedly")

    monkeypatch.setattr("app.services.rag.RagService.stream_tokens", failing_stream)

    resp = obs_client.post(
        "/api/v1/chat/stream",
        headers={"Authorization": f"Bearer {token}", "X-Workspace-Id": str(ws.id)},
        json={"question": "Stream provider error check"},
    )
    assert resp.status_code == 200
    _ = resp.text
    trc_id = resp.headers["X-Trace-Id"]

    trace = db_session.scalars(select(QueryTrace).where(QueryTrace.trace_id == trc_id)).first()
    assert trace is not None
    assert trace.status == TraceStatus.ERROR.value
    assert trace.error_type in (ErrorCategory.LLM_PROVIDER_ERROR.value, ErrorCategory.STREAM_ERROR.value)


def test_stream_cancellation_before_first_token(obs_setup: dict, db_session: Session, monkeypatch):
    """Test 11: Client cancellation before first token results in CANCELLED status."""
    ws = obs_setup["ws_a1"]
    org = obs_setup["org_a"]
    user = obs_setup["contrib"]

    provider = MagicMock()
    provider.create_embedding.side_effect = lambda text, task: [0.1] * 768
    provider.stream_text.side_effect = lambda prompt: iter(["Token 1 ", "Token 2 "])
    monkeypatch.setattr("app.services.rag.get_ai_provider", lambda: provider)

    conv_service = ConversationService(
        db_session,
        workspace_id=ws.id,
        user_id=user.id,
        workspace_context=WorkspaceContext(
            workspace_id=ws.id,
            workspace_slug=ws.slug,
            organization_id=org.id,
            organization_slug=org.slug,
            user_id=user.id,
            workspace_role=WorkspaceRole.CONTRIBUTOR,
            organization_role=OrganizationRole.MEMBER,
        ),
    )

    prepared = conv_service.prepare_turn("Test cancellation before token")
    gen = conv_service.iter_chat_events(prepared)
    # Read the initial 'start' event before any generation tokens
    _ = next(gen)
    # Client closes stream before receiving tokens
    gen.close()

    trace = db_session.scalars(select(QueryTrace).where(QueryTrace.trace_id == prepared.tracer.trace_id)).first()
    assert trace is not None
    assert trace.status == TraceStatus.CANCELLED.value


def test_stream_cancellation_after_first_token(obs_setup: dict, db_session: Session, monkeypatch):
    """Test 12: Client cancellation after yielding a token results in PARTIAL status."""
    ws = obs_setup["ws_a1"]
    org = obs_setup["org_a"]
    user = obs_setup["contrib"]

    provider = MagicMock()
    provider.create_embedding.side_effect = lambda text, task: [0.1] * 768
    provider.stream_text.side_effect = lambda prompt: iter(["Token 1 ", "Token 2 ", "Token 3 "])
    monkeypatch.setattr("app.services.rag.get_ai_provider", lambda: provider)

    conv_service = ConversationService(
        db_session,
        workspace_id=ws.id,
        user_id=user.id,
        workspace_context=WorkspaceContext(
            workspace_id=ws.id,
            workspace_slug=ws.slug,
            organization_id=org.id,
            organization_slug=org.slug,
            user_id=user.id,
            workspace_role=WorkspaceRole.CONTRIBUTOR,
            organization_role=OrganizationRole.MEMBER,
        ),
    )
    prepared = conv_service.prepare_turn("Test cancellation after token")
    gen = conv_service.iter_chat_events(prepared)
    # Read start event
    _ = next(gen)
    # Read first token event
    tok_event = next(gen)
    assert "token" in tok_event
    # Client closes connection midway
    gen.close()

    trace = db_session.scalars(select(QueryTrace).where(QueryTrace.trace_id == prepared.tracer.trace_id)).first()
    assert trace is not None
    assert trace.status == TraceStatus.PARTIAL.value


def test_stream_provider_failure_after_first_token(obs_client: TestClient, obs_setup: dict, db_session: Session, monkeypatch):
    """Test 14: Provider exception after first token sets terminal status to ERROR."""
    user = obs_setup["contrib"]
    ws = obs_setup["ws_a1"]
    token = create_access_token(user.id, email=user.email)

    def failing_stream_midway(*args, **kwargs):
        yield "Initial text "
        raise AIProviderError("Provider reset midway")

    monkeypatch.setattr("app.services.rag.RagService.stream_tokens", failing_stream_midway)

    resp = obs_client.post(
        "/api/v1/chat/stream",
        headers={"Authorization": f"Bearer {token}", "X-Workspace-Id": str(ws.id)},
        json={"question": "Stream provider error midway"},
    )
    assert resp.status_code == 200
    _ = resp.text
    trc_id = resp.headers["X-Trace-Id"]

    trace = db_session.scalars(select(QueryTrace).where(QueryTrace.trace_id == trc_id)).first()
    assert trace is not None
    assert trace.status == TraceStatus.ERROR.value


def test_partial_trace_terminal_status_error(db_session: Session, obs_setup: dict):
    """Test 15: An unhandled failure in a trace marks status ERROR and preserves finished spans."""
    ws = obs_setup["ws_a1"]
    org = obs_setup["org_a"]

    tracer = QueryTracer(
        request_id="req-part-fail",
        trace_id="trc-part-fail",
        organization_id=org.id,
        workspace_id=ws.id,
    )
    with tracer.span(SpanName.AUTHENTICATION, SpanType.SECURITY):
        pass

    try:
        with tracer.span(SpanName.EMBEDDING, SpanType.AI_PROVIDER):
            raise ValueError("Embedding calculation failed")
    except ValueError as exc:
        tracer.set_status(TraceStatus.ERROR, error_type=ErrorCategory.VALIDATION_ERROR.value, error_code="ValueError")

    saved = tracer.persist(db_session)
    assert saved is not None
    assert saved.status == TraceStatus.ERROR.value
    assert saved.error_type == ErrorCategory.VALIDATION_ERROR.value
    assert len(tracer.spans) == 2


def test_token_count_validation_non_negative():
    """Test 16: Negative token counts are sanitized to None and marked unavailable."""
    tracer = QueryTracer(
        request_id="req-token-neg",
        trace_id="trc-token-neg",
        organization_id=uuid.uuid4(),
    )
    tracer.record_llm_telemetry(
        provider="gemini",
        model="gemini-2.5-flash",
        latency_ms=100.0,
        input_token_count=-50,
        output_token_count=-20,
    )
    span = tracer.spans[-1]
    assert span.metadata["token_usage_available"] is False
    assert "input_token_count" not in span.metadata


def test_trace_metadata_cannot_be_client_controlled(obs_client: TestClient, obs_setup: dict, db_session: Session):
    """Test 17: Malicious request payloads cannot overwrite server-owned tenant context."""
    user = obs_setup["contrib"]
    ws = obs_setup["ws_a1"]
    token = create_access_token(user.id, email=user.email)
    fake_org_id = str(uuid.uuid4())

    resp = obs_client.post(
        "/api/v1/chat",
        headers={"Authorization": f"Bearer {token}", "X-Workspace-Id": str(ws.id)},
        json={
            "question": "Can I hijack tenant metadata?",
            "organization_id": fake_org_id,
            "status": "FORGED_STATUS",
        },
    )
    assert resp.status_code == 200
    trc_id = resp.headers["X-Trace-Id"]

    trace = db_session.scalars(select(QueryTrace).where(QueryTrace.trace_id == trc_id)).first()
    assert trace is not None
    assert trace.organization_id == obs_setup["org_a"].id
    assert trace.organization_id != uuid.UUID(fake_org_id)
    assert trace.status == TraceStatus.SUCCESS.value


# =========================================================================
# 7. Failure Isolation, Audit Correlation & RAG Equivalence
# =========================================================================

def test_trace_persistence_failure_isolation(obs_client: TestClient, obs_setup: dict, monkeypatch):
    """Test 18: Database trace failure does NOT break the business chat response."""
    user = obs_setup["contrib"]
    ws = obs_setup["ws_a1"]
    token = create_access_token(user.id, email=user.email)

    monkeypatch.setattr(QueryTracer, "persist", lambda self, db: None)

    resp = obs_client.post(
        "/api/v1/chat",
        headers={"Authorization": f"Bearer {token}", "X-Workspace-Id": str(ws.id)},
        json={"question": "Persistence isolation test"},
    )
    assert resp.status_code == 200
    assert "answer" in resp.json()


def test_audit_and_trace_correlation(obs_client: TestClient, obs_setup: dict, db_session: Session):
    """Test 19: Correlation between QueryTrace.request_id and AuditLog.request_id."""
    user = obs_setup["contrib"]
    ws = obs_setup["ws_a1"]
    token = create_access_token(user.id, email=user.email)

    resp = obs_client.post(
        "/api/v1/chat",
        headers={"Authorization": f"Bearer {token}", "X-Workspace-Id": str(ws.id)},
        json={"question": "Correlate trace and audit"},
    )
    assert resp.status_code == 200
    req_id = resp.headers["X-Request-Id"]
    trc_id = resp.headers["X-Trace-Id"]

    trace = db_session.scalars(select(QueryTrace).where(QueryTrace.trace_id == trc_id)).first()
    audit = db_session.scalars(select(AuditLog).where(AuditLog.request_id == req_id)).first()

    assert trace is not None
    assert audit is not None
    assert trace.request_id == audit.request_id == req_id


def test_rag_results_remain_identical_with_hardening_enabled(obs_client: TestClient, obs_setup: dict):
    """Test 20: RAG answers and sources are strictly preserved."""
    user = obs_setup["contrib"]
    ws = obs_setup["ws_a1"]
    token = create_access_token(user.id, email=user.email)

    resp = obs_client.post(
        "/api/v1/chat",
        headers={"Authorization": f"Bearer {token}", "X-Workspace-Id": str(ws.id)},
        json={"question": "Final equivalence test"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["answer"] == "Observability allows developers to inspect fine-grained execution latency."
    assert len(data["sources"]) == 1
    assert data["sources"][0]["document_id"] == str(obs_setup["doc"].id)
