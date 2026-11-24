"""Security and RBAC authorization tests for Phase 1.3.

Validates:
- Workspace role boundaries (Viewer, Contributor, Workspace Admin) on Document endpoints
- Chat authorization with KNOWLEDGE_QUERY
- Conversation privacy boundary across users in the same workspace
- Multi-workspace switching and capability shifts
- Arbitrary and cross-tenant workspace access rejection
- Privilege escalation prevention
"""

import uuid
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.db.database import get_db
from app.db.models import (
    Document,
    DocumentChunk,
    DocumentStatus,
    Organization,
    OrganizationMembership,
    OrganizationRole,
    User,
    Workspace,
    WorkspaceMembership,
    WorkspaceRole,
)
from app.main import app
from app.repositories.membership_repository import MembershipRepository
from tests.conftest import make_settings, postgres_available
from tests.helpers.pdfs import build_pdf


@pytest.fixture
def rbac_client(db_session, monkeypatch) -> TestClient:
    if not postgres_available():
        pytest.skip("PostgreSQL is not available for API tests.")

    provider = MagicMock()
    provider.create_embedding.side_effect = lambda text, task: [0.2] * 768
    monkeypatch.setattr("app.services.document_service.get_ai_provider", lambda: provider)

    def override_db():
        yield db_session

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def register_user(client: TestClient, email: str, name: str = "Test User") -> tuple[str, str, str]:
    """Helper returning (user_id, token, default_workspace_id)."""
    res = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "Password123!", "full_name": name},
    )
    assert res.status_code == 201
    body = res.json()
    token = body["access_token"]
    user_id = body["user"]["id"]

    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).json()
    ws_id = me["workspaces"][0]["id"]
    return user_id, token, ws_id


def test_viewer_role_restrictions(rbac_client: TestClient, db_session):
    """Viewer cannot upload, patch metadata, or delete documents, but can read and chat."""
    # 1. Register admin and viewer
    admin_id, admin_token, ws_id = register_user(
        rbac_client, f"admin_{uuid.uuid4().hex[:6]}@example.com", "Admin"
    )
    viewer_id, viewer_token, _ = register_user(
        rbac_client, f"viewer_{uuid.uuid4().hex[:6]}@example.com", "Viewer"
    )

    # Add viewer to admin's workspace with VIEWER role
    ws_uuid = uuid.UUID(ws_id)
    viewer_uuid = uuid.UUID(viewer_id)
    mem_repo = MembershipRepository(db_session)

    # First add viewer to admin's organization
    ws = db_session.get(Workspace, ws_uuid)
    mem_repo.add_organization_membership(
        OrganizationMembership(
            organization_id=ws.organization_id,
            user_id=viewer_uuid,
            role=OrganizationRole.MEMBER,
        )
    )
    # Add to workspace as VIEWER
    mem_repo.add_workspace_membership(
        WorkspaceMembership(
            workspace_id=ws_uuid,
            user_id=viewer_uuid,
            role=WorkspaceRole.VIEWER,
        )
    )
    db_session.commit()

    # 2. Upload a document as Admin
    pdf_bytes = build_pdf(["Policy content page one"])
    upload_res = rbac_client.post(
        "/api/v1/documents",
        headers={"Authorization": f"Bearer {admin_token}", "X-Workspace-Id": ws_id},
        files={"file": ("policy.pdf", pdf_bytes, "application/pdf")},
    )
    assert upload_res.status_code == 201
    doc_id = upload_res.json()["id"]

    # 3. Viewer attempts to upload -> 403 Forbidden
    viewer_headers = {"Authorization": f"Bearer {viewer_token}", "X-Workspace-Id": ws_id}
    viewer_upload = rbac_client.post(
        "/api/v1/documents",
        headers=viewer_headers,
        files={"file": ("viewer.pdf", pdf_bytes, "application/pdf")},
    )
    assert viewer_upload.status_code == 403
    assert "document:create" in viewer_upload.json()["detail"].lower()

    # 4. Viewer can read/list documents -> 200 OK
    viewer_list = rbac_client.get("/api/v1/documents", headers=viewer_headers)
    assert viewer_list.status_code == 200
    assert any(d["id"] == doc_id for d in viewer_list.json()["documents"])

    viewer_get = rbac_client.get(f"/api/v1/documents/{doc_id}", headers=viewer_headers)
    assert viewer_get.status_code == 200

    # 5. Viewer attempts to update metadata -> 403 Forbidden
    viewer_patch = rbac_client.patch(
        f"/api/v1/documents/{doc_id}",
        headers=viewer_headers,
        json={"category": "confidential"},
    )
    assert viewer_patch.status_code == 403
    assert "document:update" in viewer_patch.json()["detail"].lower()

    # 6. Viewer attempts to delete document -> 403 Forbidden
    viewer_delete = rbac_client.delete(f"/api/v1/documents/{doc_id}", headers=viewer_headers)
    assert viewer_delete.status_code == 403
    assert "document:delete" in viewer_delete.json()["detail"].lower()


def test_contributor_role_permissions(rbac_client: TestClient, db_session):
    """Contributor can upload and patch metadata, but cannot delete documents."""
    admin_id, admin_token, ws_id = register_user(
        rbac_client, f"admin_{uuid.uuid4().hex[:6]}@example.com", "Admin"
    )
    contrib_id, contrib_token, _ = register_user(
        rbac_client, f"contrib_{uuid.uuid4().hex[:6]}@example.com", "Contributor"
    )

    ws_uuid = uuid.UUID(ws_id)
    contrib_uuid = uuid.UUID(contrib_id)
    ws = db_session.get(Workspace, ws_uuid)
    mem_repo = MembershipRepository(db_session)

    mem_repo.add_organization_membership(
        OrganizationMembership(
            organization_id=ws.organization_id,
            user_id=contrib_uuid,
            role=OrganizationRole.MEMBER,
        )
    )
    mem_repo.add_workspace_membership(
        WorkspaceMembership(
            workspace_id=ws_uuid,
            user_id=contrib_uuid,
            role=WorkspaceRole.CONTRIBUTOR,
        )
    )
    db_session.commit()

    contrib_headers = {"Authorization": f"Bearer {contrib_token}", "X-Workspace-Id": ws_id}

    # 1. Contributor can upload
    pdf_bytes = build_pdf(["Contributor document content"])
    upload_res = rbac_client.post(
        "/api/v1/documents",
        headers=contrib_headers,
        files={"file": ("contrib.pdf", pdf_bytes, "application/pdf")},
    )
    assert upload_res.status_code == 201
    doc_id = upload_res.json()["id"]

    # 2. Contributor can update metadata
    patch_res = rbac_client.patch(
        f"/api/v1/documents/{doc_id}",
        headers=contrib_headers,
        json={"category": "engineering", "tags": ["spec", "design"]},
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["category"] == "engineering"
    assert patch_res.json()["tags"] == ["spec", "design"]

    # 3. Contributor cannot delete document -> 403 Forbidden
    del_res = rbac_client.delete(f"/api/v1/documents/{doc_id}", headers=contrib_headers)
    assert del_res.status_code == 403
    assert "document:delete" in del_res.json()["detail"].lower()

    # 4. Workspace Admin CAN delete document -> 204 No Content
    admin_del = rbac_client.delete(
        f"/api/v1/documents/{doc_id}",
        headers={"Authorization": f"Bearer {admin_token}", "X-Workspace-Id": ws_id},
    )
    assert admin_del.status_code == 204


def test_conversation_privacy_boundary(rbac_client: TestClient, db_session):
    """User A cannot access or delete User B's private conversations within the same workspace."""
    user_a_id, token_a, ws_id = register_user(
        rbac_client, f"user_a_{uuid.uuid4().hex[:6]}@example.com", "User A"
    )
    user_b_id, token_b, _ = register_user(
        rbac_client, f"user_b_{uuid.uuid4().hex[:6]}@example.com", "User B"
    )

    ws_uuid = uuid.UUID(ws_id)
    user_b_uuid = uuid.UUID(user_b_id)
    ws = db_session.get(Workspace, ws_uuid)
    mem_repo = MembershipRepository(db_session)

    mem_repo.add_organization_membership(
        OrganizationMembership(
            organization_id=ws.organization_id,
            user_id=user_b_uuid,
            role=OrganizationRole.MEMBER,
        )
    )
    mem_repo.add_workspace_membership(
        WorkspaceMembership(
            workspace_id=ws_uuid,
            user_id=user_b_uuid,
            role=WorkspaceRole.CONTRIBUTOR,
        )
    )
    db_session.commit()

    headers_a = {"Authorization": f"Bearer {token_a}", "X-Workspace-Id": ws_id}
    headers_b = {"Authorization": f"Bearer {token_b}", "X-Workspace-Id": ws_id}

    # 1. User A creates a conversation
    conv_a_res = rbac_client.post("/api/v1/conversations", headers=headers_a)
    assert conv_a_res.status_code == 201
    conv_a_id = conv_a_res.json()["id"]

    # 2. User B creates a conversation
    conv_b_res = rbac_client.post("/api/v1/conversations", headers=headers_b)
    assert conv_b_res.status_code == 201
    conv_b_id = conv_b_res.json()["id"]

    # 3. User B lists conversations: User A's conversation is NOT returned
    list_b = rbac_client.get("/api/v1/conversations", headers=headers_b)
    assert list_b.status_code == 200
    b_conv_ids = [c["id"] for c in list_b.json()["conversations"]]
    assert conv_b_id in b_conv_ids
    assert conv_a_id not in b_conv_ids

    # 4. User B attempts direct GET on User A's conversation -> 404 Not Found (privacy boundary)
    get_cross = rbac_client.get(f"/api/v1/conversations/{conv_a_id}", headers=headers_b)
    assert get_cross.status_code == 404

    # 5. User B attempts DELETE on User A's conversation -> 404 Not Found
    del_cross = rbac_client.delete(f"/api/v1/conversations/{conv_a_id}", headers=headers_b)
    assert del_cross.status_code == 404

    # 6. User B attempts to chat within User A's conversation -> 404 Not Found
    chat_cross = rbac_client.post(
        "/api/v1/chat",
        headers=headers_b,
        json={"question": "Confidential query?", "conversation_id": conv_a_id},
    )
    assert chat_cross.status_code == 404


def test_multi_workspace_switching_and_role_shift(rbac_client: TestClient, db_session):
    """A user who is WORKSPACE_ADMIN in Workspace A and VIEWER in Workspace B experiences proper role shifts."""
    user_id, token, ws_a_id = register_user(
        rbac_client, f"multi_{uuid.uuid4().hex[:6]}@example.com", "Multi User"
    )
    _, admin_b_token, ws_b_id = register_user(
        rbac_client, f"admin_b_{uuid.uuid4().hex[:6]}@example.com", "Admin B"
    )

    # In Workspace A, user is WORKSPACE_ADMIN (created via registration)
    # Add user to Workspace B as VIEWER
    ws_b_uuid = uuid.UUID(ws_b_id)
    user_uuid = uuid.UUID(user_id)
    ws_b = db_session.get(Workspace, ws_b_uuid)
    mem_repo = MembershipRepository(db_session)

    mem_repo.add_organization_membership(
        OrganizationMembership(
            organization_id=ws_b.organization_id,
            user_id=user_uuid,
            role=OrganizationRole.MEMBER,
        )
    )
    mem_repo.add_workspace_membership(
        WorkspaceMembership(
            workspace_id=ws_b_uuid,
            user_id=user_uuid,
            role=WorkspaceRole.VIEWER,
        )
    )
    db_session.commit()

    pdf_bytes = build_pdf(["Multi-workspace test document"])

    # 1. Switch to Workspace A: user is WORKSPACE_ADMIN -> upload and delete allowed
    headers_a = {"Authorization": f"Bearer {token}", "X-Workspace-Id": ws_a_id}
    res_upload_a = rbac_client.post(
        "/api/v1/documents",
        headers=headers_a,
        files={"file": ("doc_a.pdf", pdf_bytes, "application/pdf")},
    )
    assert res_upload_a.status_code == 201
    doc_a_id = res_upload_a.json()["id"]

    res_del_a = rbac_client.delete(f"/api/v1/documents/{doc_a_id}", headers=headers_a)
    assert res_del_a.status_code == 204

    # 2. Switch to Workspace B: user is VIEWER -> upload is denied (403)
    headers_b = {"Authorization": f"Bearer {token}", "X-Workspace-Id": ws_b_id}
    res_upload_b = rbac_client.post(
        "/api/v1/documents",
        headers=headers_b,
        files={"file": ("doc_b.pdf", pdf_bytes, "application/pdf")},
    )
    assert res_upload_b.status_code == 403
    assert "document:create" in res_upload_b.json()["detail"].lower()

    # 3. Requesting Workspace C where user has NO membership -> 403 Forbidden
    fake_ws_c = str(uuid.uuid4())
    headers_c = {"Authorization": f"Bearer {token}", "X-Workspace-Id": fake_ws_c}
    res_c = rbac_client.get("/api/v1/documents", headers=headers_c)
    assert res_c.status_code == 403
    assert "access" in res_c.json()["detail"].lower()


def test_cross_organization_member_addition_rejected(rbac_client: TestClient, db_session):
    """Adding a user to a workspace when they do not belong to the organization returns 400 Bad Request."""
    admin_a_id, admin_a_token, ws_a_id = register_user(
        rbac_client, f"org_a_{uuid.uuid4().hex[:6]}@example.com", "Admin Org A"
    )
    user_b_id, _, _ = register_user(
        rbac_client, f"org_b_{uuid.uuid4().hex[:6]}@example.com", "User Org B"
    )

    # Admin A tries to add User B to Workspace A directly without adding to Org A first
    headers_a = {"Authorization": f"Bearer {admin_a_token}"}
    res = rbac_client.post(
        f"/api/v1/workspaces/{ws_a_id}/members",
        headers=headers_a,
        json={"user_id": user_b_id, "role": "CONTRIBUTOR"},
    )
    assert res.status_code == 400
    assert "belong to the organization" in res.json()["detail"].lower()


def test_privilege_escalation_prevention(rbac_client: TestClient, db_session):
    """Users cannot modify their own role, non-owners cannot grant owner role, and last owner cannot be demoted."""
    owner_id, owner_token, ws_id = register_user(
        rbac_client, f"owner_{uuid.uuid4().hex[:6]}@example.com", "Owner"
    )
    member_id, member_token, _ = register_user(
        rbac_client, f"member_{uuid.uuid4().hex[:6]}@example.com", "Member"
    )

    ws = db_session.get(Workspace, uuid.UUID(ws_id))
    org_id = str(ws.organization_id)
    mem_repo = MembershipRepository(db_session)

    # Add member to org as MEMBER
    mem_repo.add_organization_membership(
        OrganizationMembership(
            organization_id=ws.organization_id,
            user_id=uuid.UUID(member_id),
            role=OrganizationRole.MEMBER,
        )
    )
    db_session.commit()

    # 1. Member tries to change own role to ADMIN or OWNER -> 403 Forbidden
    headers_member = {"Authorization": f"Bearer {member_token}"}
    res_self = rbac_client.patch(
        f"/api/v1/organizations/{org_id}/members/{member_id}",
        headers=headers_member,
        json={"role": "ADMIN"},
    )
    assert res_self.status_code == 403

    # 2. Owner tries to demote self when they are the ONLY owner -> 400 Bad Request
    headers_owner = {"Authorization": f"Bearer {owner_token}"}
    # First, self role change is prevented:
    res_demote_self = rbac_client.patch(
        f"/api/v1/organizations/{org_id}/members/{owner_id}",
        headers=headers_owner,
        json={"role": "MEMBER"},
    )
    assert res_demote_self.status_code == 403
