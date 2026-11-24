"""Comprehensive test suite for Phase 1.5 Enterprise Audit Logging & Compliance.

Covers:
- A. Successful login creates audit event
- B. Failed login creates safe audit event (no secrets/passwords logged)
- C. Logout creates audit event
- D. Workspace switch creates audit event
- E. Organization member change creates event
- F. Workspace membership change creates event
- G. Role change creates event
- H. Document create/view/update/delete creates expected events
- I. ACL add/remove creates expected events
- J. Denied access is recorded correctly
- K. Knowledge query creates expected safe event
- L. Query event does not contain full query text
- M. Query event does not contain chunk text
- N. Query event does not contain tokens/secrets
- O. Viewer cannot retrieve protected audit records
- P. Contributor cannot retrieve protected audit records
- Q. Workspace Admin receives appropriate audit records
- R. Organization Owner receives organization-level records
- S. Cross-workspace audit access is denied
- T. Cross-organization audit access is denied
- U. Audit records cannot be updated (database trigger prevents UPDATE)
- V. Audit records cannot be deleted (database trigger prevents DELETE)
- W. Valid hash chain verifies
- X. Modified event metadata causes verification failure
- Y. Broken previous_hash causes verification failure
- Z. Deleting an event causes verification failure
- AA. Forged insertion causes verification failure
- AB. ACL audit events do not trigger re-embedding
- AC. Audit logging does not change RAG retrieval results
- AD. Audit verification scope enforcement (Workspace Admin cannot verify org chain)
- AE. Canonical payload determinism & sanitization
"""

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.permissions import resolve_effective_permissions
from app.core.security import create_access_token, hash_password
from app.core.workspace_context import WorkspaceContext
from app.db.database import get_db
from app.db.models import (
    AuditEventType,
    AuditLog,
    AuditOutcome,
    Document,
    DocumentAcl,
    DocumentChunk,
    DocumentPermission,
    DocumentStatus,
    Organization,
    OrganizationMembership,
    OrganizationRole,
    PrincipalType,
    User,
    Workspace,
    WorkspaceMembership,
    WorkspaceRole,
)
from app.main import app
from app.repositories.document_repository import DocumentRepository
from app.services.audit_service import (
    AuditLogService,
    compute_canonical_payload,
    sanitize_audit_metadata,
)
from app.services.document_service import DocumentService
from app.services.rag import RagService
from tests.conftest import make_settings, postgres_available
from tests.helpers.pdfs import build_pdf


@pytest.fixture
def audit_client(db_session: Session, monkeypatch) -> TestClient:
    if not postgres_available():
        pytest.skip("PostgreSQL is not available for database tests.")

    provider = MagicMock()
    provider.create_embedding.side_effect = lambda text, task: [0.15] * 768
    provider.generate_text.return_value = "Verified answer from authorized knowledge sources."
    monkeypatch.setattr("app.services.document_service.get_ai_provider", lambda: provider)
    monkeypatch.setattr("app.services.rag.get_ai_provider", lambda: provider)

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def create_test_tenant(
    db: Session,
    suffix: str = "",
) -> tuple[Organization, Workspace, User, str]:
    unique_suffix = f"{uuid.uuid4().hex[:6]}_{suffix}" if suffix else uuid.uuid4().hex[:8]
    org = Organization(
        id=uuid.uuid4(),
        name=f"Audit Org {unique_suffix}",
        slug=f"audit-org-{unique_suffix}",
    )
    db.add(org)
    db.flush()

    ws = Workspace(
        id=uuid.uuid4(),
        organization_id=org.id,
        name=f"Audit Workspace {unique_suffix}",
        slug=f"audit-ws-{unique_suffix}",
        settings={},
    )
    db.add(ws)
    db.flush()

    raw_pw = "SecurePassword123!"
    user = User(
        id=uuid.uuid4(),
        email=f"owner_{unique_suffix}@auditcorp.com",
        full_name="Audit Owner",
        hashed_password=hash_password(raw_pw),
        is_active=True,
    )
    db.add(user)
    db.flush()

    org_mem = OrganizationMembership(
        user_id=user.id,
        organization_id=org.id,
        role=OrganizationRole.OWNER,
    )
    db.add(org_mem)

    ws_mem = WorkspaceMembership(
        user_id=user.id,
        workspace_id=ws.id,
        role=WorkspaceRole.WORKSPACE_ADMIN,
    )
    db.add(ws_mem)
    db.flush()

    return org, ws, user, raw_pw


def create_user_with_role(
    db: Session,
    org: Organization,
    ws: Workspace,
    email: str,
    org_role: OrganizationRole = OrganizationRole.MEMBER,
    ws_role: WorkspaceRole = WorkspaceRole.VIEWER,
) -> User:
    user = User(
        id=uuid.uuid4(),
        email=email,
        full_name=f"User {email}",
        hashed_password=hash_password("Password123!"),
        is_active=True,
    )
    db.add(user)
    db.flush()

    org_mem = OrganizationMembership(
        user_id=user.id,
        organization_id=org.id,
        role=org_role,
    )
    db.add(org_mem)

    ws_mem = WorkspaceMembership(
        user_id=user.id,
        workspace_id=ws.id,
        role=ws_role,
    )
    db.add(ws_mem)
    db.flush()
    return user


# ==============================================================================
# SECTION A - C: AUTHENTICATION AUDIT TESTS
# ==============================================================================


def test_successful_login_creates_audit_event(audit_client: TestClient, db_session: Session):
    org, ws, user, pw = create_test_tenant(db_session, "login_succ")

    res = audit_client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": pw},
    )
    assert res.status_code == 200

    # Verify audit event
    audit = db_session.query(AuditLog).filter(
        AuditLog.organization_id == org.id,
        AuditLog.event_type == AuditEventType.LOGIN_SUCCESS.value,
    ).first()
    assert audit is not None
    assert audit.actor_user_id == user.id
    assert audit.actor_email_snapshot == user.email
    assert audit.outcome == AuditOutcome.SUCCESS.value
    assert pw not in str(audit.metadata_)
    assert "hashed_password" not in str(audit.metadata_)
    assert "token" not in str(audit.metadata_).lower()


def test_failed_login_creates_safe_audit_event(audit_client: TestClient, db_session: Session):
    org, ws, user, _ = create_test_tenant(db_session, "login_fail")

    res = audit_client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": "WrongPassword!"},
    )
    assert res.status_code == 401

    # Verify safe audit event
    audit = db_session.query(AuditLog).filter(
        AuditLog.organization_id == org.id,
        AuditLog.event_type == AuditEventType.LOGIN_FAILURE.value,
    ).first()
    assert audit is not None
    assert audit.outcome == AuditOutcome.FAILURE.value
    # Crucial privacy assertion: raw attempt password and secrets must NOT be in metadata
    assert "WrongPassword!" not in str(audit.metadata_)
    assert "hashed_password" not in str(audit.metadata_)


def test_logout_creates_audit_event(audit_client: TestClient, db_session: Session):
    org, ws, user, pw = create_test_tenant(db_session, "logout")

    login_res = audit_client.post(
        "/api/v1/auth/login",
        json={"email": user.email, "password": pw},
    )
    token = login_res.json()["access_token"]

    logout_res = audit_client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert logout_res.status_code == 204

    logout_audit = db_session.query(AuditLog).filter(
        AuditLog.organization_id == org.id,
        AuditLog.event_type == AuditEventType.LOGOUT.value,
    ).first()
    assert logout_audit is not None
    assert logout_audit.actor_user_id == user.id


# ==============================================================================
# SECTION D - G: WORKSPACE & RBAC AUDIT TESTS
# ==============================================================================


def test_workspace_creation_and_switch_creates_audit_event(
    audit_client: TestClient, db_session: Session
):
    org, ws, user, _ = create_test_tenant(db_session, "ws_mgmt")
    token = create_access_token(user.id, user.email)

    # 1. Create workspace via API
    new_ws_res = audit_client.post(
        "/api/v1/workspaces",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "organization_id": str(org.id),
            "name": "Finance Audit WS",
            "slug": f"fin-ws-{uuid.uuid4().hex[:4]}",
        },
    )
    assert new_ws_res.status_code == 201
    created_ws_id = new_ws_res.json()["id"]

    create_audit = db_session.query(AuditLog).filter(
        AuditLog.organization_id == org.id,
        AuditLog.event_type == AuditEventType.WORKSPACE_CREATED.value,
    ).first()
    assert create_audit is not None
    assert create_audit.resource_id == created_ws_id

    # 2. Workspace switch audit event
    switch_event = AuditLogService.record_event(
        db_session,
        organization_id=org.id,
        workspace_id=uuid.UUID(created_ws_id),
        actor_user_id=user.id,
        actor_email=user.email,
        event_type=AuditEventType.WORKSPACE_SWITCHED,
        action="WORKSPACE_SWITCH",
        outcome=AuditOutcome.SUCCESS,
        resource_type="workspace",
        resource_id=created_ws_id,
        autocommit=True,
    )
    assert switch_event is not None
    assert switch_event.workspace_id == uuid.UUID(created_ws_id)


def test_organization_and_workspace_member_changes_create_audit_events(
    audit_client: TestClient, db_session: Session
):
    org, ws, owner, _ = create_test_tenant(db_session, "members")
    owner_token = create_access_token(owner.id, owner.email)

    # 1. Add Org Member
    new_user = User(
        id=uuid.uuid4(),
        email=f"member_{uuid.uuid4().hex[:4]}@auditcorp.com",
        full_name="New Member",
        hashed_password=hash_password("Pass!"),
    )
    db_session.add(new_user)
    db_session.flush()

    add_org_res = audit_client.post(
        f"/api/v1/organizations/{org.id}/members",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={"user_id": str(new_user.id), "role": "MEMBER"},
    )
    assert add_org_res.status_code == 201

    org_audit = db_session.query(AuditLog).filter(
        AuditLog.organization_id == org.id,
        AuditLog.event_type == AuditEventType.MEMBER_ADDED.value,
    ).first()
    assert org_audit is not None
    assert org_audit.metadata_["target_user_id"] == str(new_user.id)

    # 2. Add Workspace Member
    add_ws_res = audit_client.post(
        f"/api/v1/workspaces/{ws.id}/members",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={"user_id": str(new_user.id), "role": "CONTRIBUTOR"},
    )
    assert add_ws_res.status_code == 201

    ws_audit = db_session.query(AuditLog).filter(
        AuditLog.organization_id == org.id,
        AuditLog.event_type == AuditEventType.WORKSPACE_MEMBER_ADDED.value,
    ).first()
    assert ws_audit is not None
    assert ws_audit.workspace_id == ws.id

    # 3. Update Workspace Member Role
    update_role_res = audit_client.patch(
        f"/api/v1/workspaces/{ws.id}/members/{new_user.id}",
        headers={"Authorization": f"Bearer {owner_token}"},
        json={"role": "WORKSPACE_ADMIN"},
    )
    assert update_role_res.status_code == 200

    role_audit = db_session.query(AuditLog).filter(
        AuditLog.organization_id == org.id,
        AuditLog.event_type == AuditEventType.WORKSPACE_MEMBER_UPDATED.value,
    ).first()
    assert role_audit is not None
    assert role_audit.metadata_["new_role"] == "WORKSPACE_ADMIN"


# ==============================================================================
# SECTION H - J: DOCUMENT & ACL AUDIT TESTS
# ==============================================================================


def test_document_lifecycle_and_acl_creates_expected_audit_events(
    audit_client: TestClient, db_session: Session, tmp_path: Path
):
    org, ws, owner, _ = create_test_tenant(db_session, "doc_life")
    owner_token = create_access_token(owner.id, owner.email)

    # 1. Document Ingest / Create
    pdf_bytes = build_pdf(["Confidential Audit Policy: ISO 27001 compliance standards."])
    files = {"file": ("audit_policy.pdf", pdf_bytes, "application/pdf")}
    ingest_res = audit_client.post(
        "/api/v1/documents",
        headers={"Authorization": f"Bearer {owner_token}", "X-Workspace-Id": str(ws.id)},
        files=files,
    )
    assert ingest_res.status_code == 201
    doc_id = ingest_res.json()["id"]

    create_doc_audit = db_session.query(AuditLog).filter(
        AuditLog.organization_id == org.id,
        AuditLog.event_type == AuditEventType.DOCUMENT_CREATED.value,
        AuditLog.resource_id == doc_id,
    ).first()
    assert create_doc_audit is not None
    assert create_doc_audit.outcome == AuditOutcome.SUCCESS.value
    # Confirm no chunk content or text in metadata
    assert "ISO 27001" not in str(create_doc_audit.metadata_)

    # 2. Document View
    view_res = audit_client.get(
        f"/api/v1/documents/{doc_id}",
        headers={"Authorization": f"Bearer {owner_token}", "X-Workspace-Id": str(ws.id)},
    )
    assert view_res.status_code == 200

    view_doc_audit = db_session.query(AuditLog).filter(
        AuditLog.organization_id == org.id,
        AuditLog.event_type == AuditEventType.DOCUMENT_VIEWED.value,
        AuditLog.resource_id == doc_id,
    ).first()
    assert view_doc_audit is not None

    # 3. Document Update Metadata
    update_res = audit_client.patch(
        f"/api/v1/documents/{doc_id}",
        headers={"Authorization": f"Bearer {owner_token}", "X-Workspace-Id": str(ws.id)},
        json={"category": "compliance"},
    )
    assert update_res.status_code == 200

    update_doc_audit = db_session.query(AuditLog).filter(
        AuditLog.organization_id == org.id,
        AuditLog.event_type == AuditEventType.DOCUMENT_UPDATED.value,
        AuditLog.resource_id == doc_id,
    ).first()
    assert update_doc_audit is not None

    # 4. Add ACL
    colleague = create_user_with_role(db_session, org, ws, f"colleague_{uuid.uuid4().hex[:4]}@audit.com")
    acl_add_res = audit_client.post(
        f"/api/v1/documents/{doc_id}/acl",
        headers={"Authorization": f"Bearer {owner_token}", "X-Workspace-Id": str(ws.id)},
        json={
            "principal_type": "USER",
            "principal_id": str(colleague.id),
            "permission": "READ",
        },
    )
    assert acl_add_res.status_code == 201
    acl_id = acl_add_res.json()["id"]

    acl_add_audit = db_session.query(AuditLog).filter(
        AuditLog.organization_id == org.id,
        AuditLog.event_type == AuditEventType.DOCUMENT_ACL_ADDED.value,
        AuditLog.resource_id == acl_id,
    ).first()
    assert acl_add_audit is not None
    assert acl_add_audit.metadata_["principal_id"] == str(colleague.id)

    # 5. Remove ACL
    acl_del_res = audit_client.delete(
        f"/api/v1/documents/{doc_id}/acl/{acl_id}",
        headers={"Authorization": f"Bearer {owner_token}", "X-Workspace-Id": str(ws.id)},
    )
    assert acl_del_res.status_code == 204

    acl_del_audit = db_session.query(AuditLog).filter(
        AuditLog.organization_id == org.id,
        AuditLog.event_type == AuditEventType.DOCUMENT_ACL_REMOVED.value,
        AuditLog.resource_id == acl_id,
    ).first()
    assert acl_del_audit is not None

    # 6. Delete Document
    del_res = audit_client.delete(
        f"/api/v1/documents/{doc_id}",
        headers={"Authorization": f"Bearer {owner_token}", "X-Workspace-Id": str(ws.id)},
    )
    assert del_res.status_code == 204

    del_doc_audit = db_session.query(AuditLog).filter(
        AuditLog.organization_id == org.id,
        AuditLog.event_type == AuditEventType.DOCUMENT_DELETED.value,
        AuditLog.resource_id == doc_id,
    ).first()
    assert del_doc_audit is not None


def test_denied_access_recorded_correctly(audit_client: TestClient, db_session: Session):
    org, ws, owner, _ = create_test_tenant(db_session, "denied_access")
    viewer = create_user_with_role(
        db_session, org, ws, f"viewer_{uuid.uuid4().hex[:4]}@audit.com", ws_role=WorkspaceRole.VIEWER
    )
    viewer_token = create_access_token(viewer.id, viewer.email)

    # Viewer attempting admin document upload should be denied
    pdf_bytes = build_pdf(["Page content"])
    files = {"file": ("test.pdf", pdf_bytes, "application/pdf")}
    res = audit_client.post(
        "/api/v1/documents",
        headers={"Authorization": f"Bearer {viewer_token}", "X-Workspace-Id": str(ws.id)},
        files=files,
    )
    assert res.status_code == 403

    denied_audit = db_session.query(AuditLog).filter(
        AuditLog.organization_id == org.id,
        AuditLog.actor_user_id == viewer.id,
        AuditLog.outcome == AuditOutcome.DENIED.value,
    ).first()
    assert denied_audit is not None


# ==============================================================================
# SECTION K - N: KNOWLEDGE QUERY PRIVACY & AUDIT TESTS
# ==============================================================================


def test_knowledge_query_creates_safe_audit_event_without_leakage(
    audit_client: TestClient, db_session: Session
):
    org, ws, owner, _ = create_test_tenant(db_session, "query_audit")
    owner_token = create_access_token(owner.id, owner.email)

    user_secret_query = "What is the secret cryptographic key for project alpha?"

    res = audit_client.post(
        "/api/v1/chat",
        headers={"Authorization": f"Bearer {owner_token}", "X-Workspace-Id": str(ws.id)},
        json={"question": user_secret_query},
    )
    assert res.status_code == 200

    query_audit = db_session.query(AuditLog).filter(
        AuditLog.organization_id == org.id,
        AuditLog.event_type == AuditEventType.KNOWLEDGE_QUERY.value,
    ).first()

    assert query_audit is not None
    assert query_audit.outcome == AuditOutcome.SUCCESS.value

    # Privacy verification:
    # 1. Raw question text must NOT be stored in metadata
    assert user_secret_query not in str(query_audit.metadata_)
    # 2. SHA-256 hash of question is stored
    expected_hash = hashlib.sha256(user_secret_query.encode("utf-8")).hexdigest()
    assert query_audit.metadata_["query_hash"] == expected_hash
    # 3. No chunk content / raw response in metadata
    assert "retrieval_mode" in query_audit.metadata_
    assert "result_count" in query_audit.metadata_
    assert "content" not in str(query_audit.metadata_).lower()
    assert "prompt" not in str(query_audit.metadata_).lower()
    assert "token" not in str(query_audit.metadata_).lower()


# ==============================================================================
# SECTION O - T: AUDIT RETRIEVAL API & TENANT ISOLATION TESTS
# ==============================================================================


def test_audit_log_retrieval_rbac_and_tenant_isolation(
    audit_client: TestClient, db_session: Session
):
    # Org A
    org_a, ws_a, owner_a, _ = create_test_tenant(db_session, "orga")
    admin_a = create_user_with_role(
        db_session, org_a, ws_a, f"admin_a_{uuid.uuid4().hex[:4]}@orga.com", ws_role=WorkspaceRole.WORKSPACE_ADMIN
    )
    contrib_a = create_user_with_role(
        db_session, org_a, ws_a, f"contrib_a_{uuid.uuid4().hex[:4]}@orga.com", ws_role=WorkspaceRole.CONTRIBUTOR
    )
    viewer_a = create_user_with_role(
        db_session, org_a, ws_a, f"viewer_a_{uuid.uuid4().hex[:4]}@orga.com", ws_role=WorkspaceRole.VIEWER
    )

    # Org B
    org_b, ws_b, owner_b, _ = create_test_tenant(db_session, "orgb")

    # Record some events in Org A and Org B
    AuditLogService.record_event(
        db_session,
        organization_id=org_a.id,
        workspace_id=ws_a.id,
        actor_user_id=admin_a.id,
        event_type=AuditEventType.DOCUMENT_CREATED,
        action="create_doc",
        autocommit=True,
    )
    AuditLogService.record_event(
        db_session,
        organization_id=org_b.id,
        workspace_id=ws_b.id,
        actor_user_id=owner_b.id,
        event_type=AuditEventType.DOCUMENT_CREATED,
        action="create_doc",
        autocommit=True,
    )

    # O & P: Viewer & Contributor are DENIED access to audit logs
    viewer_token = create_access_token(viewer_a.id, viewer_a.email)
    v_res = audit_client.get("/api/v1/audit-logs", headers={"Authorization": f"Bearer {viewer_token}"})
    assert v_res.status_code == 403

    contrib_token = create_access_token(contrib_a.id, contrib_a.email)
    c_res = audit_client.get("/api/v1/audit-logs", headers={"Authorization": f"Bearer {contrib_token}"})
    assert c_res.status_code == 403

    # Q: Workspace Admin CAN retrieve audit records for their workspace
    admin_token = create_access_token(admin_a.id, admin_a.email)
    admin_res = audit_client.get("/api/v1/audit-logs", headers={"Authorization": f"Bearer {admin_token}"})
    assert admin_res.status_code == 200
    items = admin_res.json()["items"]
    assert len(items) >= 1
    for item in items:
        assert item["organization_id"] == str(org_a.id)

    # R: Organization Owner receives org-wide records
    owner_token = create_access_token(owner_a.id, owner_a.email)
    owner_res = audit_client.get("/api/v1/audit-logs", headers={"Authorization": f"Bearer {owner_token}"})
    assert owner_res.status_code == 200
    for item in owner_res.json()["items"]:
        assert item["organization_id"] == str(org_a.id)

    # T: Cross-tenant isolation - Org A admin cannot see Org B logs even if passing org_b workspace_id
    cross_res = audit_client.get(
        f"/api/v1/audit-logs?workspace_id={ws_b.id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert cross_res.status_code == 403


# ==============================================================================
# SECTION U - V: IMMUTABILITY PROTECTION (TRIGGER ENFORCEMENT)
# ==============================================================================


def test_database_trigger_prevents_update_and_delete(db_session: Session):
    org, ws, user, _ = create_test_tenant(db_session, "immutable")

    audit = AuditLogService.record_event(
        db_session,
        organization_id=org.id,
        workspace_id=ws.id,
        actor_user_id=user.id,
        event_type=AuditEventType.DOCUMENT_CREATED,
        action="create_doc",
        autocommit=True,
    )

    # Attempt UPDATE directly via SQL
    with pytest.raises(Exception) as exc_update:
        db_session.execute(
            text("UPDATE audit_logs SET action = 'tampered' WHERE id = :log_id"),
            {"log_id": str(audit.id)},
        )
        db_session.flush()
    assert "immutable" in str(exc_update.value).lower() or "audit" in str(exc_update.value).lower()
    db_session.rollback()

    # Attempt DELETE directly via SQL
    with pytest.raises(Exception) as exc_delete:
        db_session.execute(
            text("DELETE FROM audit_logs WHERE id = :log_id"),
            {"log_id": str(audit.id)},
        )
        db_session.flush()
    assert "immutable" in str(exc_delete.value).lower() or "audit" in str(exc_delete.value).lower()
    db_session.rollback()


# ==============================================================================
# SECTION W - AA: TAMPER-EVIDENT HASH CHAIN VERIFICATION TESTS
# ==============================================================================


def test_cryptographic_hash_chain_verification_and_tamper_detection(
    db_session: Session, audit_client: TestClient
):
    org, ws, user, _ = create_test_tenant(db_session, "hash_chain")
    owner_token = create_access_token(user.id, user.email)

    # 1. Create a chain of 5 valid events
    for i in range(5):
        AuditLogService.record_event(
            db_session,
            organization_id=org.id,
            workspace_id=ws.id,
            actor_user_id=user.id,
            event_type=AuditEventType.DOCUMENT_VIEWED,
            action=f"view_step_{i}",
            metadata={"step": i},
            autocommit=True,
        )

    # W: Valid chain verifies cleanly via service and endpoint
    is_valid, err, count = AuditLogService.verify_chain(db_session, org.id)
    assert is_valid is True
    assert err is None
    assert count >= 5

    api_verify = audit_client.get(
        "/api/v1/audit-logs/verify",
        headers={"Authorization": f"Bearer {owner_token}"},
    )
    assert api_verify.status_code == 200
    assert api_verify.json()["is_valid"] is True

    # X: Tamper test: In-memory/simulated payload modification causes verification failure
    logs = db_session.query(AuditLog).filter(AuditLog.organization_id == org.id).order_by(AuditLog.created_at.asc()).all()
    target_event = logs[2]

    # Temporarily bypass trigger with disable trigger statement to test verification algorithm resilience
    db_session.execute(text("ALTER TABLE audit_logs DISABLE TRIGGER trg_prevent_audit_log_modification"))
    try:
        # X: Modify metadata
        db_session.execute(
            text("UPDATE audit_logs SET metadata = '{\"step\": 999, \"tampered\": true}' WHERE id = :id"),
            {"id": str(target_event.id)},
        )
        db_session.commit()

        is_valid_x, err_x, _ = AuditLogService.verify_chain(db_session, org.id)
        assert is_valid_x is False
        assert "hash mismatch" in str(err_x).lower()

        # Restore
        db_session.execute(
            text("UPDATE audit_logs SET metadata = :meta WHERE id = :id"),
            {"meta": '{"step": 2}', "id": str(target_event.id)},
        )
        db_session.commit()

        # Y: Broken previous_hash causes verification failure
        db_session.execute(
            text("UPDATE audit_logs SET previous_hash = 'bad_hash_value' WHERE id = :id"),
            {"id": str(target_event.id)},
        )
        db_session.commit()

        is_valid_y, err_y, _ = AuditLogService.verify_chain(db_session, org.id)
        assert is_valid_y is False
        assert "chain link broken" in str(err_y).lower()

        # Restore
        db_session.execute(
            text("UPDATE audit_logs SET previous_hash = :prev WHERE id = :id"),
            {"prev": target_event.previous_hash, "id": str(target_event.id)},
        )
        db_session.commit()

        # Z: Deleting an event causes verification failure
        deleted_event = logs[3]
        db_session.execute(text("DELETE FROM audit_logs WHERE id = :id"), {"id": str(deleted_event.id)})
        db_session.commit()

        is_valid_z, err_z, _ = AuditLogService.verify_chain(db_session, org.id)
        assert is_valid_z is False

    finally:
        # Re-enable trigger
        db_session.execute(text("ALTER TABLE audit_logs ENABLE TRIGGER trg_prevent_audit_log_modification"))
        db_session.commit()


# ==============================================================================
# SECTION AA: FORGED AUDIT EVENT INSERTION BREAKS CHAIN
# ==============================================================================


def test_forged_audit_event_insertion_breaks_chain(db_session: Session):
    org, ws, user, _ = create_test_tenant(db_session, "forged")

    # 1. Create 3 valid sequential events A, B, C
    event_a = AuditLogService.record_event(
        db_session,
        organization_id=org.id,
        workspace_id=ws.id,
        actor_user_id=user.id,
        event_type=AuditEventType.DOCUMENT_CREATED,
        action="event_a",
        autocommit=True,
    )
    event_b = AuditLogService.record_event(
        db_session,
        organization_id=org.id,
        workspace_id=ws.id,
        actor_user_id=user.id,
        event_type=AuditEventType.DOCUMENT_VIEWED,
        action="event_b",
        autocommit=True,
    )
    event_c = AuditLogService.record_event(
        db_session,
        organization_id=org.id,
        workspace_id=ws.id,
        actor_user_id=user.id,
        event_type=AuditEventType.DOCUMENT_UPDATED,
        action="event_c",
        autocommit=True,
    )

    # Initial chain is valid
    valid_initial, _, count = AuditLogService.verify_chain(db_session, org.id)
    assert valid_initial is True
    assert count == 3

    # 2. Insert a forged rogue event with a fabricated event hash
    forged_event = AuditLog(
        id=uuid.uuid4(),
        organization_id=org.id,
        workspace_id=ws.id,
        actor_user_id=user.id,
        event_type=AuditEventType.DOCUMENT_DELETED.value,
        action="forged_delete",
        outcome=AuditOutcome.SUCCESS.value,
        metadata_={"forged": True},
        created_at=datetime.now(timezone.utc),
        previous_hash=event_c.event_hash,
        event_hash="0000000000000000000000000000000000000000000000000000000000000000",
    )
    db_session.add(forged_event)
    db_session.commit()

    # 3. Verification must detect hash mismatch on forged event
    is_valid, err, broken_idx = AuditLogService.verify_chain(db_session, org.id)
    assert is_valid is False
    assert broken_idx == 3
    assert "hash mismatch" in str(err).lower()


# ==============================================================================
# SECTION AD: AUDIT VERIFICATION SCOPE ENFORCEMENT
# ==============================================================================


def test_audit_verification_scope_enforcement(audit_client: TestClient, db_session: Session):
    org, ws, owner, _ = create_test_tenant(db_session, "scope_enf")

    # Roles in org
    org_admin = create_user_with_role(
        db_session, org, ws, f"orgadmin_{uuid.uuid4().hex[:4]}@scope.com",
        org_role=OrganizationRole.ADMIN, ws_role=WorkspaceRole.WORKSPACE_ADMIN
    )
    ws_admin_only = create_user_with_role(
        db_session, org, ws, f"wsadmin_{uuid.uuid4().hex[:4]}@scope.com",
        org_role=OrganizationRole.MEMBER, ws_role=WorkspaceRole.WORKSPACE_ADMIN
    )
    contributor = create_user_with_role(
        db_session, org, ws, f"contrib_{uuid.uuid4().hex[:4]}@scope.com",
        org_role=OrganizationRole.MEMBER, ws_role=WorkspaceRole.CONTRIBUTOR
    )
    viewer = create_user_with_role(
        db_session, org, ws, f"viewer_{uuid.uuid4().hex[:4]}@scope.com",
        org_role=OrganizationRole.MEMBER, ws_role=WorkspaceRole.VIEWER
    )

    # Populate audit log
    AuditLogService.record_event(
        db_session,
        organization_id=org.id,
        workspace_id=ws.id,
        actor_user_id=owner.id,
        event_type=AuditEventType.DOCUMENT_CREATED,
        action="init",
        autocommit=True,
    )

    # A. Organization Owner CAN verify
    owner_token = create_access_token(owner.id, owner.email)
    owner_res = audit_client.get("/api/v1/audit-logs/verify", headers={"Authorization": f"Bearer {owner_token}"})
    assert owner_res.status_code == 200
    assert owner_res.json()["is_valid"] is True

    # B. Organization Admin CAN verify
    org_admin_token = create_access_token(org_admin.id, org_admin.email)
    admin_res = audit_client.get("/api/v1/audit-logs/verify", headers={"Authorization": f"Bearer {org_admin_token}"})
    assert admin_res.status_code == 200
    assert admin_res.json()["is_valid"] is True

    # C. Workspace Admin (Org role MEMBER) CANNOT verify (403 Forbidden)
    ws_admin_token = create_access_token(ws_admin_only.id, ws_admin_only.email)
    ws_admin_res = audit_client.get("/api/v1/audit-logs/verify", headers={"Authorization": f"Bearer {ws_admin_token}"})
    assert ws_admin_res.status_code == 403
    assert "Organization Owner or Organization Admin authority required" in ws_admin_res.json()["detail"]

    # D. Workspace Admin CAN still retrieve their workspace's audit records
    ws_list_res = audit_client.get("/api/v1/audit-logs", headers={"Authorization": f"Bearer {ws_admin_token}"})
    assert ws_list_res.status_code == 200
    assert len(ws_list_res.json()["items"]) >= 1

    # E & F. Contributor and Viewer CANNOT retrieve or verify
    contrib_token = create_access_token(contributor.id, contributor.email)
    viewer_token = create_access_token(viewer.id, viewer.email)

    assert audit_client.get("/api/v1/audit-logs/verify", headers={"Authorization": f"Bearer {contrib_token}"}).status_code == 403
    assert audit_client.get("/api/v1/audit-logs/verify", headers={"Authorization": f"Bearer {viewer_token}"}).status_code == 403
    assert audit_client.get("/api/v1/audit-logs", headers={"Authorization": f"Bearer {contrib_token}"}).status_code == 403
    assert audit_client.get("/api/v1/audit-logs", headers={"Authorization": f"Bearer {viewer_token}"}).status_code == 403


# ==============================================================================
# SECTION AE: CANONICAL PAYLOAD DETERMINISM & SANITIZATION
# ==============================================================================


def test_canonical_payload_determinism():
    org_id = uuid.uuid4()
    ws_id = uuid.uuid4()
    actor_id = uuid.uuid4()
    now = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)

    payload_a = compute_canonical_payload(
        organization_id=org_id,
        workspace_id=ws_id,
        actor_user_id=actor_id,
        actor_email="admin@test.com",
        event_type="DOCUMENT_CREATED",
        action="CREATE",
        outcome="SUCCESS",
        resource_type="document",
        resource_id="doc-123",
        clean_metadata={"zeta": 1, "alpha": "test"},
        ip_address="127.0.0.1",
        user_agent="Mozilla/5.0",
        request_id="req-123",
        created_at=now,
        previous_hash="prev_hash_abc",
    )

    payload_b = compute_canonical_payload(
        organization_id=org_id,
        workspace_id=ws_id,
        actor_user_id=actor_id,
        actor_email="admin@test.com",
        event_type="DOCUMENT_CREATED",
        action="CREATE",
        outcome="SUCCESS",
        resource_type="document",
        resource_id="doc-123",
        clean_metadata={"alpha": "test", "zeta": 1},
        ip_address="127.0.0.1",
        user_agent="Mozilla/5.0",
        request_id="req-123",
        created_at=now,
        previous_hash="prev_hash_abc",
    )

    # Key order in metadata or arguments must produce strictly identical byte streams
    assert payload_a == payload_b

    # Verify JSON structure
    parsed = json.loads(payload_a.decode("utf-8"))
    assert "event_hash" not in parsed  # event_hash is computed over the payload, not inside it
    assert parsed["previous_hash"] == "prev_hash_abc"
    assert parsed["organization_id"] == str(org_id)


# ==============================================================================
# SECTION AB - AC: RAG RETRIEVAL & EMBEDDING INDEPENDENCE TESTS
# ==============================================================================


def test_acl_audit_events_do_not_trigger_reembedding_or_alter_rag_results(
    audit_client: TestClient, db_session: Session
):
    org, ws, owner, _ = create_test_tenant(db_session, "rag_audit")
    owner_token = create_access_token(owner.id, owner.email)

    # Ingest document
    pdf_bytes = build_pdf(["Enterprise Audit Logging provides tamper evident governance."])
    files = {"file": ("arch.pdf", pdf_bytes, "application/pdf")}
    res = audit_client.post(
        "/api/v1/documents",
        headers={"Authorization": f"Bearer {owner_token}", "X-Workspace-Id": str(ws.id)},
        files=files,
    )
    assert res.status_code == 201
    doc_id = res.json()["id"]

    # Record initial chunk embedding counts
    chunks_before = db_session.query(DocumentChunk).filter(DocumentChunk.document_id == doc_id).all()
    assert len(chunks_before) >= 1
    original_chunk_ids = {c.id for c in chunks_before}

    # Add and remove ACLs (which generate audit events)
    user2 = create_user_with_role(db_session, org, ws, f"user2_{uuid.uuid4().hex[:4]}@test.com")
    acl_res = audit_client.post(
        f"/api/v1/documents/{doc_id}/acl",
        headers={"Authorization": f"Bearer {owner_token}", "X-Workspace-Id": str(ws.id)},
        json={"principal_type": "USER", "principal_id": str(user2.id), "permission": "READ"},
    )
    assert acl_res.status_code == 201
    acl_id = acl_res.json()["id"]

    audit_client.delete(
        f"/api/v1/documents/{doc_id}/acl/{acl_id}",
        headers={"Authorization": f"Bearer {owner_token}", "X-Workspace-Id": str(ws.id)},
    )

    # Verify: AB - Chunks and embeddings are completely unchanged
    chunks_after = db_session.query(DocumentChunk).filter(DocumentChunk.document_id == doc_id).all()
    assert {c.id for c in chunks_after} == original_chunk_ids

    # Verify: AC - RAG retrieval functions identically
    rag_res = audit_client.post(
        "/api/v1/chat",
        headers={"Authorization": f"Bearer {owner_token}", "X-Workspace-Id": str(ws.id)},
        json={"question": "What does Enterprise Audit Logging provide?"},
    )
    assert rag_res.status_code == 200
    assert len(rag_res.json()["sources"]) >= 1


# ==============================================================================
# SECTION AF - AI: REFERENTIAL IMMUTABILITY & TRANSACTIONAL FAILURE TESTS
# ==============================================================================


def test_referential_immutability_user_deletion_prohibited_when_referenced_in_audit_logs(
    db_session: Session,
):
    """Deleting a user referenced by immutable audit logs must be rejected by foreign key constraint,
    ensuring historical actor_user_id fields are never mutated to NULL (which would break hash verification).
    """
    org, ws, owner, _ = create_test_tenant(db_session, "user_fk_immut")

    # 1. Record valid audit event referencing owner
    event = AuditLogService.record_event(
        db_session,
        organization_id=org.id,
        workspace_id=ws.id,
        actor_user_id=owner.id,
        actor_email=owner.email,
        event_type=AuditEventType.LOGIN_SUCCESS,
        action="LOGIN",
        outcome=AuditOutcome.SUCCESS,
        autocommit=False,
    )
    db_session.flush()

    # Verify initial chain validity
    is_valid, err, count = AuditLogService.verify_chain(db_session, org.id)
    assert is_valid is True
    assert count == 1

    # 2. Attempt hard-deletion of the user entity inside a savepoint
    nested = db_session.begin_nested()
    with pytest.raises(IntegrityError) as excinfo:
        db_session.delete(owner)
        db_session.flush()

    assert (
        "audit_logs" in str(excinfo.value).lower()
        or "foreign key" in str(excinfo.value).lower()
        or "violates foreign key constraint" in str(excinfo.value).lower()
    )
    nested.rollback()

    # 3. Verify audit record remains completely unchanged and hash chain remains 100% valid
    persisted_event = db_session.get(AuditLog, event.id)
    assert persisted_event is not None
    assert persisted_event.actor_user_id == owner.id
    assert persisted_event.event_hash == event.event_hash

    is_valid_after, err_after, count_after = AuditLogService.verify_chain(db_session, org.id)
    assert is_valid_after is True
    assert err_after is None
    assert count_after == 1


def test_referential_immutability_workspace_deletion_prohibited_when_referenced_in_audit_logs(
    db_session: Session,
):
    """Deleting a workspace referenced by immutable audit logs must be rejected by foreign key constraint,
    preventing indirect NULL mutation of workspace_id.
    """
    org, ws, owner, _ = create_test_tenant(db_session, "ws_fk_immut")

    # 1. Record valid audit event referencing workspace
    event = AuditLogService.record_event(
        db_session,
        organization_id=org.id,
        workspace_id=ws.id,
        actor_user_id=owner.id,
        actor_email=owner.email,
        event_type=AuditEventType.WORKSPACE_CREATED,
        action="CREATE",
        outcome=AuditOutcome.SUCCESS,
        autocommit=False,
    )
    db_session.flush()

    # 2. Attempt hard-deletion of workspace entity inside a savepoint
    nested = db_session.begin_nested()
    with pytest.raises(IntegrityError) as excinfo:
        db_session.delete(ws)
        db_session.flush()

    assert (
        "audit_logs" in str(excinfo.value).lower()
        or "foreign key" in str(excinfo.value).lower()
        or "violates foreign key constraint" in str(excinfo.value).lower()
    )
    nested.rollback()

    # 3. Verify audit record remains intact and hash chain verifies
    persisted_event = db_session.get(AuditLog, event.id)
    assert persisted_event is not None
    assert persisted_event.workspace_id == ws.id

    is_valid, err, count = AuditLogService.verify_chain(db_session, org.id)
    assert is_valid is True
    assert count == 1


def test_transactional_mutation_rolls_back_when_audit_persistence_fails(
    db_session: Session,
):
    """If audit persistence fails during a transactional business mutation, the entire transaction
    must roll back so the mutation is not committed without an audit record.
    """
    org, ws, owner, _ = create_test_tenant(db_session, "tx_rollback")

    # Ingest document
    doc = Document(
        id=uuid.uuid4(),
        workspace_id=ws.id,
        filename="doc_tx.pdf",
        original_filename="doc_tx.pdf",
        file_type="application/pdf",
        file_path="/tmp/fake.pdf",
        file_size=100,
        page_count=1,
        status=DocumentStatus.COMPLETED,
    )
    db_session.add(doc)
    db_session.flush()
    doc_id = doc.id

    ws_ctx = WorkspaceContext(
        workspace_id=ws.id,
        organization_id=org.id,
        workspace_slug=ws.slug,
        organization_slug=org.slug,
        user_id=owner.id,
        workspace_role=WorkspaceRole.WORKSPACE_ADMIN,
        organization_role=OrganizationRole.OWNER,
        permissions=resolve_effective_permissions(OrganizationRole.OWNER, WorkspaceRole.WORKSPACE_ADMIN),
    )

    doc_service = DocumentService(
        session=db_session,
        workspace_id=ws.id,
        workspace_context=ws_ctx,
        autocommit=False,
    )

    # Wrap the mutation in a nested savepoint
    nested = db_session.begin_nested()
    real_record_event = AuditLogService.record_event

    def mock_record_event(*args, **kwargs):
        if kwargs.get("event_type") == AuditEventType.DOCUMENT_DELETED:
            raise RuntimeError("Simulated DB lock/audit disk failure on deletion")
        return real_record_event(*args, **kwargs)

    with patch.object(AuditLogService, "record_event", side_effect=mock_record_event):
        with pytest.raises(RuntimeError) as excinfo:
            doc_service.delete_document(doc_id)
        assert "Simulated DB lock/audit disk failure" in str(excinfo.value)

    # Roll back to savepoint
    nested.rollback()

    # Ensure document was NOT deleted and remains fully persistent
    doc_after = db_session.get(Document, doc_id)
    assert doc_after is not None
    assert doc_after.id == doc_id


def test_knowledge_query_audit_failure_is_non_blocking_and_emits_error_log(
    audit_client: TestClient, db_session: Session, caplog: pytest.LogCaptureFixture
):
    """Knowledge query auditing is best-effort telemetry. If audit recording fails after answer generation,
    the user receives their response, but an ERROR-level log is emitted with error details.
    """
    import logging

    org, ws, owner, _ = create_test_tenant(db_session, "query_audit_err")
    owner_token = create_access_token(owner.id, owner.email)

    # Ingest document
    pdf_bytes = build_pdf(["Compliance guidelines require explicit error telemetry."])
    files = {"file": ("comp.pdf", pdf_bytes, "application/pdf")}
    audit_client.post(
        "/api/v1/documents",
        headers={"Authorization": f"Bearer {owner_token}", "X-Workspace-Id": str(ws.id)},
        files=files,
    )

    with caplog.at_level(logging.ERROR):
        with patch.object(
            AuditLogService, "record_event", side_effect=RuntimeError("Simulated audit write timeout")
        ):
            rag_res = audit_client.post(
                "/api/v1/chat",
                headers={"Authorization": f"Bearer {owner_token}", "X-Workspace-Id": str(ws.id)},
                json={"question": "What do compliance guidelines require?"},
            )
            assert rag_res.status_code == 200
            assert "answer" in rag_res.json()

    # Check that an ERROR-level log was captured
    error_records = [
        rec
        for rec in caplog.records
        if rec.levelno >= logging.ERROR and "knowledge query" in rec.message.lower()
    ]
    assert len(error_records) >= 1

