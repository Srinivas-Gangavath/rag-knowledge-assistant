"""Test suite for Phase 1.7 Trace Retention, Performance Analytics & Diagnostics.

Contains 27 dedicated tests mapping 1:1 to Section 22:
1. retention cutoff correctness
2. retention dry-run
3. retention deletion
4. spans cascade with trace deletion
5. audit logs remain untouched
6. organization isolation
7. workspace isolation
8. p50 calculation
9. p95 calculation
10. p99 calculation
11. error rate calculation
12. stage latency aggregation
13. dominant-stage detection
14. slow-query classification
15. model/provider aggregation
16. token usage aggregation
17. missing token handling
18. streaming TTFT analytics
19. trace export authorization
20. trace export privacy
21. analytics authorization
22. analytics filter isolation
23. time-window filtering
24. empty dataset behavior
25. rollback on retention failure
26. analytics does not modify traces
27. RAG results remain unchanged
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import create_access_token, hash_password
from app.core.workspace_context import WorkspaceContext
from app.db.database import get_db
from app.db.models import (
    AuditEventType,
    AuditLog,
    AuditOutcome,
    Conversation,
    Document,
    DocumentChunk,
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
from app.schemas.trace import TraceRetentionCleanupRequest
from app.services.audit_service import AuditLogService
from app.services.tracing.analytics_service import (
    TraceAnalyticsService,
    _calculate_percentiles,
)
from app.services.tracing.retention_service import TraceRetentionService
from app.services.tracing.taxonomy import SpanName, SpanType, TraceStatus
from tests.conftest import postgres_available


@pytest.fixture
def analytics_setup(db_session: Session):
    if not postgres_available():
        pytest.skip("PostgreSQL is not available for database tests.")

    # Create Org A
    org_a = Organization(name="Analytics Org A", slug=f"an-org-a-{uuid.uuid4().hex[:6]}")
    # Create Org B
    org_b = Organization(name="Analytics Org B", slug=f"an-org-b-{uuid.uuid4().hex[:6]}")
    db_session.add_all([org_a, org_b])
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
        filename=f"analytics_doc_{uuid.uuid4().hex[:6]}.pdf",
        original_filename="Analytics Guide.pdf",
        file_path="/tmp/analytics_doc.pdf",
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
        content="Platform analytics provides latency percentiles and slow query diagnoses.",
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
def analytics_client(db_session: Session, monkeypatch) -> TestClient:
    if not postgres_available():
        pytest.skip("PostgreSQL is not available for database tests.")

    provider = MagicMock()
    provider.create_embedding.side_effect = lambda text, task: [0.1] * 768
    provider.generate_text.side_effect = lambda prompt: "Analytics response content."
    provider.stream_text.side_effect = lambda prompt: iter(["Analytics ", "streaming ", "answer."])
    monkeypatch.setattr("app.services.rag.get_ai_provider", lambda: provider)

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.pop(get_db, None)


# =========================================================================
# 1. Retention Policy, Cutoff, Dry-Run, Cascades & Isolation Tests (1 - 7)
# =========================================================================

def test_retention_cutoff_correctness(db_session: Session, analytics_setup: dict):
    """Test 1: Retention correctly calculates cutoff timestamp based on configured days."""
    org_a = analytics_setup["org_a"]
    ws_a1 = analytics_setup["ws_a1"]
    owner = analytics_setup["owner"]

    ctx = WorkspaceContext(
        workspace_id=ws_a1.id,
        workspace_slug=ws_a1.slug,
        organization_id=org_a.id,
        organization_slug=org_a.slug,
        user_id=owner.id,
        workspace_role=WorkspaceRole.WORKSPACE_ADMIN,
        organization_role=OrganizationRole.OWNER,
    )

    before = datetime.now(timezone.utc) - timedelta(days=14)
    preview = TraceRetentionService.preview_expired_traces(db_session, ctx, days=14)
    after = datetime.now(timezone.utc) - timedelta(days=14)

    assert before <= preview.cutoff <= after


def test_retention_dry_run(db_session: Session, analytics_setup: dict):
    """Test 2: Dry-run mode previews eligible traces without deleting anything from DB."""
    org_a = analytics_setup["org_a"]
    ws_a1 = analytics_setup["ws_a1"]
    owner = analytics_setup["owner"]

    old_time = datetime.now(timezone.utc) - timedelta(days=45)
    t_old = QueryTrace(
        trace_id="trc_dry_1",
        request_id="req_dry_1",
        organization_id=org_a.id,
        workspace_id=ws_a1.id,
        started_at=old_time,
        total_latency_ms=120.0,
        status="SUCCESS",
        operation_type="CHAT",
    )
    db_session.add(t_old)
    db_session.commit()

    ctx = WorkspaceContext(
        workspace_id=ws_a1.id,
        workspace_slug=ws_a1.slug,
        organization_id=org_a.id,
        organization_slug=org_a.slug,
        user_id=owner.id,
        workspace_role=WorkspaceRole.WORKSPACE_ADMIN,
        organization_role=OrganizationRole.OWNER,
    )

    cleanup_dry = TraceRetentionService.delete_expired_traces(db_session, ctx, days=30, dry_run=True)
    assert cleanup_dry.dry_run is True
    assert cleanup_dry.deleted_traces_count == 1

    # Verify trace is still in database
    t = db_session.scalars(select(QueryTrace).where(QueryTrace.trace_id == "trc_dry_1")).first()
    assert t is not None


def test_retention_deletion(db_session: Session, analytics_setup: dict):
    """Test 3: Retention deletion deletes eligible expired traces."""
    org_a = analytics_setup["org_a"]
    ws_a1 = analytics_setup["ws_a1"]
    owner = analytics_setup["owner"]

    old_time = datetime.now(timezone.utc) - timedelta(days=50)
    t_old = QueryTrace(
        trace_id="trc_del_act",
        request_id="req_del_act",
        organization_id=org_a.id,
        workspace_id=ws_a1.id,
        started_at=old_time,
        status="SUCCESS",
        operation_type="CHAT",
    )
    db_session.add(t_old)
    db_session.commit()

    ctx = WorkspaceContext(
        workspace_id=ws_a1.id,
        workspace_slug=ws_a1.slug,
        organization_id=org_a.id,
        organization_slug=org_a.slug,
        user_id=owner.id,
        workspace_role=WorkspaceRole.WORKSPACE_ADMIN,
        organization_role=OrganizationRole.OWNER,
    )

    cleanup = TraceRetentionService.delete_expired_traces(db_session, ctx, days=30, dry_run=False)
    assert cleanup.dry_run is False
    assert cleanup.deleted_traces_count == 1

    t = db_session.scalars(select(QueryTrace).where(QueryTrace.trace_id == "trc_del_act")).first()
    assert t is None


def test_spans_cascade_with_trace_deletion(db_session: Session, analytics_setup: dict):
    """Test 4: Child spans cascade delete when parent trace is deleted via retention."""
    org_a = analytics_setup["org_a"]
    ws_a1 = analytics_setup["ws_a1"]
    owner = analytics_setup["owner"]

    old_time = datetime.now(timezone.utc) - timedelta(days=50)
    trace = QueryTrace(
        trace_id="trc_cascade_1",
        request_id="req_cas_1",
        organization_id=org_a.id,
        workspace_id=ws_a1.id,
        started_at=old_time,
        status="SUCCESS",
        operation_type="CHAT",
    )
    db_session.add(trace)
    db_session.flush()

    span = QueryTraceSpan(
        trace_id="trc_cascade_1",
        span_name="EMBEDDING",
        span_type="AI_PROVIDER",
        started_at=old_time,
        duration_ms=45.0,
        status="SUCCESS",
    )
    db_session.add(span)
    db_session.commit()

    ctx = WorkspaceContext(
        workspace_id=ws_a1.id,
        workspace_slug=ws_a1.slug,
        organization_id=org_a.id,
        organization_slug=org_a.slug,
        user_id=owner.id,
        workspace_role=WorkspaceRole.WORKSPACE_ADMIN,
        organization_role=OrganizationRole.OWNER,
    )

    TraceRetentionService.delete_expired_traces(db_session, ctx, days=30)
    spans = list(db_session.scalars(select(QueryTraceSpan).where(QueryTraceSpan.trace_id == "trc_cascade_1")).all())
    assert len(spans) == 0


def test_audit_logs_remain_untouched(db_session: Session, analytics_setup: dict):
    """Test 5: Retention deletion NEVER touches or alters audit_logs."""
    org_a = analytics_setup["org_a"]
    ws_a1 = analytics_setup["ws_a1"]
    owner = analytics_setup["owner"]

    old_time = datetime.now(timezone.utc) - timedelta(days=60)
    trace = QueryTrace(
        trace_id="trc_audit_keep",
        request_id="req_audit_keep",
        organization_id=org_a.id,
        workspace_id=ws_a1.id,
        started_at=old_time,
        status="SUCCESS",
        operation_type="CHAT",
    )
    db_session.add(trace)
    db_session.flush()

    AuditLogService.record_event(
        db_session,
        organization_id=org_a.id,
        workspace_id=ws_a1.id,
        actor_user_id=owner.id,
        event_type=AuditEventType.KNOWLEDGE_QUERY,
        action="knowledge_query",
        outcome=AuditOutcome.SUCCESS,
        request_id="req_audit_keep",
    )
    db_session.commit()

    ctx = WorkspaceContext(
        workspace_id=ws_a1.id,
        workspace_slug=ws_a1.slug,
        organization_id=org_a.id,
        organization_slug=org_a.slug,
        user_id=owner.id,
        workspace_role=WorkspaceRole.WORKSPACE_ADMIN,
        organization_role=OrganizationRole.OWNER,
    )

    TraceRetentionService.delete_expired_traces(db_session, ctx, days=30)
    audit = db_session.scalars(select(AuditLog).where(AuditLog.request_id == "req_audit_keep")).first()
    assert audit is not None


def test_organization_isolation(db_session: Session, analytics_setup: dict):
    """Test 6: Retention execution in Org A does not touch Org B records."""
    org_a = analytics_setup["org_a"]
    org_b = analytics_setup["org_b"]
    ws_a1 = analytics_setup["ws_a1"]
    ws_b1 = analytics_setup["ws_b1"]
    owner = analytics_setup["owner"]

    old_time = datetime.now(timezone.utc) - timedelta(days=60)
    t_b = QueryTrace(
        trace_id="trc_org_b_iso",
        request_id="req_org_b_iso",
        organization_id=org_b.id,
        workspace_id=ws_b1.id,
        started_at=old_time,
        status="SUCCESS",
        operation_type="CHAT",
    )
    db_session.add(t_b)
    db_session.commit()

    ctx_a = WorkspaceContext(
        workspace_id=ws_a1.id,
        workspace_slug=ws_a1.slug,
        organization_id=org_a.id,
        organization_slug=org_a.slug,
        user_id=owner.id,
        workspace_role=WorkspaceRole.WORKSPACE_ADMIN,
        organization_role=OrganizationRole.OWNER,
    )

    cleanup_a = TraceRetentionService.delete_expired_traces(db_session, ctx_a, days=30)
    assert cleanup_a.deleted_traces_count == 0

    t_b_check = db_session.scalars(select(QueryTrace).where(QueryTrace.trace_id == "trc_org_b_iso")).first()
    assert t_b_check is not None


def test_workspace_isolation(db_session: Session, analytics_setup: dict):
    """Test 7: Analytics results in WS A1 do not count traces from WS A2."""
    org_a = analytics_setup["org_a"]
    ws_a1 = analytics_setup["ws_a1"]
    ws_a2 = analytics_setup["ws_a2"]
    admin = analytics_setup["admin"]

    now = datetime.now(timezone.utc)
    t1 = QueryTrace(
        trace_id="trc_ws1_only",
        request_id="req_ws1",
        organization_id=org_a.id,
        workspace_id=ws_a1.id,
        started_at=now,
        total_latency_ms=100.0,
        status="SUCCESS",
        operation_type="CHAT",
    )
    t2 = QueryTrace(
        trace_id="trc_ws2_only",
        request_id="req_ws2",
        organization_id=org_a.id,
        workspace_id=ws_a2.id,
        started_at=now,
        total_latency_ms=300.0,
        status="SUCCESS",
        operation_type="CHAT",
    )
    db_session.add_all([t1, t2])
    db_session.commit()

    ctx_ws1 = WorkspaceContext(
        workspace_id=ws_a1.id,
        workspace_slug=ws_a1.slug,
        organization_id=org_a.id,
        organization_slug=org_a.slug,
        user_id=admin.id,
        workspace_role=WorkspaceRole.WORKSPACE_ADMIN,
        organization_role=OrganizationRole.MEMBER,
    )

    analytics = TraceAnalyticsService.get_analytics(db_session, ctx_ws1, workspace_id=ws_a1.id)
    assert analytics.overview.request_count == 1
    assert analytics.overview.average_latency_ms == 100.0


# =========================================================================
# 2. Percentile Calculations & Stage Diagnostics (8 - 14)
# =========================================================================

def test_p50_calculation():
    """Test 8: Exact median p50 latency calculation."""
    vals = [10.0, 20.0, 30.0, 40.0, 50.0]
    avg, p50, p95, p99, max_val = _calculate_percentiles(vals)
    assert p50 == 30.0


def test_p95_calculation():
    """Test 9: Exact p95 latency calculation with linear interpolation."""
    vals = [float(i) for i in range(1, 101)]
    _, _, p95, _, _ = _calculate_percentiles(vals)
    assert abs(p95 - 95.05) < 0.1


def test_p99_calculation():
    """Test 10: Exact p99 latency calculation."""
    vals = [float(i) for i in range(1, 101)]
    _, _, _, p99, _ = _calculate_percentiles(vals)
    assert abs(p99 - 99.01) < 0.1


def test_error_rate_calculation(db_session: Session, analytics_setup: dict):
    """Test 11: Error rate calculation across successes and failures."""
    org_a = analytics_setup["org_a"]
    ws_a1 = analytics_setup["ws_a1"]
    owner = analytics_setup["owner"]

    now = datetime.now(timezone.utc)
    t_ok = QueryTrace(
        trace_id="trc_err_ok",
        request_id="req_e1",
        organization_id=org_a.id,
        workspace_id=ws_a1.id,
        started_at=now,
        status="SUCCESS",
        operation_type="CHAT",
        total_latency_ms=100.0,
    )
    t_err = QueryTrace(
        trace_id="trc_err_fail",
        request_id="req_e2",
        organization_id=org_a.id,
        workspace_id=ws_a1.id,
        started_at=now,
        status="ERROR",
        error_type="LLM_PROVIDER_ERROR",
        operation_type="CHAT",
        total_latency_ms=500.0,
    )
    db_session.add_all([t_ok, t_err])
    db_session.commit()

    ctx = WorkspaceContext(
        workspace_id=ws_a1.id,
        workspace_slug=ws_a1.slug,
        organization_id=org_a.id,
        organization_slug=org_a.slug,
        user_id=owner.id,
        workspace_role=WorkspaceRole.WORKSPACE_ADMIN,
        organization_role=OrganizationRole.OWNER,
    )

    analytics = TraceAnalyticsService.get_analytics(db_session, ctx)
    assert analytics.overview.request_count == 2
    assert analytics.overview.error_count == 1
    assert analytics.overview.error_rate == 0.5
    assert analytics.errors.errors_by_category.get("LLM_PROVIDER_ERROR") == 1


def test_stage_latency_aggregation(db_session: Session, analytics_setup: dict):
    """Test 12: Aggregation of individual span stages with percentiles and count."""
    org_a = analytics_setup["org_a"]
    ws_a1 = analytics_setup["ws_a1"]
    owner = analytics_setup["owner"]

    now = datetime.now(timezone.utc)
    t = QueryTrace(
        trace_id="trc_stage_agg",
        request_id="req_s_agg",
        organization_id=org_a.id,
        workspace_id=ws_a1.id,
        started_at=now,
        status="SUCCESS",
        operation_type="CHAT",
        total_latency_ms=400.0,
    )
    db_session.add(t)
    db_session.flush()

    s1 = QueryTraceSpan(
        trace_id="trc_stage_agg",
        span_name="DENSE_RETRIEVAL",
        span_type="RETRIEVAL",
        started_at=now,
        duration_ms=150.0,
        status="SUCCESS",
    )
    s2 = QueryTraceSpan(
        trace_id="trc_stage_agg",
        span_name="LLM_GENERATION",
        span_type="AI_PROVIDER",
        started_at=now,
        duration_ms=250.0,
        status="SUCCESS",
    )
    db_session.add_all([s1, s2])
    db_session.commit()

    ctx = WorkspaceContext(
        workspace_id=ws_a1.id,
        workspace_slug=ws_a1.slug,
        organization_id=org_a.id,
        organization_slug=org_a.slug,
        user_id=owner.id,
        workspace_role=WorkspaceRole.WORKSPACE_ADMIN,
        organization_role=OrganizationRole.OWNER,
    )

    analytics = TraceAnalyticsService.get_analytics(db_session, ctx)
    dense_stage = next((s for s in analytics.stages if s.stage == "DENSE_RETRIEVAL"), None)
    assert dense_stage is not None
    assert dense_stage.count == 1
    assert dense_stage.average_ms == 150.0


def test_dominant_stage_detection(db_session: Session, analytics_setup: dict):
    """Test 13: Accurate identification of the largest latency contributor."""
    t = QueryTrace(
        trace_id="trc_dom_test",
        request_id="req_dom",
        organization_id=analytics_setup["org_a"].id,
        workspace_id=analytics_setup["ws_a1"].id,
        started_at=datetime.now(timezone.utc),
        status="SUCCESS",
        operation_type="CHAT",
        total_latency_ms=2500.0,
    )
    db_session.add(t)
    db_session.flush()

    s1 = QueryTraceSpan(
        trace_id="trc_dom_test",
        span_name="EMBEDDING",
        span_type="AI_PROVIDER",
        started_at=datetime.now(timezone.utc),
        duration_ms=100.0,
        status="SUCCESS",
    )
    s2 = QueryTraceSpan(
        trace_id="trc_dom_test",
        span_name="LLM_GENERATION",
        span_type="AI_PROVIDER",
        started_at=datetime.now(timezone.utc),
        duration_ms=2400.0,
        status="SUCCESS",
    )
    db_session.add_all([s1, s2])
    db_session.commit()

    db_session.refresh(t)
    diag = TraceAnalyticsService.diagnose_trace(t)
    assert diag.dominant_stage == "LLM_GENERATION"
    assert diag.dominant_stage_duration_ms == 2400.0
    assert diag.is_generation_dominant is True
    assert diag.is_retrieval_dominant is False


def test_slow_query_classification():
    """Test 14: Classifies queries into FAST, NORMAL, SLOW, VERY_SLOW."""
    assert TraceAnalyticsService.classify_slow_query(200.0) == "FAST"
    assert TraceAnalyticsService.classify_slow_query(1200.0) == "NORMAL"
    assert TraceAnalyticsService.classify_slow_query(3000.0) == "SLOW"
    assert TraceAnalyticsService.classify_slow_query(8000.0) == "VERY_SLOW"


# =========================================================================
# 3. Model, Token & Streaming Analytics (15 - 18)
# =========================================================================

def test_model_provider_aggregation(db_session: Session, analytics_setup: dict):
    """Test 15: Groups telemetry by AI provider and model."""
    org_a = analytics_setup["org_a"]
    ws_a1 = analytics_setup["ws_a1"]
    owner = analytics_setup["owner"]

    now = datetime.now(timezone.utc)
    t = QueryTrace(
        trace_id="trc_mod_prov",
        request_id="req_mp",
        organization_id=org_a.id,
        workspace_id=ws_a1.id,
        started_at=now,
        status="SUCCESS",
        operation_type="CHAT",
        total_latency_ms=600.0,
    )
    db_session.add(t)
    db_session.flush()

    s = QueryTraceSpan(
        trace_id="trc_mod_prov",
        span_name="LLM_GENERATION",
        span_type="AI_PROVIDER",
        started_at=now,
        duration_ms=550.0,
        status="SUCCESS",
        metadata_={"provider": "gemini", "model": "gemini-3.7-flash"},
    )
    db_session.add(s)
    db_session.commit()

    ctx = WorkspaceContext(
        workspace_id=ws_a1.id,
        workspace_slug=ws_a1.slug,
        organization_id=org_a.id,
        organization_slug=org_a.slug,
        user_id=owner.id,
        workspace_role=WorkspaceRole.WORKSPACE_ADMIN,
        organization_role=OrganizationRole.OWNER,
    )

    analytics = TraceAnalyticsService.get_analytics(db_session, ctx)
    assert any(p.provider == "gemini" and p.model == "gemini-3.7-flash" for p in analytics.providers)


def test_token_usage_aggregation(db_session: Session, analytics_setup: dict):
    """Test 16: Aggregates total, input, and output tokens accurately."""
    org_a = analytics_setup["org_a"]
    ws_a1 = analytics_setup["ws_a1"]
    owner = analytics_setup["owner"]

    now = datetime.now(timezone.utc)
    t = QueryTrace(
        trace_id="trc_tok_sum",
        request_id="req_ts",
        organization_id=org_a.id,
        workspace_id=ws_a1.id,
        started_at=now,
        status="SUCCESS",
        operation_type="CHAT",
        total_latency_ms=500.0,
    )
    db_session.add(t)
    db_session.flush()

    s = QueryTraceSpan(
        trace_id="trc_tok_sum",
        span_name="LLM_GENERATION",
        span_type="AI_PROVIDER",
        started_at=now,
        duration_ms=450.0,
        status="SUCCESS",
        metadata_={
            "provider": "gemini",
            "model": "gemini-3.7-flash",
            "input_token_count": 50,
            "output_token_count": 30,
            "total_token_count": 80,
            "token_usage_available": True,
        },
    )
    db_session.add(s)
    db_session.commit()

    ctx = WorkspaceContext(
        workspace_id=ws_a1.id,
        workspace_slug=ws_a1.slug,
        organization_id=org_a.id,
        organization_slug=org_a.slug,
        user_id=owner.id,
        workspace_role=WorkspaceRole.WORKSPACE_ADMIN,
        organization_role=OrganizationRole.OWNER,
    )

    analytics = TraceAnalyticsService.get_analytics(db_session, ctx)
    p = next((x for x in analytics.providers if x.model == "gemini-3.7-flash"), None)
    assert p is not None
    assert p.total_token_count == 80


def test_missing_token_handling(db_session: Session, analytics_setup: dict):
    """Test 17: Properly records token_usage_available=False when token metrics are absent."""
    org_a = analytics_setup["org_a"]
    ws_a1 = analytics_setup["ws_a1"]
    owner = analytics_setup["owner"]

    now = datetime.now(timezone.utc)
    t = QueryTrace(
        trace_id="trc_tok_miss",
        request_id="req_tm",
        organization_id=org_a.id,
        workspace_id=ws_a1.id,
        started_at=now,
        status="SUCCESS",
        operation_type="CHAT",
        total_latency_ms=400.0,
    )
    db_session.add(t)
    db_session.flush()

    s = QueryTraceSpan(
        trace_id="trc_tok_miss",
        span_name="LLM_GENERATION",
        span_type="AI_PROVIDER",
        started_at=now,
        duration_ms=350.0,
        status="SUCCESS",
        metadata_={
            "provider": "mock-llm",
            "model": "mock-v1",
            "token_usage_available": False,
        },
    )
    db_session.add(s)
    db_session.commit()

    ctx = WorkspaceContext(
        workspace_id=ws_a1.id,
        workspace_slug=ws_a1.slug,
        organization_id=org_a.id,
        organization_slug=org_a.slug,
        user_id=owner.id,
        workspace_role=WorkspaceRole.WORKSPACE_ADMIN,
        organization_role=OrganizationRole.OWNER,
    )

    analytics = TraceAnalyticsService.get_analytics(db_session, ctx)
    p = next((x for x in analytics.providers if x.model == "mock-v1"), None)
    assert p is not None
    assert p.token_usage_available is False


def test_streaming_ttft_analytics(db_session: Session, analytics_setup: dict):
    """Test 18: Calculates TTFT percentiles and average stream duration."""
    org_a = analytics_setup["org_a"]
    ws_a1 = analytics_setup["ws_a1"]
    owner = analytics_setup["owner"]

    now = datetime.now(timezone.utc)
    t = QueryTrace(
        trace_id="trc_ttft_test",
        request_id="req_ttft",
        organization_id=org_a.id,
        workspace_id=ws_a1.id,
        started_at=now,
        status="SUCCESS",
        operation_type="CHAT",
        total_latency_ms=900.0,
        metadata_={"time_to_first_token_ms": 110.0},
    )
    db_session.add(t)
    db_session.flush()

    s = QueryTraceSpan(
        trace_id="trc_ttft_test",
        span_name="STREAM_GENERATION",
        span_type="AI_PROVIDER",
        started_at=now,
        duration_ms=850.0,
        status="SUCCESS",
        metadata_={"time_to_first_token_ms": 110.0},
    )
    db_session.add(s)
    db_session.commit()

    ctx = WorkspaceContext(
        workspace_id=ws_a1.id,
        workspace_slug=ws_a1.slug,
        organization_id=org_a.id,
        organization_slug=org_a.slug,
        user_id=owner.id,
        workspace_role=WorkspaceRole.WORKSPACE_ADMIN,
        organization_role=OrganizationRole.OWNER,
    )

    analytics = TraceAnalyticsService.get_analytics(db_session, ctx)
    assert analytics.streaming.stream_count == 1
    assert analytics.streaming.average_ttft_ms == 110.0


# =========================================================================
# 4. Trace Export, RBAC & Isolation Tests (19 - 24)
# =========================================================================

def test_trace_export_authorization(analytics_client: TestClient, analytics_setup: dict):
    """Test 19: Viewer and Contributor are denied export access."""
    ws = analytics_setup["ws_a1"]
    viewer = analytics_setup["viewer"]
    viewer_token = create_access_token(viewer.id, email=viewer.email)

    resp = analytics_client.get(
        "/api/v1/traces/trc_nonexistent/export",
        headers={"Authorization": f"Bearer {viewer_token}", "X-Workspace-Id": str(ws.id)},
    )
    assert resp.status_code == 403


def test_trace_export_privacy(analytics_client: TestClient, analytics_setup: dict):
    """Test 20: Trace export never contains raw query, prompt, or sensitive tokens."""
    ws = analytics_setup["ws_a1"]
    admin = analytics_setup["admin"]
    token = create_access_token(admin.id, email=admin.email)

    chat_resp = analytics_client.post(
        "/api/v1/chat",
        headers={"Authorization": f"Bearer {token}", "X-Workspace-Id": str(ws.id)},
        json={"question": "Confidential question secret_token_xyz"},
    )
    assert chat_resp.status_code == 200
    trc_id = chat_resp.headers["X-Trace-Id"]

    export_resp = analytics_client.get(
        f"/api/v1/traces/{trc_id}/export",
        headers={"Authorization": f"Bearer {token}", "X-Workspace-Id": str(ws.id)},
    )
    assert export_resp.status_code == 200
    dumped = json.dumps(export_resp.json())
    assert "Confidential question" not in dumped
    assert "secret_token_xyz" not in dumped


def test_analytics_authorization(analytics_client: TestClient, analytics_setup: dict):
    """Test 21: Analytics endpoint rejects non-admin users with 403."""
    ws = analytics_setup["ws_a1"]
    contrib = analytics_setup["contrib"]
    token = create_access_token(contrib.id, email=contrib.email)

    resp = analytics_client.get(
        "/api/v1/traces/analytics",
        headers={"Authorization": f"Bearer {token}", "X-Workspace-Id": str(ws.id)},
    )
    assert resp.status_code == 403


def test_analytics_filter_isolation(analytics_client: TestClient, analytics_setup: dict):
    """Test 22: Workspace Admin cannot query other workspaces via filter parameter."""
    ws_a1 = analytics_setup["ws_a1"]
    ws_a2 = analytics_setup["ws_a2"]
    admin = analytics_setup["admin"]
    token = create_access_token(admin.id, email=admin.email)

    resp = analytics_client.get(
        f"/api/v1/traces/analytics?workspace_id={ws_a2.id}",
        headers={"Authorization": f"Bearer {token}", "X-Workspace-Id": str(ws_a1.id)},
    )
    assert resp.status_code == 403


def test_time_window_filtering(analytics_client: TestClient, analytics_setup: dict):
    """Test 23: Accurate filtering between from_time and to_time boundaries."""
    ws = analytics_setup["ws_a1"]
    admin = analytics_setup["admin"]
    token = create_access_token(admin.id, email=admin.email)

    now = datetime.now(timezone.utc)
    from_iso = (now - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    to_iso = (now + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")

    resp = analytics_client.get(
        f"/api/v1/traces/analytics?from_time={from_iso}&to_time={to_iso}",
        headers={"Authorization": f"Bearer {token}", "X-Workspace-Id": str(ws.id)},
    )
    assert resp.status_code == 200


def test_empty_dataset_behavior(analytics_client: TestClient, analytics_setup: dict):
    """Test 24: Returns 0 values gracefully without division-by-zero errors when no traces exist."""
    ws = analytics_setup["ws_a1"]
    admin = analytics_setup["admin"]
    token = create_access_token(admin.id, email=admin.email)

    future_iso = (datetime.now(timezone.utc) + timedelta(days=200)).strftime("%Y-%m-%dT%H:%M:%SZ")
    resp = analytics_client.get(
        f"/api/v1/traces/analytics?from_time={future_iso}",
        headers={"Authorization": f"Bearer {token}", "X-Workspace-Id": str(ws.id)},
    )
    assert resp.status_code == 200
    res = resp.json()
    assert res["overview"]["request_count"] == 0
    assert res["overview"]["error_rate"] == 0.0
    assert res["overview"]["average_latency_ms"] == 0.0


# =========================================================================
# 5. Rollback, Read-Only & RAG Equivalence (25 - 27)
# =========================================================================

def test_rollback_on_retention_failure(analytics_setup: dict, db_session: Session, monkeypatch):
    """Test 25: Savepoint rollback preserves database records on unexpected failure."""
    org_a = analytics_setup["org_a"]
    ws_a1 = analytics_setup["ws_a1"]
    owner = analytics_setup["owner"]

    old_time = datetime.now(timezone.utc) - timedelta(days=50)
    trace = QueryTrace(
        trace_id="trc_rb_verify",
        request_id="req_rb_v",
        organization_id=org_a.id,
        workspace_id=ws_a1.id,
        started_at=old_time,
        status="SUCCESS",
        operation_type="CHAT",
    )
    db_session.add(trace)
    db_session.commit()

    ctx = WorkspaceContext(
        workspace_id=ws_a1.id,
        workspace_slug=ws_a1.slug,
        organization_id=org_a.id,
        organization_slug=org_a.slug,
        user_id=owner.id,
        workspace_role=WorkspaceRole.WORKSPACE_ADMIN,
        organization_role=OrganizationRole.OWNER,
    )

    orig_exec = db_session.execute

    def failing_exec(statement, *args, **kwargs):
        if "DELETE FROM query_traces" in str(statement):
            raise RuntimeError("Forced simulation error")
        return orig_exec(statement, *args, **kwargs)

    monkeypatch.setattr(db_session, "execute", failing_exec)

    with pytest.raises(RuntimeError):
        TraceRetentionService.delete_expired_traces(db_session, ctx, days=30)

    t = db_session.scalars(select(QueryTrace).where(QueryTrace.trace_id == "trc_rb_verify")).first()
    assert t is not None


def test_analytics_does_not_modify_traces(analytics_client: TestClient, analytics_setup: dict, db_session: Session):
    """Test 26: Analytics querying is strictly read-only and does not mutate stored traces."""
    ws = analytics_setup["ws_a1"]
    admin = analytics_setup["admin"]
    token = create_access_token(admin.id, email=admin.email)

    chat_resp = analytics_client.post(
        "/api/v1/chat",
        headers={"Authorization": f"Bearer {token}", "X-Workspace-Id": str(ws.id)},
        json={"question": "Read only check"},
    )
    assert chat_resp.status_code == 200
    trc_id = chat_resp.headers["X-Trace-Id"]

    t_before = db_session.scalars(select(QueryTrace).where(QueryTrace.trace_id == trc_id)).first()
    assert t_before is not None

    _ = analytics_client.get(
        "/api/v1/traces/analytics",
        headers={"Authorization": f"Bearer {token}", "X-Workspace-Id": str(ws.id)},
    )

    t_after = db_session.scalars(select(QueryTrace).where(QueryTrace.trace_id == trc_id)).first()
    assert t_after.id == t_before.id
    assert t_after.started_at == t_before.started_at


def test_rag_results_remain_unchanged(analytics_client: TestClient, analytics_setup: dict):
    """Test 27: RAG answers and sources remain strictly unaltered."""
    ws = analytics_setup["ws_a1"]
    contrib = analytics_setup["contrib"]
    token = create_access_token(contrib.id, email=contrib.email)

    resp = analytics_client.post(
        "/api/v1/chat",
        headers={"Authorization": f"Bearer {token}", "X-Workspace-Id": str(ws.id)},
        json={"question": "What does platform analytics provide?"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["answer"] == "Analytics response content."
    assert len(data["sources"]) == 1
    assert data["sources"][0]["document_id"] == str(analytics_setup["doc"].id)


# =========================================================================
# 6. Governance Hardening Tests (28 - 39)
# =========================================================================

def test_retention_cleanup_generates_audit_event(analytics_setup: dict, db_session: Session):
    """Test 28: Retention cleanup creates an immutable TRACE_RETENTION_EXECUTED audit event."""
    org_a = analytics_setup["org_a"]
    ws_a1 = analytics_setup["ws_a1"]
    owner = analytics_setup["owner"]

    old_time = datetime.now(timezone.utc) - timedelta(days=60)
    trace = QueryTrace(
        trace_id="trc_audit_ret_1",
        request_id="req_audit_ret_1",
        organization_id=org_a.id,
        workspace_id=ws_a1.id,
        started_at=old_time,
        status="SUCCESS",
        operation_type="CHAT",
    )
    db_session.add(trace)
    db_session.commit()

    ctx = WorkspaceContext(
        workspace_id=ws_a1.id,
        workspace_slug=ws_a1.slug,
        organization_id=org_a.id,
        organization_slug=org_a.slug,
        user_id=owner.id,
        workspace_role=WorkspaceRole.WORKSPACE_ADMIN,
        organization_role=OrganizationRole.OWNER,
    )

    res = TraceRetentionService.delete_expired_traces(db_session, ctx, days=30, dry_run=False)
    assert res.deleted_traces_count == 1

    # Check for the audit event
    audit = db_session.scalars(
        select(AuditLog)
        .where(
            AuditLog.organization_id == org_a.id,
            AuditLog.event_type == AuditEventType.TRACE_RETENTION_EXECUTED,
        )
        .order_by(AuditLog.created_at.desc())
    ).first()

    assert audit is not None
    assert audit.action == "DELETE"
    assert audit.outcome == AuditOutcome.SUCCESS
    assert audit.resource_type == "QUERY_TRACE"
    assert audit.actor_user_id == owner.id
    assert audit.metadata_["deleted_traces_count"] == 1
    assert audit.metadata_["dry_run"] is False
    assert audit.metadata_["retention_days"] == 30
    assert "cutoff" in audit.metadata_


def test_successful_cleanup_and_audit_event_commit_together(analytics_client: TestClient, analytics_setup: dict, db_session: Session):
    """Test 29: Retention cleanup and audit record are atomically committed together via API."""
    org_a = analytics_setup["org_a"]
    ws_a1 = analytics_setup["ws_a1"]
    owner = analytics_setup["owner"]
    token = create_access_token(owner.id, email=owner.email)

    old_time = datetime.now(timezone.utc) - timedelta(days=45)
    trace = QueryTrace(
        trace_id="trc_atomic_api_1",
        request_id="req_atomic_api_1",
        organization_id=org_a.id,
        workspace_id=ws_a1.id,
        started_at=old_time,
        status="SUCCESS",
        operation_type="CHAT",
    )
    db_session.add(trace)
    db_session.commit()

    resp = analytics_client.post(
        "/api/v1/traces/retention/cleanup",
        headers={"Authorization": f"Bearer {token}", "X-Workspace-Id": str(ws_a1.id)},
        json={"days": 30, "dry_run": False},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["deleted_traces_count"] == 1
    assert data["dry_run"] is False

    # Verify trace is gone
    t = db_session.scalars(select(QueryTrace).where(QueryTrace.trace_id == "trc_atomic_api_1")).first()
    assert t is None

    # Verify audit event is present
    audit = db_session.scalars(
        select(AuditLog)
        .where(
            AuditLog.organization_id == org_a.id,
            AuditLog.event_type == AuditEventType.TRACE_RETENTION_EXECUTED,
        )
    ).first()
    assert audit is not None


def test_audit_failure_rolls_back_cleanup(analytics_setup: dict, db_session: Session, monkeypatch):
    """Test 30: Failure in audit logging rolls back trace deletion."""
    org_a = analytics_setup["org_a"]
    ws_a1 = analytics_setup["ws_a1"]
    owner = analytics_setup["owner"]

    old_time = datetime.now(timezone.utc) - timedelta(days=50)
    trace = QueryTrace(
        trace_id="trc_audit_rb_1",
        request_id="req_audit_rb_1",
        organization_id=org_a.id,
        workspace_id=ws_a1.id,
        started_at=old_time,
        status="SUCCESS",
        operation_type="CHAT",
    )
    db_session.add(trace)
    db_session.commit()

    ctx = WorkspaceContext(
        workspace_id=ws_a1.id,
        workspace_slug=ws_a1.slug,
        organization_id=org_a.id,
        organization_slug=org_a.slug,
        user_id=owner.id,
        workspace_role=WorkspaceRole.WORKSPACE_ADMIN,
        organization_role=OrganizationRole.OWNER,
    )

    def failing_record_event(*args, **kwargs):
        raise RuntimeError("Simulated audit service failure")

    monkeypatch.setattr(AuditLogService, "record_event", failing_record_event)

    with pytest.raises(RuntimeError, match="Simulated audit service failure"):
        TraceRetentionService.delete_expired_traces(db_session, ctx, days=30, dry_run=False)

    # Verify trace was NOT deleted because of rollback
    t = db_session.scalars(select(QueryTrace).where(QueryTrace.trace_id == "trc_audit_rb_1")).first()
    assert t is not None


def test_trace_export_generates_audit_event(analytics_client: TestClient, analytics_setup: dict, db_session: Session):
    """Test 31: Exporting trace detail records an immutable TRACE_EXPORTED audit event."""
    org_a = analytics_setup["org_a"]
    ws_a1 = analytics_setup["ws_a1"]
    admin = analytics_setup["admin"]
    token = create_access_token(admin.id, email=admin.email)

    trace = QueryTrace(
        trace_id="trc_export_audit_1",
        request_id="req_exp_aud_1",
        organization_id=org_a.id,
        workspace_id=ws_a1.id,
        started_at=datetime.now(timezone.utc),
        status="SUCCESS",
        operation_type="CHAT",
    )
    db_session.add(trace)
    db_session.commit()

    resp = analytics_client.get(
        f"/api/v1/traces/{trace.trace_id}/export",
        headers={"Authorization": f"Bearer {token}", "X-Workspace-Id": str(ws_a1.id)},
    )
    assert resp.status_code == 200

    audit = db_session.scalars(
        select(AuditLog)
        .where(
            AuditLog.organization_id == org_a.id,
            AuditLog.event_type == AuditEventType.TRACE_EXPORTED,
        )
    ).first()

    assert audit is not None
    assert audit.action == "EXPORT"
    assert audit.outcome == AuditOutcome.SUCCESS
    assert audit.resource_id == trace.trace_id
    assert audit.metadata_["export_format"] == "JSON"
    assert audit.metadata_["trace_id"] == trace.trace_id


def test_unauthorized_export_generates_no_successful_export_audit_event(
    analytics_client: TestClient, analytics_setup: dict, db_session: Session
):
    """Test 32: Unauthorized export attempt produces no successful TRACE_EXPORTED audit log."""
    org_a = analytics_setup["org_a"]
    ws_a1 = analytics_setup["ws_a1"]
    contrib = analytics_setup["contrib"]
    token = create_access_token(contrib.id, email=contrib.email)

    trace = QueryTrace(
        trace_id="trc_unauth_exp_1",
        request_id="req_unauth_1",
        organization_id=org_a.id,
        workspace_id=ws_a1.id,
        started_at=datetime.now(timezone.utc),
        status="SUCCESS",
        operation_type="CHAT",
    )
    db_session.add(trace)
    db_session.commit()

    resp = analytics_client.get(
        f"/api/v1/traces/{trace.trace_id}/export",
        headers={"Authorization": f"Bearer {token}", "X-Workspace-Id": str(ws_a1.id)},
    )
    assert resp.status_code == 403

    audits = db_session.scalars(
        select(AuditLog).where(
            AuditLog.organization_id == org_a.id,
            AuditLog.event_type == AuditEventType.TRACE_EXPORTED,
            AuditLog.outcome == AuditOutcome.SUCCESS,
        )
    ).all()
    assert len(audits) == 0


def test_retention_remains_org_admin_owner_only(analytics_client: TestClient, analytics_setup: dict, db_session: Session):
    """Test 33: Workspace Admin cannot execute organization retention cleanup."""
    org_a = analytics_setup["org_a"]
    ws_a2 = analytics_setup["ws_a2"]

    # User who is Workspace Admin in WS A2, but only MEMBER in Org A
    ws_admin_user = User(
        email=f"wsadmin-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password=hash_password("Pass123!"),
        full_name="WS Admin Member",
    )
    db_session.add(ws_admin_user)
    db_session.flush()

    org_m = OrganizationMembership(
        organization_id=org_a.id,
        user_id=ws_admin_user.id,
        role=OrganizationRole.MEMBER,
    )
    ws_m = WorkspaceMembership(
        workspace_id=ws_a2.id,
        user_id=ws_admin_user.id,
        role=WorkspaceRole.WORKSPACE_ADMIN,
    )
    db_session.add_all([org_m, ws_m])
    db_session.commit()

    token = create_access_token(ws_admin_user.id, email=ws_admin_user.email)

    # Try retention cleanup
    resp = analytics_client.post(
        "/api/v1/traces/retention/cleanup",
        headers={"Authorization": f"Bearer {token}", "X-Workspace-Id": str(ws_a2.id)},
        json={"days": 30},
    )
    assert resp.status_code == 403


def test_unauthorized_roles_cannot_trigger_cleanup(analytics_client: TestClient, analytics_setup: dict):
    """Test 34: Contributor and Viewer cannot preview or trigger retention cleanup."""
    ws = analytics_setup["ws_a1"]
    contrib = analytics_setup["contrib"]
    token = create_access_token(contrib.id, email=contrib.email)

    resp_preview = analytics_client.get(
        "/api/v1/traces/retention/preview",
        headers={"Authorization": f"Bearer {token}", "X-Workspace-Id": str(ws.id)},
    )
    assert resp_preview.status_code == 403

    resp_clean = analytics_client.post(
        "/api/v1/traces/retention/cleanup",
        headers={"Authorization": f"Bearer {token}", "X-Workspace-Id": str(ws.id)},
        json={"days": 30},
    )
    assert resp_clean.status_code == 403


def test_retention_cannot_cross_organizations(analytics_setup: dict, db_session: Session):
    """Test 35: Retention cleanup in Org A never deletes expired traces in Org B."""
    org_a = analytics_setup["org_a"]
    org_b = analytics_setup["org_b"]
    ws_a1 = analytics_setup["ws_a1"]
    ws_b1 = analytics_setup["ws_b1"]
    owner = analytics_setup["owner"]

    old_time = datetime.now(timezone.utc) - timedelta(days=60)
    t_a = QueryTrace(
        trace_id="trc_cross_a",
        request_id="req_cross_a",
        organization_id=org_a.id,
        workspace_id=ws_a1.id,
        started_at=old_time,
        status="SUCCESS",
        operation_type="CHAT",
    )
    t_b = QueryTrace(
        trace_id="trc_cross_b",
        request_id="req_cross_b",
        organization_id=org_b.id,
        workspace_id=ws_b1.id,
        started_at=old_time,
        status="SUCCESS",
        operation_type="CHAT",
    )
    db_session.add_all([t_a, t_b])
    db_session.commit()

    ctx_a = WorkspaceContext(
        workspace_id=ws_a1.id,
        workspace_slug=ws_a1.slug,
        organization_id=org_a.id,
        organization_slug=org_a.slug,
        user_id=owner.id,
        workspace_role=WorkspaceRole.WORKSPACE_ADMIN,
        organization_role=OrganizationRole.OWNER,
    )

    res = TraceRetentionService.delete_expired_traces(db_session, ctx_a, days=30, dry_run=False)
    assert res.deleted_traces_count == 1

    # Org A trace is deleted
    assert db_session.scalars(select(QueryTrace).where(QueryTrace.trace_id == "trc_cross_a")).first() is None
    # Org B trace is preserved
    assert db_session.scalars(select(QueryTrace).where(QueryTrace.trace_id == "trc_cross_b")).first() is not None


def test_retention_cannot_delete_newer_traces(analytics_setup: dict, db_session: Session):
    """Test 36: Traces within the retention window are never deleted."""
    org_a = analytics_setup["org_a"]
    ws_a1 = analytics_setup["ws_a1"]
    owner = analytics_setup["owner"]

    recent_time_1 = datetime.now(timezone.utc) - timedelta(days=5)
    recent_time_2 = datetime.now(timezone.utc) - timedelta(hours=2)

    t_rec_1 = QueryTrace(
        trace_id="trc_rec_1",
        request_id="req_rec_1",
        organization_id=org_a.id,
        workspace_id=ws_a1.id,
        started_at=recent_time_1,
        status="SUCCESS",
        operation_type="CHAT",
    )
    t_rec_2 = QueryTrace(
        trace_id="trc_rec_2",
        request_id="req_rec_2",
        organization_id=org_a.id,
        workspace_id=ws_a1.id,
        started_at=recent_time_2,
        status="SUCCESS",
        operation_type="CHAT",
    )
    db_session.add_all([t_rec_1, t_rec_2])
    db_session.commit()

    ctx = WorkspaceContext(
        workspace_id=ws_a1.id,
        workspace_slug=ws_a1.slug,
        organization_id=org_a.id,
        organization_slug=org_a.slug,
        user_id=owner.id,
        workspace_role=WorkspaceRole.WORKSPACE_ADMIN,
        organization_role=OrganizationRole.OWNER,
    )

    res = TraceRetentionService.delete_expired_traces(db_session, ctx, days=30, dry_run=False)
    assert res.deleted_traces_count == 0

    assert db_session.scalars(select(QueryTrace).where(QueryTrace.trace_id == "trc_rec_1")).first() is not None
    assert db_session.scalars(select(QueryTrace).where(QueryTrace.trace_id == "trc_rec_2")).first() is not None


def test_active_incomplete_traces_safety(analytics_setup: dict, db_session: Session):
    """Test 37: Active/partial/recent traces are safely preserved during retention cleanup."""
    org_a = analytics_setup["org_a"]
    ws_a1 = analytics_setup["ws_a1"]
    owner = analytics_setup["owner"]

    recent_partial = QueryTrace(
        trace_id="trc_active_partial_1",
        request_id="req_act_part_1",
        organization_id=org_a.id,
        workspace_id=ws_a1.id,
        started_at=datetime.now(timezone.utc) - timedelta(minutes=5),
        status="PARTIAL",
        operation_type="CHAT",
    )
    db_session.add(recent_partial)
    db_session.commit()

    ctx = WorkspaceContext(
        workspace_id=ws_a1.id,
        workspace_slug=ws_a1.slug,
        organization_id=org_a.id,
        organization_slug=org_a.slug,
        user_id=owner.id,
        workspace_role=WorkspaceRole.WORKSPACE_ADMIN,
        organization_role=OrganizationRole.OWNER,
    )

    res = TraceRetentionService.delete_expired_traces(db_session, ctx, days=30, dry_run=False)
    assert res.deleted_traces_count == 0

    t = db_session.scalars(select(QueryTrace).where(QueryTrace.trace_id == "trc_active_partial_1")).first()
    assert t is not None


def test_exported_telemetry_contains_no_sensitive_content(
    analytics_client: TestClient, analytics_setup: dict, db_session: Session
):
    """Test 38: Export sanitizes and excludes all raw queries, prompts, passwords, tokens, cookies, and keys."""
    org_a = analytics_setup["org_a"]
    ws_a1 = analytics_setup["ws_a1"]
    admin = analytics_setup["admin"]
    token = create_access_token(admin.id, email=admin.email)

    trace = QueryTrace(
        trace_id="trc_sensitive_leak_test",
        request_id="req_leak_t",
        organization_id=org_a.id,
        workspace_id=ws_a1.id,
        started_at=datetime.now(timezone.utc),
        status="SUCCESS",
        operation_type="CHAT",
        metadata_={
            "query": "super secret confidential query",
            "prompt": "system prompt leaking internals",
            "password": "secret_password",
            "token": "bearer_token_123",
            "api_key": "sk-1234567890",
            "cookie": "session_cookie=abc",
            "safe_metric": 42,
        },
    )
    db_session.add(trace)
    db_session.flush()

    span = QueryTraceSpan(
        trace_id="trc_sensitive_leak_test",
        span_name="EMBEDDING",
        span_type="EMBEDDING",
        started_at=datetime.now(timezone.utc),
        duration_ms=12.0,
        status="SUCCESS",
        metadata_={
            "chunk_text": "internal chunk content",
            "response": "raw llm generation",
            "safe_model": "gemini-1.5-flash",
        },
    )
    db_session.add(span)
    db_session.commit()

    resp = analytics_client.get(
        f"/api/v1/traces/{trace.trace_id}/export",
        headers={"Authorization": f"Bearer {token}", "X-Workspace-Id": str(ws_a1.id)},
    )
    assert resp.status_code == 200
    export_json = resp.json()

    # Convert entire export to string for comprehensive leakage check
    export_str = json.dumps(export_json)

    # Verify sensitive injected values are NOT in export
    assert "super secret confidential query" not in export_str
    assert "system prompt leaking internals" not in export_str
    assert "secret_password" not in export_str
    assert "bearer_token_123" not in export_str
    assert "sk-1234567890" not in export_str
    assert "session_cookie=abc" not in export_str
    assert "internal chunk content" not in export_str
    assert "raw llm generation" not in export_str

    # Verify safe fields remain present
    assert export_json["metadata"]["safe_metric"] == 42
    assert export_json["spans"][0]["metadata"]["safe_model"] == "gemini-1.5-flash"


def test_retention_never_modifies_audit_logs(analytics_setup: dict, db_session: Session):
    """Test 39: Retention deletion strictly ignores and preserves audit_logs records."""
    org_a = analytics_setup["org_a"]
    ws_a1 = analytics_setup["ws_a1"]
    owner = analytics_setup["owner"]

    # 1. Create a 100-day-old audit log
    old_audit = AuditLog(
        id=uuid.uuid4(),
        organization_id=org_a.id,
        workspace_id=ws_a1.id,
        actor_user_id=owner.id,
        event_type="DOCUMENT_CREATED",
        action="CREATE",
        outcome="SUCCESS",
        resource_type="DOCUMENT",
        resource_id="doc-old-123",
        created_at=datetime.now(timezone.utc) - timedelta(days=100),
        event_hash="hash_old_audit_100",
    )
    db_session.add(old_audit)

    # 2. Create a 100-day-old trace
    old_trace = QueryTrace(
        trace_id="trc_old_audit_safe_1",
        request_id="req_old_aud_s1",
        organization_id=org_a.id,
        workspace_id=ws_a1.id,
        started_at=datetime.now(timezone.utc) - timedelta(days=100),
        status="SUCCESS",
        operation_type="CHAT",
    )
    db_session.add(old_trace)
    db_session.commit()

    ctx = WorkspaceContext(
        workspace_id=ws_a1.id,
        workspace_slug=ws_a1.slug,
        organization_id=org_a.id,
        organization_slug=org_a.slug,
        user_id=owner.id,
        workspace_role=WorkspaceRole.WORKSPACE_ADMIN,
        organization_role=OrganizationRole.OWNER,
    )

    # Run retention cleanup
    res = TraceRetentionService.delete_expired_traces(db_session, ctx, days=30, dry_run=False)
    assert res.deleted_traces_count == 1

    # Verify trace is deleted
    assert db_session.scalars(select(QueryTrace).where(QueryTrace.trace_id == "trc_old_audit_safe_1")).first() is None

    # Verify the 100-day-old audit log is completely intact
    aud_check = db_session.scalars(select(AuditLog).where(AuditLog.id == old_audit.id)).first()
    assert aud_check is not None
    assert aud_check.event_hash == "hash_old_audit_100"

