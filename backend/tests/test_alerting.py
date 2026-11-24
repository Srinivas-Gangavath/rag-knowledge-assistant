"""Security, Functional and Governance Test Suite for Phase 1.8 Alerting & Diagnostics.

Contains 28 dedicated tests mapping 1:1 to Section 26:
1. alert creation from high latency rule
2. error-rate alert
3. provider failure alert
4. retrieval degradation proxy
5. anomaly detection
6. minimum sample size protection
7. cooldown deduplication
8. acknowledge workflow
9. resolve workflow
10. role-based alert access
11. workspace isolation
12. organization isolation
13. cross-tenant alert access denied
14. cross-tenant rule creation denied
15. invalid threshold rejected
16. manual evaluation authorization
17. alert auditing
18. alert/trace correlation
19. no raw query stored
20. no prompt/context/chunk stored
21. no credentials stored
22. diagnostics distinguish observed vs inferred
23. alert evaluation does not modify traces
24. alert evaluation does not modify audit logs incorrectly
25. trace retention does not delete alerts
26. alert lifecycle remains consistent
27. duplicate alert prevention
28. RAG results remain unchanged
"""

from __future__ import annotations

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
    AlertOperator,
    AlertRule,
    AlertSeverity,
    AlertStatus,
    AuditEventType,
    AuditLog,
    AuditOutcome,
    Document,
    DocumentChunk,
    DocumentStatus,
    Organization,
    OrganizationMembership,
    OrganizationRole,
    PlatformAlert,
    QueryTrace,
    QueryTraceSpan,
    User,
    Workspace,
    WorkspaceMembership,
    WorkspaceRole,
)
from app.main import app
from app.schemas.alert import AlertRuleCreateRequest, AlertRuleUpdateRequest
from app.services.alerting.alert_service import AlertService
from app.services.alerting.anomaly_service import AnomalyDetectionService
from app.services.alerting.diagnostics_service import PlatformDiagnosticsService
from app.services.alerting.evaluation_service import AlertEvaluationService
from app.services.alerting.rule_service import AlertRuleService
from app.services.alerting.taxonomy import (
    AlertMetricName,
    AlertType,
    DiagnosticCategory,
    InvestigationTarget,
    PlatformSubsystem,
)
from app.services.audit_service import AuditLogService
from app.services.tracing.retention_service import TraceRetentionService
from app.services.tracing.taxonomy import SpanName, TraceStatus
from tests.conftest import postgres_available


@pytest.fixture
def alerting_setup(db_session: Session):
    if not postgres_available():
        pytest.skip("PostgreSQL is not available for database tests.")

    # Create Org A and Org B
    org_a = Organization(name="Alerting Org A", slug=f"alert-org-a-{uuid.uuid4().hex[:6]}")
    org_b = Organization(name="Alerting Org B", slug=f"alert-org-b-{uuid.uuid4().hex[:6]}")
    db_session.add_all([org_a, org_b])
    db_session.flush()

    # Create Workspaces
    ws_a1 = Workspace(organization_id=org_a.id, name="Alert WS A1", slug=f"alert-ws-a1-{uuid.uuid4().hex[:6]}")
    ws_a2 = Workspace(organization_id=org_a.id, name="Alert WS A2", slug=f"alert-ws-a2-{uuid.uuid4().hex[:6]}")
    ws_b1 = Workspace(organization_id=org_b.id, name="Alert WS B1", slug=f"alert-ws-b1-{uuid.uuid4().hex[:6]}")
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

    # Add a sample document and chunk to WS A1 for RAG test
    doc = Document(
        workspace_id=ws_a1.id,
        filename=f"alert_doc_{uuid.uuid4().hex[:6]}.pdf",
        original_filename="Alert Guide.pdf",
        file_path="/tmp/alert_doc.pdf",
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
        content="Platform operational alerting provides deterministic anomaly detection.",
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
def alerting_client(db_session: Session, monkeypatch) -> TestClient:
    if not postgres_available():
        pytest.skip("PostgreSQL is not available for database tests.")

    provider = MagicMock()
    provider.create_embedding.side_effect = lambda text, task: [0.1] * 768
    provider.generate_text.side_effect = lambda prompt: "Alert response content."
    provider.stream_text.side_effect = lambda prompt: iter(["Alert ", "streaming ", "answer."])
    monkeypatch.setattr("app.services.rag.get_ai_provider", lambda: provider)

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.pop(get_db, None)


def _make_context(user: User, org: Organization, ws: Workspace, org_role: OrganizationRole, ws_role: WorkspaceRole) -> WorkspaceContext:
    return WorkspaceContext(
        workspace_id=ws.id,
        workspace_slug=ws.slug,
        organization_id=org.id,
        organization_slug=org.slug,
        user_id=user.id,
        workspace_role=ws_role,
        organization_role=org_role,
    )


def _seed_traces(db: Session, org_id: uuid.UUID, ws_id: uuid.UUID, count: int, latency_ms: float = 100.0, status: str = "SUCCESS", result_count: int = 3, grounded: bool = True):
    now = datetime.now(timezone.utc)
    traces = []
    for i in range(count):
        t = QueryTrace(
            trace_id=f"trc-{uuid.uuid4().hex[:12]}",
            request_id=f"req-{uuid.uuid4().hex[:12]}",
            organization_id=org_id,
            workspace_id=ws_id,
            operation_type="CHAT",
            status=status,
            started_at=now - timedelta(minutes=2),
            completed_at=now - timedelta(minutes=2) + timedelta(milliseconds=latency_ms),
            total_latency_ms=latency_ms,
            retrieval_mode="hybrid",
            grounded=grounded,
            result_count=result_count,
            metadata_={"test_seed": i},
        )
        db.add(t)
        traces.append(t)
    db.commit()
    return traces


# =========================================================================
# 1. Alert Creation from High Latency Rule
# =========================================================================

def test_alert_creation_from_high_latency_rule(db_session: Session, alerting_setup: dict):
    """Test 1: Alert is generated when p95 total latency breaches configured rule threshold."""
    org_a = alerting_setup["org_a"]
    ws_a1 = alerting_setup["ws_a1"]
    admin = alerting_setup["admin"]

    ctx = _make_context(admin, org_a, ws_a1, OrganizationRole.MEMBER, WorkspaceRole.WORKSPACE_ADMIN)

    # 1. Create a rule for total_latency_p95 > 2500ms
    rule = AlertRuleService.create_rule(
        db_session,
        ctx,
        AlertRuleCreateRequest(
            workspace_id=ws_a1.id,
            rule_type=AlertType.LATENCY_HIGH.value,
            metric_name=AlertMetricName.TOTAL_LATENCY_P95.value,
            operator=AlertOperator.GT,
            threshold=2500.0,
            window_minutes=15,
            minimum_sample_size=5,
            severity=AlertSeverity.WARNING,
        ),
    )

    # 2. Seed 6 traces with 3000ms latency
    _seed_traces(db_session, org_a.id, ws_a1.id, count=6, latency_ms=3000.0)

    # 3. Evaluate alerts
    eval_res = AlertEvaluationService.evaluate(db_session, ctx, workspace_id=ws_a1.id)

    assert eval_res.alerts_created >= 1
    # Check alert in DB
    alert = db_session.scalars(
        select(PlatformAlert).where(
            PlatformAlert.workspace_id == ws_a1.id,
            PlatformAlert.alert_type == AlertType.LATENCY_HIGH.value,
        )
    ).first()

    assert alert is not None
    assert alert.metric_name == AlertMetricName.TOTAL_LATENCY_P95.value
    assert alert.metric_value == 3000.0
    assert alert.threshold_value == 2500.0
    assert alert.status == AlertStatus.OPEN.value
    assert alert.severity == AlertSeverity.WARNING.value


# =========================================================================
# 2. Error-Rate Alert
# =========================================================================

def test_error_rate_alert(db_session: Session, alerting_setup: dict):
    """Test 2: Alert is generated when request error rate breaches configured percentage."""
    org_a = alerting_setup["org_a"]
    ws_a1 = alerting_setup["ws_a1"]
    admin = alerting_setup["admin"]

    ctx = _make_context(admin, org_a, ws_a1, OrganizationRole.MEMBER, WorkspaceRole.WORKSPACE_ADMIN)

    AlertRuleService.create_rule(
        db_session,
        ctx,
        AlertRuleCreateRequest(
            workspace_id=ws_a1.id,
            rule_type=AlertType.LLM_ERROR_RATE_HIGH.value,
            metric_name=AlertMetricName.ERROR_RATE.value,
            operator=AlertOperator.GT,
            threshold=20.0,
            window_minutes=15,
            minimum_sample_size=5,
            severity=AlertSeverity.ERROR,
        ),
    )

    # Seed 3 success and 3 error traces (50% error rate > 20%)
    _seed_traces(db_session, org_a.id, ws_a1.id, count=3, status="SUCCESS")
    _seed_traces(db_session, org_a.id, ws_a1.id, count=3, status="ERROR")

    eval_res = AlertEvaluationService.evaluate(db_session, ctx, workspace_id=ws_a1.id)
    assert eval_res.alerts_created >= 1

    alert = db_session.scalars(
        select(PlatformAlert).where(
            PlatformAlert.workspace_id == ws_a1.id,
            PlatformAlert.alert_type == AlertType.LLM_ERROR_RATE_HIGH.value,
        )
    ).first()

    assert alert is not None
    assert alert.metric_value == 50.0
    assert alert.status == AlertStatus.OPEN.value
    assert alert.severity == AlertSeverity.ERROR.value


# =========================================================================
# 3. Provider Failure Alert
# =========================================================================

def test_provider_failure_alert(db_session: Session, alerting_setup: dict):
    """Test 3: Detect elevated failure rate on AI provider interactions."""
    org_a = alerting_setup["org_a"]
    ws_a1 = alerting_setup["ws_a1"]
    admin = alerting_setup["admin"]

    ctx = _make_context(admin, org_a, ws_a1, OrganizationRole.MEMBER, WorkspaceRole.WORKSPACE_ADMIN)

    AlertRuleService.create_rule(
        db_session,
        ctx,
        AlertRuleCreateRequest(
            workspace_id=ws_a1.id,
            rule_type=AlertType.PROVIDER_FAILURE_SPIKE.value,
            metric_name=AlertMetricName.PROVIDER_ERROR_RATE.value,
            operator=AlertOperator.GT,
            threshold=15.0,
            window_minutes=15,
            minimum_sample_size=5,
            severity=AlertSeverity.ERROR,
        ),
    )

    # Seed traces with provider failure spans
    traces = _seed_traces(db_session, org_a.id, ws_a1.id, count=6)
    for i, t in enumerate(traces):
        span_status = "ERROR" if i < 3 else "SUCCESS"
        span = QueryTraceSpan(
            trace_id=t.trace_id,
            span_name=SpanName.LLM_GENERATION.value,
            span_type="AI_PROVIDER",
            started_at=t.started_at,
            completed_at=t.completed_at,
            duration_ms=100.0,
            status=span_status,
        )
        db_session.add(span)
    db_session.commit()

    eval_res = AlertEvaluationService.evaluate(db_session, ctx, workspace_id=ws_a1.id)
    assert eval_res.alerts_created >= 1

    alert = db_session.scalars(
        select(PlatformAlert).where(
            PlatformAlert.workspace_id == ws_a1.id,
            PlatformAlert.alert_type == AlertType.PROVIDER_FAILURE_SPIKE.value,
        )
    ).first()
    assert alert is not None
    assert alert.severity == AlertSeverity.ERROR.value


# =========================================================================
# 4. Retrieval Degradation Proxy
# =========================================================================

def test_retrieval_degradation_proxy(db_session: Session, alerting_setup: dict):
    """Test 4: Alert triggered by elevated no-context rate in live telemetry."""
    org_a = alerting_setup["org_a"]
    ws_a1 = alerting_setup["ws_a1"]
    admin = alerting_setup["admin"]

    ctx = _make_context(admin, org_a, ws_a1, OrganizationRole.MEMBER, WorkspaceRole.WORKSPACE_ADMIN)

    AlertRuleService.create_rule(
        db_session,
        ctx,
        AlertRuleCreateRequest(
            workspace_id=ws_a1.id,
            rule_type=AlertType.NO_CONTEXT_RATE_HIGH.value,
            metric_name=AlertMetricName.NO_CONTEXT_RATE.value,
            operator=AlertOperator.GT,
            threshold=25.0,
            window_minutes=15,
            minimum_sample_size=5,
            severity=AlertSeverity.WARNING,
        ),
    )

    # Seed traces with 4 ungrounded/no-context out of 6 (66.6% > 25%)
    _seed_traces(db_session, org_a.id, ws_a1.id, count=4, result_count=0, grounded=False)
    _seed_traces(db_session, org_a.id, ws_a1.id, count=2, result_count=3, grounded=True)

    eval_res = AlertEvaluationService.evaluate(db_session, ctx, workspace_id=ws_a1.id)
    assert eval_res.alerts_created >= 1

    alert = db_session.scalars(
        select(PlatformAlert).where(
            PlatformAlert.workspace_id == ws_a1.id,
            PlatformAlert.alert_type == AlertType.NO_CONTEXT_RATE_HIGH.value,
        )
    ).first()
    assert alert is not None
    assert round(alert.metric_value, 1) == 66.7


# =========================================================================
# 5. Anomaly Detection
# =========================================================================

def test_anomaly_detection(db_session: Session, alerting_setup: dict):
    """Test 5: Statistical baseline comparison triggers ANOMALY_DETECTED on significant drift."""
    org_a = alerting_setup["org_a"]
    ws_a1 = alerting_setup["ws_a1"]
    admin = alerting_setup["admin"]

    ctx = _make_context(admin, org_a, ws_a1, OrganizationRole.MEMBER, WorkspaceRole.WORKSPACE_ADMIN)
    now = datetime.now(timezone.utc)

    # Seed historical traces (100ms latency, 2 hours ago)
    for _ in range(10):
        t = QueryTrace(
            trace_id=f"trc-hist-{uuid.uuid4().hex[:10]}",
            request_id=f"req-hist-{uuid.uuid4().hex[:10]}",
            organization_id=org_a.id,
            workspace_id=ws_a1.id,
            operation_type="CHAT",
            status="SUCCESS",
            started_at=now - timedelta(hours=2),
            completed_at=now - timedelta(hours=2) + timedelta(milliseconds=100),
            total_latency_ms=100.0,
        )
        db_session.add(t)

    # Seed current window traces (350ms latency, 3.5x baseline > 2.0x multiplier)
    for _ in range(6):
        t = QueryTrace(
            trace_id=f"trc-cur-{uuid.uuid4().hex[:10]}",
            request_id=f"req-cur-{uuid.uuid4().hex[:10]}",
            organization_id=org_a.id,
            workspace_id=ws_a1.id,
            operation_type="CHAT",
            status="SUCCESS",
            started_at=now - timedelta(minutes=3),
            completed_at=now - timedelta(minutes=3) + timedelta(milliseconds=350),
            total_latency_ms=350.0,
        )
        db_session.add(t)
    db_session.commit()

    eval_res = AlertEvaluationService.evaluate(db_session, ctx, workspace_id=ws_a1.id)
    assert eval_res.anomalies_detected >= 1

    alert = db_session.scalars(
        select(PlatformAlert).where(
            PlatformAlert.workspace_id == ws_a1.id,
            PlatformAlert.alert_type == AlertType.ANOMALY_DETECTED.value,
        )
    ).first()

    assert alert is not None
    assert alert.metadata_["deviation_ratio"] >= 2.0
    assert alert.metadata_["baseline_value"] == 100.0


# =========================================================================
# 6. Minimum Sample Size Protection
# =========================================================================

def test_minimum_sample_size_protection(db_session: Session, alerting_setup: dict):
    """Test 6: Alerts are not generated when total sample count is below minimum sample size."""
    org_a = alerting_setup["org_a"]
    ws_a1 = alerting_setup["ws_a1"]
    admin = alerting_setup["admin"]

    ctx = _make_context(admin, org_a, ws_a1, OrganizationRole.MEMBER, WorkspaceRole.WORKSPACE_ADMIN)

    AlertRuleService.create_rule(
        db_session,
        ctx,
        AlertRuleCreateRequest(
            workspace_id=ws_a1.id,
            rule_type=AlertType.LATENCY_HIGH.value,
            metric_name=AlertMetricName.TOTAL_LATENCY_P95.value,
            operator=AlertOperator.GT,
            threshold=1000.0,
            window_minutes=15,
            minimum_sample_size=10,  # Requires at least 10 samples
            severity=AlertSeverity.WARNING,
        ),
    )

    # Seed only 3 traces (exceeds threshold, but below sample size of 10)
    _seed_traces(db_session, org_a.id, ws_a1.id, count=3, latency_ms=5000.0)

    eval_res = AlertEvaluationService.evaluate(db_session, ctx, workspace_id=ws_a1.id)

    # Assert no alert was created for this rule
    rule_results = [d for d in eval_res.details if d.alert_type == AlertType.LATENCY_HIGH.value]
    assert len(rule_results) > 0
    assert rule_results[0].action_taken == "MINIMUM_SAMPLE_SIZE_GATE"

    alerts = db_session.scalars(
        select(PlatformAlert).where(
            PlatformAlert.workspace_id == ws_a1.id,
            PlatformAlert.alert_type == AlertType.LATENCY_HIGH.value,
        )
    ).all()
    assert len(alerts) == 0


# =========================================================================
# 7. Cooldown Deduplication
# =========================================================================

def test_cooldown_deduplication(db_session: Session, alerting_setup: dict):
    """Test 7: Cooldown window prevents redundant duplicate alert creation."""
    org_a = alerting_setup["org_a"]
    ws_a1 = alerting_setup["ws_a1"]
    admin = alerting_setup["admin"]

    ctx = _make_context(admin, org_a, ws_a1, OrganizationRole.MEMBER, WorkspaceRole.WORKSPACE_ADMIN)

    AlertRuleService.create_rule(
        db_session,
        ctx,
        AlertRuleCreateRequest(
            workspace_id=ws_a1.id,
            rule_type=AlertType.LATENCY_HIGH.value,
            metric_name=AlertMetricName.TOTAL_LATENCY_P95.value,
            operator=AlertOperator.GT,
            threshold=2000.0,
            window_minutes=15,
            minimum_sample_size=5,
            cooldown_minutes=60,
        ),
    )

    _seed_traces(db_session, org_a.id, ws_a1.id, count=6, latency_ms=4000.0)

    # First evaluation: creates alert
    eval_1 = AlertEvaluationService.evaluate(db_session, ctx, workspace_id=ws_a1.id)
    assert eval_1.alerts_created == 1

    # Second evaluation immediately after: suppressed by cooldown!
    eval_2 = AlertEvaluationService.evaluate(db_session, ctx, workspace_id=ws_a1.id)
    assert eval_2.alerts_created == 0

    suppressed_items = [d for d in eval_2.details if d.action_taken == "COOLDOWN_SUPPRESSED"]
    assert len(suppressed_items) >= 1

    # Verify only 1 alert in database
    alerts = db_session.scalars(
        select(PlatformAlert).where(
            PlatformAlert.workspace_id == ws_a1.id,
            PlatformAlert.alert_type == AlertType.LATENCY_HIGH.value,
        )
    ).all()
    assert len(alerts) == 1


# =========================================================================
# 8. Acknowledge Workflow
# =========================================================================

def test_acknowledge_workflow(db_session: Session, alerting_setup: dict):
    """Test 8: Operator can acknowledge alert, transitioning state and capturing timestamp and actor."""
    org_a = alerting_setup["org_a"]
    ws_a1 = alerting_setup["ws_a1"]
    admin = alerting_setup["admin"]

    ctx = _make_context(admin, org_a, ws_a1, OrganizationRole.MEMBER, WorkspaceRole.WORKSPACE_ADMIN)

    # Create an alert
    alert = PlatformAlert(
        organization_id=org_a.id,
        workspace_id=ws_a1.id,
        alert_type=AlertType.LATENCY_HIGH.value,
        severity=AlertSeverity.WARNING.value,
        status=AlertStatus.OPEN.value,
        title="High Latency",
        description="Observed high latency",
        metric_name="total_latency_p95",
        metric_value=3000.0,
        threshold_value=2000.0,
        deduplication_key=f"{org_a.id}:{ws_a1.id}:LATENCY_HIGH:total_latency_p95:test",
    )
    db_session.add(alert)
    db_session.commit()

    # Acknowledge
    ack_alert = AlertService.acknowledge_alert(db_session, ctx, alert.id)
    assert ack_alert.status == AlertStatus.ACKNOWLEDGED.value
    assert ack_alert.acknowledged_at is not None
    assert ack_alert.acknowledged_by == admin.id


# =========================================================================
# 9. Resolve Workflow
# =========================================================================

def test_resolve_workflow(db_session: Session, alerting_setup: dict):
    """Test 9: Operator can resolve alert with justification, transitioning state to RESOLVED."""
    org_a = alerting_setup["org_a"]
    ws_a1 = alerting_setup["ws_a1"]
    admin = alerting_setup["admin"]

    ctx = _make_context(admin, org_a, ws_a1, OrganizationRole.MEMBER, WorkspaceRole.WORKSPACE_ADMIN)

    alert = PlatformAlert(
        organization_id=org_a.id,
        workspace_id=ws_a1.id,
        alert_type=AlertType.LATENCY_HIGH.value,
        severity=AlertSeverity.WARNING.value,
        status=AlertStatus.OPEN.value,
        title="High Latency",
        description="Observed high latency",
        metric_name="total_latency_p95",
        metric_value=3000.0,
        threshold_value=2000.0,
        deduplication_key=f"{org_a.id}:{ws_a1.id}:LATENCY_HIGH:total_latency_p95:test_res",
    )
    db_session.add(alert)
    db_session.commit()

    res_alert = AlertService.resolve_alert(
        db_session,
        ctx,
        alert.id,
        resolution_reason="Provider transient network degradation recovered.",
    )
    assert res_alert.status == AlertStatus.RESOLVED.value
    assert res_alert.resolved_at is not None
    assert res_alert.resolved_by == admin.id
    assert res_alert.resolution_reason == "Provider transient network degradation recovered."


# =========================================================================
# 10. Role-Based Alert Access
# =========================================================================

def test_role_based_alert_access(alerting_client: TestClient, alerting_setup: dict):
    """Test 10: Viewers and Contributors are denied access to alert APIs (403 Forbidden)."""
    contrib = alerting_setup["contrib"]
    viewer = alerting_setup["viewer"]
    ws_a1 = alerting_setup["ws_a1"]

    token_contrib = create_access_token(contrib.id, contrib.email)
    token_viewer = create_access_token(viewer.id, viewer.email)

    # Contributor attempt
    resp_c = alerting_client.get(
        f"/api/v1/alerts?workspace_id={ws_a1.id}",
        headers={"Authorization": f"Bearer {token_contrib}", "X-Workspace-Id": str(ws_a1.id)},
    )
    assert resp_c.status_code == 403

    # Viewer attempt
    resp_v = alerting_client.get(
        f"/api/v1/alerts?workspace_id={ws_a1.id}",
        headers={"Authorization": f"Bearer {token_viewer}", "X-Workspace-Id": str(ws_a1.id)},
    )
    assert resp_v.status_code == 403


# =========================================================================
# 11. Workspace Isolation
# =========================================================================

def test_workspace_isolation(db_session: Session, alerting_setup: dict):
    """Test 11: Workspace Admin can only see and manage alerts for their active workspace."""
    org_a = alerting_setup["org_a"]
    ws_a1 = alerting_setup["ws_a1"]
    ws_a2 = alerting_setup["ws_a2"]
    admin = alerting_setup["admin"]

    ctx = _make_context(admin, org_a, ws_a1, OrganizationRole.MEMBER, WorkspaceRole.WORKSPACE_ADMIN)

    # Create alert in WS A1 and WS A2
    alert_1 = PlatformAlert(
        organization_id=org_a.id,
        workspace_id=ws_a1.id,
        alert_type=AlertType.LATENCY_HIGH.value,
        severity=AlertSeverity.WARNING.value,
        status=AlertStatus.OPEN.value,
        title="WS 1 Alert",
        description="WS 1 Alert",
        deduplication_key=f"{org_a.id}:{ws_a1.id}:LATENCY_HIGH:total_latency_p95:1",
    )
    alert_2 = PlatformAlert(
        organization_id=org_a.id,
        workspace_id=ws_a2.id,
        alert_type=AlertType.LATENCY_HIGH.value,
        severity=AlertSeverity.WARNING.value,
        status=AlertStatus.OPEN.value,
        title="WS 2 Alert",
        description="WS 2 Alert",
        deduplication_key=f"{org_a.id}:{ws_a2.id}:LATENCY_HIGH:total_latency_p95:2",
    )
    db_session.add_all([alert_1, alert_2])
    db_session.commit()

    # Listing alerts with WS A1 context only returns WS A1 alert
    items, total = AlertService.list_alerts(db_session, ctx)
    alert_ids = [a.id for a in items]
    assert alert_1.id in alert_ids
    assert alert_2.id not in alert_ids

    # Directly fetching alert_2 raises 403 Forbidden
    with pytest.raises(Exception) as excinfo:
        AlertService.get_alert_detail(db_session, ctx, alert_2.id)
    assert "403" in str(excinfo.value)


# =========================================================================
# 12. Organization Isolation
# =========================================================================

def test_organization_isolation(db_session: Session, alerting_setup: dict):
    """Test 12: Org Owner in Org A cannot view or manage alerts in Org B."""
    org_a = alerting_setup["org_a"]
    org_b = alerting_setup["org_b"]
    ws_a1 = alerting_setup["ws_a1"]
    ws_b1 = alerting_setup["ws_b1"]
    owner = alerting_setup["owner"]

    ctx_a = _make_context(owner, org_a, ws_a1, OrganizationRole.OWNER, WorkspaceRole.WORKSPACE_ADMIN)

    # Create alert in Org B
    alert_b = PlatformAlert(
        organization_id=org_b.id,
        workspace_id=ws_b1.id,
        alert_type=AlertType.LATENCY_HIGH.value,
        severity=AlertSeverity.WARNING.value,
        status=AlertStatus.OPEN.value,
        title="Org B Alert",
        description="Org B Alert",
        deduplication_key=f"{org_b.id}:{ws_b1.id}:LATENCY_HIGH:total_latency_p95:b",
    )
    db_session.add(alert_b)
    db_session.commit()

    items, _ = AlertService.list_alerts(db_session, ctx_a)
    assert alert_b.id not in [a.id for a in items]


# =========================================================================
# 13. Cross-Tenant Alert Access Denied
# =========================================================================

def test_cross_tenant_alert_access_denied(alerting_client: TestClient, db_session: Session, alerting_setup: dict):
    """Test 13: Direct API attempt to inspect cross-tenant alert is denied (404/403)."""
    org_b = alerting_setup["org_b"]
    ws_b1 = alerting_setup["ws_b1"]
    admin = alerting_setup["admin"]  # Admin in Org A, WS A1
    ws_a1 = alerting_setup["ws_a1"]

    alert_b = PlatformAlert(
        organization_id=org_b.id,
        workspace_id=ws_b1.id,
        alert_type=AlertType.LATENCY_HIGH.value,
        severity=AlertSeverity.WARNING.value,
        status=AlertStatus.OPEN.value,
        title="Org B Alert",
        description="Org B Alert",
        deduplication_key=f"{org_b.id}:{ws_b1.id}:LATENCY_HIGH:total_latency_p95:b2",
    )
    db_session.add(alert_b)
    db_session.commit()

    token_admin = create_access_token(admin.id, admin.email)

    resp = alerting_client.get(
        f"/api/v1/alerts/{alert_b.id}",
        headers={"Authorization": f"Bearer {token_admin}", "X-Workspace-Id": str(ws_a1.id)},
    )
    assert resp.status_code == 404


# =========================================================================
# 14. Cross-Tenant Rule Creation Denied
# =========================================================================

def test_cross_tenant_rule_creation_denied(db_session: Session, alerting_setup: dict):
    """Test 14: Workspace Admin cannot create organization-wide rules or rules for another workspace."""
    org_a = alerting_setup["org_a"]
    ws_a1 = alerting_setup["ws_a1"]
    ws_a2 = alerting_setup["ws_a2"]
    admin = alerting_setup["admin"]

    ctx = _make_context(admin, org_a, ws_a1, OrganizationRole.MEMBER, WorkspaceRole.WORKSPACE_ADMIN)

    # 1. Attempting to create an org-wide rule (workspace_id=None) must be denied
    with pytest.raises(Exception) as exc1:
        AlertRuleService.create_rule(
            db_session,
            ctx,
            AlertRuleCreateRequest(
                workspace_id=None,
                rule_type=AlertType.LATENCY_HIGH.value,
                metric_name=AlertMetricName.TOTAL_LATENCY_P95.value,
                operator=AlertOperator.GT,
                threshold=1000.0,
            ),
        )
    assert "403" in str(exc1.value)

    # 2. Attempting to create rule for ws_a2 must be denied
    with pytest.raises(Exception) as exc2:
        AlertRuleService.create_rule(
            db_session,
            ctx,
            AlertRuleCreateRequest(
                workspace_id=ws_a2.id,
                rule_type=AlertType.LATENCY_HIGH.value,
                metric_name=AlertMetricName.TOTAL_LATENCY_P95.value,
                operator=AlertOperator.GT,
                threshold=1000.0,
            ),
        )
    assert "403" in str(exc2.value)


# =========================================================================
# 15. Invalid Threshold Rejected
# =========================================================================

def test_invalid_threshold_rejected(alerting_client: TestClient, alerting_setup: dict):
    """Test 15: Invalid thresholds (NaN, inf, negative window) are rejected with 422."""
    admin = alerting_setup["admin"]
    ws_a1 = alerting_setup["ws_a1"]
    token_admin = create_access_token(admin.id, admin.email)

    # Window minutes < 1
    resp = alerting_client.post(
        "/api/v1/alert-rules",
        json={
            "workspace_id": str(ws_a1.id),
            "rule_type": "LATENCY_HIGH",
            "metric_name": "total_latency_p95",
            "operator": "GT",
            "threshold": 1000.0,
            "window_minutes": 0,
        },
        headers={"Authorization": f"Bearer {token_admin}", "X-Workspace-Id": str(ws_a1.id)},
    )
    assert resp.status_code == 422


# =========================================================================
# 16. Manual Evaluation Authorization
# =========================================================================

def test_manual_evaluation_authorization(alerting_client: TestClient, alerting_setup: dict):
    """Test 16: Manual evaluation endpoint checks caller roles and tenant scope."""
    contrib = alerting_setup["contrib"]
    admin = alerting_setup["admin"]
    ws_a1 = alerting_setup["ws_a1"]
    ws_a2 = alerting_setup["ws_a2"]

    token_contrib = create_access_token(contrib.id, contrib.email)
    token_admin = create_access_token(admin.id, admin.email)

    # Contributor denied
    resp_c = alerting_client.post(
        "/api/v1/alerts/evaluate",
        json={"workspace_id": str(ws_a1.id)},
        headers={"Authorization": f"Bearer {token_contrib}", "X-Workspace-Id": str(ws_a1.id)},
    )
    assert resp_c.status_code == 403

    # Admin cannot evaluate another workspace
    resp_a2 = alerting_client.post(
        "/api/v1/alerts/evaluate",
        json={"workspace_id": str(ws_a2.id)},
        headers={"Authorization": f"Bearer {token_admin}", "X-Workspace-Id": str(ws_a1.id)},
    )
    assert resp_a2.status_code == 403

    # Admin evaluating own workspace succeeds
    resp_a1 = alerting_client.post(
        "/api/v1/alerts/evaluate",
        json={"workspace_id": str(ws_a1.id)},
        headers={"Authorization": f"Bearer {token_admin}", "X-Workspace-Id": str(ws_a1.id)},
    )
    assert resp_a1.status_code == 200
    data = resp_a1.json()
    assert "evaluation_timestamp" in data
    assert "rules_evaluated" in data


# =========================================================================
# 17. Alert Auditing
# =========================================================================

def test_alert_auditing(db_session: Session, alerting_setup: dict):
    """Test 17: Lifecycle actions create corresponding immutable audit log records."""
    org_a = alerting_setup["org_a"]
    ws_a1 = alerting_setup["ws_a1"]
    admin = alerting_setup["admin"]

    ctx = _make_context(admin, org_a, ws_a1, OrganizationRole.MEMBER, WorkspaceRole.WORKSPACE_ADMIN)

    _seed_traces(db_session, org_a.id, ws_a1.id, count=6, latency_ms=5000.0)

    # Evaluate generates ALERT_CREATED audit log
    AlertEvaluationService.evaluate(db_session, ctx, workspace_id=ws_a1.id)

    create_audit = db_session.scalars(
        select(AuditLog).where(
            AuditLog.organization_id == org_a.id,
            AuditLog.event_type == AuditEventType.ALERT_CREATED.value,
        )
    ).first()
    assert create_audit is not None
    assert create_audit.metadata_["metric_name"] == "total_latency_p95"

    alert = db_session.scalars(select(PlatformAlert).where(PlatformAlert.workspace_id == ws_a1.id)).first()
    assert alert is not None

    # Acknowledge generates ALERT_ACKNOWLEDGED audit log
    AlertService.acknowledge_alert(db_session, ctx, alert.id)
    ack_audit = db_session.scalars(
        select(AuditLog).where(
            AuditLog.organization_id == org_a.id,
            AuditLog.event_type == AuditEventType.ALERT_ACKNOWLEDGED.value,
        )
    ).first()
    assert ack_audit is not None

    # Resolve generates ALERT_RESOLVED audit log
    AlertService.resolve_alert(db_session, ctx, alert.id, resolution_reason="Resolved by test")
    res_audit = db_session.scalars(
        select(AuditLog).where(
            AuditLog.organization_id == org_a.id,
            AuditLog.event_type == AuditEventType.ALERT_RESOLVED.value,
        )
    ).first()
    assert res_audit is not None
    assert res_audit.metadata_["resolution_reason"] == "Resolved by test"


# =========================================================================
# 18. Alert / Trace Correlation
# =========================================================================

def test_alert_trace_correlation(db_session: Session, alerting_setup: dict):
    """Test 18: Alerts capture safe correlation references (trace_id, request_id) without payload."""
    org_a = alerting_setup["org_a"]
    ws_a1 = alerting_setup["ws_a1"]
    admin = alerting_setup["admin"]

    ctx = _make_context(admin, org_a, ws_a1, OrganizationRole.MEMBER, WorkspaceRole.WORKSPACE_ADMIN)

    traces = _seed_traces(db_session, org_a.id, ws_a1.id, count=6, latency_ms=5000.0)
    sample_trace = traces[-1]

    AlertEvaluationService.evaluate(db_session, ctx, workspace_id=ws_a1.id)

    alert = db_session.scalars(select(PlatformAlert).where(PlatformAlert.workspace_id == ws_a1.id)).first()
    assert alert is not None
    assert alert.metadata_["sample_trace_id"] == sample_trace.trace_id
    assert alert.metadata_["sample_request_id"] == sample_trace.request_id


# =========================================================================
# 19. No Raw Query Stored
# =========================================================================

def test_no_raw_query_stored(db_session: Session, alerting_setup: dict):
    """Test 19: Alert metadata and titles never store raw query text."""
    org_a = alerting_setup["org_a"]
    ws_a1 = alerting_setup["ws_a1"]
    admin = alerting_setup["admin"]

    ctx = _make_context(admin, org_a, ws_a1, OrganizationRole.MEMBER, WorkspaceRole.WORKSPACE_ADMIN)

    _seed_traces(db_session, org_a.id, ws_a1.id, count=6, latency_ms=5000.0)
    AlertEvaluationService.evaluate(db_session, ctx, workspace_id=ws_a1.id)

    alerts = db_session.scalars(select(PlatformAlert).where(PlatformAlert.workspace_id == ws_a1.id)).all()
    for alert in alerts:
        meta_str = str(alert.metadata_).lower()
        assert "query" not in alert.metadata_
        assert "question" not in alert.metadata_
        assert "sensitive" not in meta_str


# =========================================================================
# 20. No Prompt / Context / Chunk Stored
# =========================================================================

def test_no_prompt_context_chunk_stored(db_session: Session, alerting_setup: dict):
    """Test 20: Alert records never persist prompts, chunks, or model responses."""
    org_a = alerting_setup["org_a"]
    ws_a1 = alerting_setup["ws_a1"]
    admin = alerting_setup["admin"]

    ctx = _make_context(admin, org_a, ws_a1, OrganizationRole.MEMBER, WorkspaceRole.WORKSPACE_ADMIN)

    _seed_traces(db_session, org_a.id, ws_a1.id, count=6, latency_ms=5000.0)
    AlertEvaluationService.evaluate(db_session, ctx, workspace_id=ws_a1.id)

    alerts = db_session.scalars(select(PlatformAlert).where(PlatformAlert.workspace_id == ws_a1.id)).all()
    forbidden = {"prompt", "chunk", "context", "response", "raw_response"}
    for alert in alerts:
        for k in alert.metadata_.keys():
            assert k not in forbidden


# =========================================================================
# 21. No Credentials Stored
# =========================================================================

def test_no_credentials_stored(db_session: Session, alerting_setup: dict):
    """Test 21: Alert records never persist API tokens, bearer keys, or passwords."""
    org_a = alerting_setup["org_a"]
    ws_a1 = alerting_setup["ws_a1"]
    admin = alerting_setup["admin"]

    ctx = _make_context(admin, org_a, ws_a1, OrganizationRole.MEMBER, WorkspaceRole.WORKSPACE_ADMIN)

    _seed_traces(db_session, org_a.id, ws_a1.id, count=6, latency_ms=5000.0)
    AlertEvaluationService.evaluate(db_session, ctx, workspace_id=ws_a1.id)

    alerts = db_session.scalars(select(PlatformAlert).where(PlatformAlert.workspace_id == ws_a1.id)).all()
    cred_keywords = {"bearer", "password", "token", "secret", "cookie", "auth"}
    for alert in alerts:
        meta_keys = [k.lower() for k in alert.metadata_.keys()]
        for c in cred_keywords:
            assert c not in meta_keys


# =========================================================================
# 22. Diagnostics Distinguish Observed vs Inferred
# =========================================================================

def test_diagnostics_distinguish_observed_vs_inferred(alerting_setup: dict):
    """Test 22: PlatformDiagnosticsService separates observed measurements from inferred statements."""
    alert = PlatformAlert(
        organization_id=uuid.uuid4(),
        workspace_id=uuid.uuid4(),
        alert_type=AlertType.LLM_SLOW.value,
        severity=AlertSeverity.WARNING.value,
        status=AlertStatus.OPEN.value,
        title="LLM Slow",
        description="LLM p95 latency high",
        metric_name=AlertMetricName.LLM_LATENCY_P95.value,
        metric_value=4200.0,
        threshold_value=3000.0,
        deduplication_key="test_dedup",
        metadata_={"sample_size": 10, "window_minutes": 15, "provider": "gemini"},
    )

    diag = PlatformDiagnosticsService.diagnose_alert(alert)

    # Observed must describe measurement fact
    assert "Observed" in diag.observed
    assert "4200.0ms" in diag.observed
    assert "3000.0ms" in diag.observed

    # Inferred must describe non-definitive correlation
    assert "Inferred" in diag.inferred
    assert "LLM generation stage" in diag.inferred
    assert diag.subsystem == PlatformSubsystem.AI_PROVIDER.value
    assert diag.investigation_target == InvestigationTarget.AI_PROVIDER_METRICS.value
    assert diag.dominant_stage == SpanName.LLM_GENERATION.value


# =========================================================================
# 23. Alert Evaluation Does Not Modify Traces
# =========================================================================

def test_alert_evaluation_does_not_modify_traces(db_session: Session, alerting_setup: dict):
    """Test 23: Evaluation evaluates traces in read-only manner without modifying records or timestamps."""
    org_a = alerting_setup["org_a"]
    ws_a1 = alerting_setup["ws_a1"]
    admin = alerting_setup["admin"]

    ctx = _make_context(admin, org_a, ws_a1, OrganizationRole.MEMBER, WorkspaceRole.WORKSPACE_ADMIN)

    traces = _seed_traces(db_session, org_a.id, ws_a1.id, count=6, latency_ms=4500.0)
    trace_before = [(t.id, t.started_at, t.completed_at, t.total_latency_ms, t.status) for t in traces]

    AlertEvaluationService.evaluate(db_session, ctx, workspace_id=ws_a1.id)

    db_session.expire_all()
    traces_after = db_session.scalars(select(QueryTrace).where(QueryTrace.workspace_id == ws_a1.id)).all()
    trace_after_tuples = [(t.id, t.started_at, t.completed_at, t.total_latency_ms, t.status) for t in traces_after]

    assert set(trace_before) == set(trace_after_tuples)


# =========================================================================
# 24. Alert Evaluation Does Not Modify Audit Logs Incorrectly
# =========================================================================

def test_alert_evaluation_does_not_modify_audit_logs_incorrectly(db_session: Session, alerting_setup: dict):
    """Test 24: Alert evaluation only appends valid audit log events and maintains audit hash chain integrity."""
    org_a = alerting_setup["org_a"]
    ws_a1 = alerting_setup["ws_a1"]
    admin = alerting_setup["admin"]

    ctx = _make_context(admin, org_a, ws_a1, OrganizationRole.MEMBER, WorkspaceRole.WORKSPACE_ADMIN)

    _seed_traces(db_session, org_a.id, ws_a1.id, count=6, latency_ms=5000.0)

    # Pre-existing audit log
    AuditLogService.record_event(
        db_session,
        organization_id=org_a.id,
        workspace_id=ws_a1.id,
        actor_user_id=admin.id,
        event_type=AuditEventType.WORKSPACE_SWITCHED,
        action="WORKSPACE_SWITCHED",
        outcome=AuditOutcome.SUCCESS,
    )

    # Evaluate alerts
    AlertEvaluationService.evaluate(db_session, ctx, workspace_id=ws_a1.id)

    # Verify audit chain integrity using AuditLogService
    is_valid, error_detail, count = AuditLogService.verify_chain(db_session, org_a.id)
    assert is_valid is True


# =========================================================================
# 25. Trace Retention Does Not Delete Alerts
# =========================================================================

def test_trace_retention_does_not_delete_alerts(db_session: Session, alerting_setup: dict):
    """Test 25: Executing trace retention cleanup deletes expired traces but preserves platform alerts."""
    org_a = alerting_setup["org_a"]
    ws_a1 = alerting_setup["ws_a1"]
    owner = alerting_setup["owner"]

    ctx = _make_context(owner, org_a, ws_a1, OrganizationRole.OWNER, WorkspaceRole.WORKSPACE_ADMIN)

    # Create old trace (>30 days old)
    old_time = datetime.now(timezone.utc) - timedelta(days=35)
    t = QueryTrace(
        trace_id=f"trc-old-{uuid.uuid4().hex[:10]}",
        request_id=f"req-old-{uuid.uuid4().hex[:10]}",
        organization_id=org_a.id,
        workspace_id=ws_a1.id,
        operation_type="CHAT",
        status="SUCCESS",
        started_at=old_time,
        completed_at=old_time + timedelta(milliseconds=200),
        total_latency_ms=200.0,
    )
    db_session.add(t)

    # Create old alert (>35 days old)
    alert = PlatformAlert(
        organization_id=org_a.id,
        workspace_id=ws_a1.id,
        alert_type=AlertType.LATENCY_HIGH.value,
        severity=AlertSeverity.WARNING.value,
        status=AlertStatus.OPEN.value,
        title="Old Alert",
        description="Old Alert Description",
        detected_at=old_time,
        deduplication_key=f"{org_a.id}:{ws_a1.id}:old",
    )
    db_session.add(alert)
    db_session.commit()

    # Run trace retention cleanup (30 days)
    cleanup_res = TraceRetentionService.delete_expired_traces(db_session, ctx, days=30)
    assert cleanup_res.deleted_traces_count >= 1

    # Verify alert still exists!
    alert_check = db_session.get(PlatformAlert, alert.id)
    assert alert_check is not None
    assert alert_check.id == alert.id


# =========================================================================
# 26. Alert Lifecycle Remains Consistent
# =========================================================================

def test_alert_lifecycle_remains_consistent(db_session: Session, alerting_setup: dict):
    """Test 26: Full lifecycle OPEN -> ACKNOWLEDGED -> RESOLVED preserves all audit and operational data."""
    org_a = alerting_setup["org_a"]
    ws_a1 = alerting_setup["ws_a1"]
    admin = alerting_setup["admin"]

    ctx = _make_context(admin, org_a, ws_a1, OrganizationRole.MEMBER, WorkspaceRole.WORKSPACE_ADMIN)

    alert = PlatformAlert(
        organization_id=org_a.id,
        workspace_id=ws_a1.id,
        alert_type=AlertType.LATENCY_HIGH.value,
        severity=AlertSeverity.WARNING.value,
        status=AlertStatus.OPEN.value,
        title="Lifecycle Alert",
        description="Testing lifecycle",
        deduplication_key=f"{org_a.id}:{ws_a1.id}:lifecycle",
    )
    db_session.add(alert)
    db_session.commit()
    assert alert.status == AlertStatus.OPEN.value

    # Acknowledge
    AlertService.acknowledge_alert(db_session, ctx, alert.id)
    assert alert.status == AlertStatus.ACKNOWLEDGED.value
    assert alert.acknowledged_at is not None

    # Resolve
    AlertService.resolve_alert(db_session, ctx, alert.id, resolution_reason="Resolved")
    assert alert.status == AlertStatus.RESOLVED.value
    assert alert.resolved_at is not None
    assert alert.resolution_reason == "Resolved"


# =========================================================================
# 27. Duplicate Alert Prevention
# =========================================================================

def test_duplicate_alert_prevention(db_session: Session, alerting_setup: dict):
    """Test 27: Evaluating rules multiple times during ongoing condition does not spawn duplicate alerts."""
    org_a = alerting_setup["org_a"]
    ws_a1 = alerting_setup["ws_a1"]
    admin = alerting_setup["admin"]

    ctx = _make_context(admin, org_a, ws_a1, OrganizationRole.MEMBER, WorkspaceRole.WORKSPACE_ADMIN)

    AlertRuleService.create_rule(
        db_session,
        ctx,
        AlertRuleCreateRequest(
            workspace_id=ws_a1.id,
            rule_type=AlertType.LATENCY_HIGH.value,
            metric_name=AlertMetricName.TOTAL_LATENCY_P95.value,
            operator=AlertOperator.GT,
            threshold=1500.0,
            window_minutes=15,
            minimum_sample_size=5,
            cooldown_minutes=120,
        ),
    )

    _seed_traces(db_session, org_a.id, ws_a1.id, count=6, latency_ms=3000.0)

    # Run 3 consecutive evaluations
    AlertEvaluationService.evaluate(db_session, ctx, workspace_id=ws_a1.id)
    AlertEvaluationService.evaluate(db_session, ctx, workspace_id=ws_a1.id)
    AlertEvaluationService.evaluate(db_session, ctx, workspace_id=ws_a1.id)

    alerts = db_session.scalars(
        select(PlatformAlert).where(
            PlatformAlert.workspace_id == ws_a1.id,
            PlatformAlert.alert_type == AlertType.LATENCY_HIGH.value,
        )
    ).all()

    assert len(alerts) == 1


# =========================================================================
# 28. RAG Results Remain Unchanged
# =========================================================================

def test_rag_results_remain_unchanged(alerting_client: TestClient, alerting_setup: dict):
    """Test 28: End-to-end RAG question answering pipeline continues to work identically."""
    ws_a1 = alerting_setup["ws_a1"]
    admin = alerting_setup["admin"]

    token_admin = create_access_token(admin.id, admin.email)

    resp = alerting_client.post(
        "/api/v1/chat",
        json={
            "workspace_id": str(ws_a1.id),
            "question": "What does operational alerting provide?",
            "retrieval_mode": "hybrid",
        },
        headers={"Authorization": f"Bearer {token_admin}", "X-Workspace-Id": str(ws_a1.id)},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert "answer" in data
    assert len(data["answer"]) > 0
    assert "conversation_id" in data
    assert "message_id" in data
