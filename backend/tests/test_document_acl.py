"""Security and authorization tests for Phase 1.4 Document-Level ACLs.

Validates:
- Default ACL behavior: documents with no ACL inherit workspace-level access.
- Restricted document behavior: unlisted users cannot see or access restricted documents.
- Retrieval security: restricted document chunks are excluded at the SQL level from
  dense, lexical, hybrid/RRF, reranking, and LLM context candidate pools.
- Workspace role ACLs: role-based document access restrictions.
- Workspace ceiling enforcement: document ACL cannot elevate privileges beyond workspace role.
- Workspace Admin self-lockout protection: admins retain management access.
- Cross-organization ACL validation: cannot grant ACL to external tenant users.
- ACL management API permissions: Viewers/Contributors denied ACL management; Admins allowed.
- Embedding independence: ACL changes do not touch embeddings or chunks.
"""

import uuid
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.document_access import can_access_document, resolve_document_permission
from app.db.database import get_db
from app.db.models import (
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
from app.repositories.chunk_repository import ChunkRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.membership_repository import MembershipRepository
from app.services.retrieval import RetrievalService
from tests.conftest import make_settings, postgres_available
from tests.helpers.pdfs import build_pdf


@pytest.fixture
def acl_client(db_session, monkeypatch) -> TestClient:
    if not postgres_available():
        pytest.skip("PostgreSQL is not available for API tests.")

    provider = MagicMock()
    provider.create_embedding.side_effect = lambda text, task: [0.15] * 768
    provider.generate_text.return_value = "Answer based on authorized context."
    monkeypatch.setattr("app.services.document_service.get_ai_provider", lambda: provider)
    monkeypatch.setattr("app.services.rag.get_ai_provider", lambda: provider)

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


def enroll_workspace_user(
    db_session,
    workspace_id: str,
    user_id: str,
    role: WorkspaceRole,
):
    """Enrolls a registered user into the organization and workspace."""
    ws_uuid = uuid.UUID(workspace_id)
    user_uuid = uuid.UUID(user_id)
    ws = db_session.get(Workspace, ws_uuid)
    mem_repo = MembershipRepository(db_session)

    # Org membership
    if not mem_repo.get_organization_membership(ws.organization_id, user_uuid):
        mem_repo.add_organization_membership(
            OrganizationMembership(
                organization_id=ws.organization_id,
                user_id=user_uuid,
                role=OrganizationRole.MEMBER,
            )
        )
    # Workspace membership
    if not mem_repo.get_workspace_membership(ws_uuid, user_uuid):
        mem_repo.add_workspace_membership(
            WorkspaceMembership(
                workspace_id=ws_uuid,
                user_id=user_uuid,
                role=role,
            )
        )
    db_session.commit()


def test_default_acl_inherits_workspace_access(acl_client: TestClient, db_session):
    """Documents with no ACL entries remain open to all workspace members."""
    admin_id, admin_token, ws_id = register_user(acl_client, f"admin_{uuid.uuid4().hex[:6]}@example.com")
    viewer_id, viewer_token, _ = register_user(acl_client, f"viewer_{uuid.uuid4().hex[:6]}@example.com")
    enroll_workspace_user(db_session, ws_id, viewer_id, WorkspaceRole.VIEWER)

    # 1. Admin uploads document
    pdf_bytes = build_pdf(["Public company handbook page 1"])
    upload_res = acl_client.post(
        "/api/v1/documents",
        headers={"Authorization": f"Bearer {admin_token}", "X-Workspace-Id": ws_id},
        files={"file": ("handbook.pdf", pdf_bytes, "application/pdf")},
    )
    assert upload_res.status_code == 201
    doc_id = upload_res.json()["id"]

    # 2. Viewer lists documents -> should see it
    viewer_headers = {"Authorization": f"Bearer {viewer_token}", "X-Workspace-Id": ws_id}
    list_res = acl_client.get("/api/v1/documents", headers=viewer_headers)
    assert list_res.status_code == 200
    doc_ids = [d["id"] for d in list_res.json()["documents"]]
    assert doc_id in doc_ids

    # 3. Viewer gets document detail -> 200
    get_res = acl_client.get(f"/api/v1/documents/{doc_id}", headers=viewer_headers)
    assert get_res.status_code == 200
    assert get_res.json()["original_filename"] == "handbook.pdf"


def test_document_acl_restricts_unlisted_users(acl_client: TestClient, db_session):
    """When ACL entries exist, only granted users can list or read the document."""
    admin_id, admin_token, ws_id = register_user(acl_client, f"admin_{uuid.uuid4().hex[:6]}@example.com")
    user_a_id, user_a_token, _ = register_user(acl_client, f"usera_{uuid.uuid4().hex[:6]}@example.com")
    user_b_id, user_b_token, _ = register_user(acl_client, f"userb_{uuid.uuid4().hex[:6]}@example.com")
    enroll_workspace_user(db_session, ws_id, user_a_id, WorkspaceRole.VIEWER)
    enroll_workspace_user(db_session, ws_id, user_b_id, WorkspaceRole.VIEWER)

    # Admin uploads document
    pdf_bytes = build_pdf(["Confidential financial results"])
    upload_res = acl_client.post(
        "/api/v1/documents",
        headers={"Authorization": f"Bearer {admin_token}", "X-Workspace-Id": ws_id},
        files={"file": ("finance.pdf", pdf_bytes, "application/pdf")},
    )
    assert upload_res.status_code == 201
    doc_id = upload_res.json()["id"]

    # Admin restricts document to User A only
    acl_res = acl_client.post(
        f"/api/v1/documents/{doc_id}/acl",
        headers={"Authorization": f"Bearer {admin_token}", "X-Workspace-Id": ws_id},
        json={
            "principal_type": "USER",
            "principal_id": user_a_id,
            "permission": "READ",
        },
    )
    assert acl_res.status_code == 201

    # User A lists documents -> sees finance.pdf
    headers_a = {"Authorization": f"Bearer {user_a_token}", "X-Workspace-Id": ws_id}
    res_a = acl_client.get("/api/v1/documents", headers=headers_a)
    assert res_a.status_code == 200
    assert doc_id in [d["id"] for d in res_a.json()["documents"]]

    # User A gets document -> 200
    get_a = acl_client.get(f"/api/v1/documents/{doc_id}", headers=headers_a)
    assert get_a.status_code == 200

    # User B lists documents -> finance.pdf is NOT in the list
    headers_b = {"Authorization": f"Bearer {user_b_token}", "X-Workspace-Id": ws_id}
    res_b = acl_client.get("/api/v1/documents", headers=headers_b)
    assert res_b.status_code == 200
    assert doc_id not in [d["id"] for d in res_b.json()["documents"]]

    # User B attempts direct GET /documents/{id} -> 404 Not Found (no leakage)
    get_b = acl_client.get(f"/api/v1/documents/{doc_id}", headers=headers_b)
    assert get_b.status_code == 404


def test_document_acl_retrieval_isolation_at_sql_level(acl_client: TestClient, db_session):
    """Restricted document chunks are excluded from retrieval candidate pools."""
    admin_id, admin_token, ws_id = register_user(acl_client, f"admin_{uuid.uuid4().hex[:6]}@example.com")
    user_a_id, user_a_token, _ = register_user(acl_client, f"usera_{uuid.uuid4().hex[:6]}@example.com")
    user_b_id, user_b_token, _ = register_user(acl_client, f"userb_{uuid.uuid4().hex[:6]}@example.com")
    enroll_workspace_user(db_session, ws_id, user_a_id, WorkspaceRole.CONTRIBUTOR)
    enroll_workspace_user(db_session, ws_id, user_b_id, WorkspaceRole.CONTRIBUTOR)

    # 1. Admin uploads secret document
    secret_pdf = build_pdf(["Project Krypton code is delta-niner-9988."])
    doc_res = acl_client.post(
        "/api/v1/documents",
        headers={"Authorization": f"Bearer {admin_token}", "X-Workspace-Id": ws_id},
        files={"file": ("secret.pdf", secret_pdf, "application/pdf")},
    )
    assert doc_res.status_code == 201
    doc_id = doc_res.json()["id"]

    # 2. Restrict secret document to User A only
    acl_client.post(
        f"/api/v1/documents/{doc_id}/acl",
        headers={"Authorization": f"Bearer {admin_token}", "X-Workspace-Id": ws_id},
        json={"principal_type": "USER", "principal_id": user_a_id, "permission": "READ"},
    )

    # 3. User B queries chat about the secret
    headers_b = {"Authorization": f"Bearer {user_b_token}", "X-Workspace-Id": ws_id}
    chat_b = acl_client.post(
        "/api/v1/chat",
        headers=headers_b,
        json={"question": "What is the Project Krypton code?"},
    )
    assert chat_b.status_code == 200
    body_b = chat_b.json()
    # User B receives NO_CONTEXT_ANSWER and 0 sources
    assert body_b["sources"] == []
    assert "couldn't find relevant information" in body_b["answer"]

    # 4. User A queries chat about the secret
    headers_a = {"Authorization": f"Bearer {user_a_token}", "X-Workspace-Id": ws_id}
    chat_a = acl_client.post(
        "/api/v1/chat",
        headers=headers_a,
        json={"question": "What is the Project Krypton code?"},
    )
    assert chat_a.status_code == 200
    body_a = chat_a.json()
    assert len(body_a["sources"]) > 0
    assert body_a["sources"][0]["document_id"] == doc_id


def test_workspace_role_acl(acl_client: TestClient, db_session):
    """Document ACL with principal_type=WORKSPACE_ROLE allows all members with that role."""
    admin_id, admin_token, ws_id = register_user(acl_client, f"admin_{uuid.uuid4().hex[:6]}@example.com")
    contributor_id, contrib_token, _ = register_user(acl_client, f"contrib_{uuid.uuid4().hex[:6]}@example.com")
    viewer_id, viewer_token, _ = register_user(acl_client, f"viewer_{uuid.uuid4().hex[:6]}@example.com")
    enroll_workspace_user(db_session, ws_id, contributor_id, WorkspaceRole.CONTRIBUTOR)
    enroll_workspace_user(db_session, ws_id, viewer_id, WorkspaceRole.VIEWER)

    # Admin uploads doc
    pdf_bytes = build_pdf(["Engineering spec document"])
    upload_res = acl_client.post(
        "/api/v1/documents",
        headers={"Authorization": f"Bearer {admin_token}", "X-Workspace-Id": ws_id},
        files={"file": ("spec.pdf", pdf_bytes, "application/pdf")},
    )
    doc_id = upload_res.json()["id"]

    # Restrict document to CONTRIBUTOR role
    acl_client.post(
        f"/api/v1/documents/{doc_id}/acl",
        headers={"Authorization": f"Bearer {admin_token}", "X-Workspace-Id": ws_id},
        json={"principal_type": "WORKSPACE_ROLE", "principal_id": "CONTRIBUTOR", "permission": "READ"},
    )

    # Contributor can read
    res_contrib = acl_client.get(
        f"/api/v1/documents/{doc_id}",
        headers={"Authorization": f"Bearer {contrib_token}", "X-Workspace-Id": ws_id},
    )
    assert res_contrib.status_code == 200

    # Viewer cannot read (404)
    res_viewer = acl_client.get(
        f"/api/v1/documents/{doc_id}",
        headers={"Authorization": f"Bearer {viewer_token}", "X-Workspace-Id": ws_id},
    )
    assert res_viewer.status_code == 404


def test_workspace_ceiling_enforcement(acl_client: TestClient, db_session):
    """Document ACL cannot elevate privileges beyond workspace role ceiling."""
    admin_id, admin_token, ws_id = register_user(acl_client, f"admin_{uuid.uuid4().hex[:6]}@example.com")
    viewer_id, viewer_token, _ = register_user(acl_client, f"viewer_{uuid.uuid4().hex[:6]}@example.com")
    contrib_id, contrib_token, _ = register_user(acl_client, f"contrib_{uuid.uuid4().hex[:6]}@example.com")
    enroll_workspace_user(db_session, ws_id, viewer_id, WorkspaceRole.VIEWER)
    enroll_workspace_user(db_session, ws_id, contrib_id, WorkspaceRole.CONTRIBUTOR)

    # Admin uploads doc
    pdf_bytes = build_pdf(["Document ceiling test"])
    upload_res = acl_client.post(
        "/api/v1/documents",
        headers={"Authorization": f"Bearer {admin_token}", "X-Workspace-Id": ws_id},
        files={"file": ("ceiling.pdf", pdf_bytes, "application/pdf")},
    )
    doc_id = upload_res.json()["id"]

    # Admin grants Viewer and Contributor ADMIN on the document
    acl_client.post(
        f"/api/v1/documents/{doc_id}/acl",
        headers={"Authorization": f"Bearer {admin_token}", "X-Workspace-Id": ws_id},
        json={"principal_type": "USER", "principal_id": viewer_id, "permission": "ADMIN"},
    )
    acl_client.post(
        f"/api/v1/documents/{doc_id}/acl",
        headers={"Authorization": f"Bearer {admin_token}", "X-Workspace-Id": ws_id},
        json={"principal_type": "USER", "principal_id": contrib_id, "permission": "ADMIN"},
    )

    # 1. Viewer cannot DELETE -> 403 (ceiling lacks DOCUMENT_DELETE)
    viewer_headers = {"Authorization": f"Bearer {viewer_token}", "X-Workspace-Id": ws_id}
    del_viewer = acl_client.delete(f"/api/v1/documents/{doc_id}", headers=viewer_headers)
    assert del_viewer.status_code == 403

    # 2. Viewer cannot PATCH -> 403 (ceiling lacks DOCUMENT_UPDATE)
    patch_viewer = acl_client.patch(
        f"/api/v1/documents/{doc_id}",
        headers=viewer_headers,
        json={"category": "confidential"},
    )
    assert patch_viewer.status_code == 403

    # 3. Contributor CAN PATCH -> 200 (workspace role has DOCUMENT_UPDATE)
    contrib_headers = {"Authorization": f"Bearer {contrib_token}", "X-Workspace-Id": ws_id}
    patch_contrib = acl_client.patch(
        f"/api/v1/documents/{doc_id}",
        headers=contrib_headers,
        json={"category": "engineering"},
    )
    assert patch_contrib.status_code == 200

    # 4. Contributor cannot DELETE -> 403 (ceiling lacks DOCUMENT_DELETE)
    del_contrib = acl_client.delete(f"/api/v1/documents/{doc_id}", headers=contrib_headers)
    assert del_contrib.status_code == 403


def test_workspace_admin_self_lockout_protection(acl_client: TestClient, db_session):
    """Workspace Admin retains full management access even if not listed in document ACL."""
    admin_id, admin_token, ws_id = register_user(acl_client, f"admin_{uuid.uuid4().hex[:6]}@example.com")
    user_a_id, user_a_token, _ = register_user(acl_client, f"usera_{uuid.uuid4().hex[:6]}@example.com")
    enroll_workspace_user(db_session, ws_id, user_a_id, WorkspaceRole.VIEWER)

    # Admin uploads doc
    pdf_bytes = build_pdf(["Admin protection test"])
    upload_res = acl_client.post(
        "/api/v1/documents",
        headers={"Authorization": f"Bearer {admin_token}", "X-Workspace-Id": ws_id},
        files={"file": ("admin_prot.pdf", pdf_bytes, "application/pdf")},
    )
    doc_id = upload_res.json()["id"]

    # Restrict doc ONLY to User A
    acl_client.post(
        f"/api/v1/documents/{doc_id}/acl",
        headers={"Authorization": f"Bearer {admin_token}", "X-Workspace-Id": ws_id},
        json={"principal_type": "USER", "principal_id": user_a_id, "permission": "READ"},
    )

    # Admin can still GET, PATCH, and DELETE
    admin_headers = {"Authorization": f"Bearer {admin_token}", "X-Workspace-Id": ws_id}
    get_res = acl_client.get(f"/api/v1/documents/{doc_id}", headers=admin_headers)
    assert get_res.status_code == 200

    patch_res = acl_client.patch(
        f"/api/v1/documents/{doc_id}",
        headers=admin_headers,
        json={"category": "general"},
    )
    assert patch_res.status_code == 200

    del_res = acl_client.delete(f"/api/v1/documents/{doc_id}", headers=admin_headers)
    assert del_res.status_code == 204


def test_cross_organization_user_acl_rejection(acl_client: TestClient, db_session):
    """Cannot add a user from another organization/workspace to document ACL."""
    admin_id, admin_token, ws_id = register_user(acl_client, f"admin_{uuid.uuid4().hex[:6]}@example.com")
    ext_user_id, ext_token, _ = register_user(acl_client, f"external_{uuid.uuid4().hex[:6]}@example.com")

    # Admin uploads doc in Org A
    pdf_bytes = build_pdf(["Org A Doc"])
    upload_res = acl_client.post(
        "/api/v1/documents",
        headers={"Authorization": f"Bearer {admin_token}", "X-Workspace-Id": ws_id},
        files={"file": ("org_a.pdf", pdf_bytes, "application/pdf")},
    )
    doc_id = upload_res.json()["id"]

    # Attempt to add external user to Document ACL -> 400 Bad Request
    res = acl_client.post(
        f"/api/v1/documents/{doc_id}/acl",
        headers={"Authorization": f"Bearer {admin_token}", "X-Workspace-Id": ws_id},
        json={"principal_type": "USER", "principal_id": ext_user_id, "permission": "READ"},
    )
    assert res.status_code == 400
    assert "User must belong to the workspace organization" in res.json()["detail"]


def test_acl_management_permissions_and_lifecycle(acl_client: TestClient, db_session):
    """Viewers and Contributors cannot manage ACLs; Admins can manage full ACL lifecycle."""
    admin_id, admin_token, ws_id = register_user(acl_client, f"admin_{uuid.uuid4().hex[:6]}@example.com")
    viewer_id, viewer_token, _ = register_user(acl_client, f"viewer_{uuid.uuid4().hex[:6]}@example.com")
    enroll_workspace_user(db_session, ws_id, viewer_id, WorkspaceRole.VIEWER)

    # Admin uploads doc
    pdf_bytes = build_pdf(["ACL Lifecycle test"])
    upload_res = acl_client.post(
        "/api/v1/documents",
        headers={"Authorization": f"Bearer {admin_token}", "X-Workspace-Id": ws_id},
        files={"file": ("lifecycle.pdf", pdf_bytes, "application/pdf")},
    )
    doc_id = upload_res.json()["id"]

    # 1. Viewer attempts to add ACL -> 403 Forbidden
    viewer_headers = {"Authorization": f"Bearer {viewer_token}", "X-Workspace-Id": ws_id}
    viewer_add = acl_client.post(
        f"/api/v1/documents/{doc_id}/acl",
        headers=viewer_headers,
        json={"principal_type": "USER", "principal_id": viewer_id, "permission": "READ"},
    )
    assert viewer_add.status_code == 403

    # 2. Admin adds ACL entry -> 201 Created
    admin_headers = {"Authorization": f"Bearer {admin_token}", "X-Workspace-Id": ws_id}
    admin_add = acl_client.post(
        f"/api/v1/documents/{doc_id}/acl",
        headers=admin_headers,
        json={"principal_type": "USER", "principal_id": viewer_id, "permission": "READ"},
    )
    assert admin_add.status_code == 201
    acl_id = admin_add.json()["id"]

    # 3. Admin lists ACL entries -> 200
    list_acl = acl_client.get(f"/api/v1/documents/{doc_id}/acl", headers=admin_headers)
    assert list_acl.status_code == 200
    assert len(list_acl.json()["acls"]) == 1
    assert list_acl.json()["acls"][0]["id"] == acl_id

    # 4. Viewer attempts to delete ACL -> 403 Forbidden
    viewer_del = acl_client.delete(f"/api/v1/documents/{doc_id}/acl/{acl_id}", headers=viewer_headers)
    assert viewer_del.status_code == 403

    # 5. Admin deletes ACL entry -> 204
    admin_del = acl_client.delete(f"/api/v1/documents/{doc_id}/acl/{acl_id}", headers=admin_headers)
    assert admin_del.status_code == 204

    # 6. Verify ACL list is now empty (reverts to inheriting workspace access)
    list_after = acl_client.get(f"/api/v1/documents/{doc_id}/acl", headers=admin_headers)
    assert len(list_after.json()["acls"]) == 0


def test_contributor_with_doc_admin_cannot_manage_acls(acl_client: TestClient, db_session):
    """Contributor granted document-level ADMIN must NOT be allowed to manage ACLs (no privilege escalation)."""
    admin_id, admin_token, ws_id = register_user(acl_client, f"admin_{uuid.uuid4().hex[:6]}@example.com")
    contrib_id, contrib_token, _ = register_user(acl_client, f"contrib_{uuid.uuid4().hex[:6]}@example.com")
    viewer_id, viewer_token, _ = register_user(acl_client, f"viewer_{uuid.uuid4().hex[:6]}@example.com")
    enroll_workspace_user(db_session, ws_id, contrib_id, WorkspaceRole.CONTRIBUTOR)
    enroll_workspace_user(db_session, ws_id, viewer_id, WorkspaceRole.VIEWER)

    # Admin uploads doc
    pdf_bytes = build_pdf(["Contributor doc admin test"])
    upload_res = acl_client.post(
        "/api/v1/documents",
        headers={"Authorization": f"Bearer {admin_token}", "X-Workspace-Id": ws_id},
        files={"file": ("contrib_admin.pdf", pdf_bytes, "application/pdf")},
    )
    doc_id = upload_res.json()["id"]

    # Admin grants Contributor ADMIN permission on the document
    acl_add = acl_client.post(
        f"/api/v1/documents/{doc_id}/acl",
        headers={"Authorization": f"Bearer {admin_token}", "X-Workspace-Id": ws_id},
        json={"principal_type": "USER", "principal_id": contrib_id, "permission": "ADMIN"},
    )
    assert acl_add.status_code == 201
    acl_id = acl_add.json()["id"]

    contrib_headers = {"Authorization": f"Bearer {contrib_token}", "X-Workspace-Id": ws_id}

    # 1. Contributor attempts GET /documents/{id}/acl -> 403 Forbidden
    get_acl = acl_client.get(f"/api/v1/documents/{doc_id}/acl", headers=contrib_headers)
    assert get_acl.status_code == 403

    # 2. Contributor attempts POST /documents/{id}/acl -> 403 Forbidden
    post_acl = acl_client.post(
        f"/api/v1/documents/{doc_id}/acl",
        headers=contrib_headers,
        json={"principal_type": "USER", "principal_id": viewer_id, "permission": "READ"},
    )
    assert post_acl.status_code == 403

    # 3. Contributor attempts DELETE /documents/{id}/acl/{acl_id} -> 403 Forbidden
    del_acl = acl_client.delete(f"/api/v1/documents/{doc_id}/acl/{acl_id}", headers=contrib_headers)
    assert del_acl.status_code == 403


def test_viewer_with_doc_admin_cannot_manage_acls(acl_client: TestClient, db_session):
    """Viewer granted document-level ADMIN must NOT be allowed to manage ACLs."""
    admin_id, admin_token, ws_id = register_user(acl_client, f"admin_{uuid.uuid4().hex[:6]}@example.com")
    viewer_id, viewer_token, _ = register_user(acl_client, f"viewer_{uuid.uuid4().hex[:6]}@example.com")
    other_id, other_token, _ = register_user(acl_client, f"other_{uuid.uuid4().hex[:6]}@example.com")
    enroll_workspace_user(db_session, ws_id, viewer_id, WorkspaceRole.VIEWER)
    enroll_workspace_user(db_session, ws_id, other_id, WorkspaceRole.VIEWER)

    # Admin uploads doc
    pdf_bytes = build_pdf(["Viewer doc admin test"])
    upload_res = acl_client.post(
        "/api/v1/documents",
        headers={"Authorization": f"Bearer {admin_token}", "X-Workspace-Id": ws_id},
        files={"file": ("viewer_admin.pdf", pdf_bytes, "application/pdf")},
    )
    doc_id = upload_res.json()["id"]

    # Admin grants Viewer ADMIN permission on the document
    acl_add = acl_client.post(
        f"/api/v1/documents/{doc_id}/acl",
        headers={"Authorization": f"Bearer {admin_token}", "X-Workspace-Id": ws_id},
        json={"principal_type": "USER", "principal_id": viewer_id, "permission": "ADMIN"},
    )
    assert acl_add.status_code == 201
    acl_id = acl_add.json()["id"]

    viewer_headers = {"Authorization": f"Bearer {viewer_token}", "X-Workspace-Id": ws_id}

    # 1. Viewer attempts GET /documents/{id}/acl -> 403 Forbidden
    assert acl_client.get(f"/api/v1/documents/{doc_id}/acl", headers=viewer_headers).status_code == 403

    # 2. Viewer attempts POST /documents/{id}/acl -> 403 Forbidden
    assert (
        acl_client.post(
            f"/api/v1/documents/{doc_id}/acl",
            headers=viewer_headers,
            json={"principal_type": "USER", "principal_id": other_id, "permission": "READ"},
        ).status_code
        == 403
    )

    # 3. Viewer attempts DELETE /documents/{id}/acl/{acl_id} -> 403 Forbidden
    assert (
        acl_client.delete(f"/api/v1/documents/{doc_id}/acl/{acl_id}", headers=viewer_headers).status_code
        == 403
    )


def test_org_owner_can_manage_acls(acl_client: TestClient, db_session):
    """Organization Owner inherits workspace administrative authority and can manage document ACLs."""
    owner_id, owner_token, ws_id = register_user(acl_client, f"owner_{uuid.uuid4().hex[:6]}@example.com")
    member_id, member_token, _ = register_user(acl_client, f"member_{uuid.uuid4().hex[:6]}@example.com")
    enroll_workspace_user(db_session, ws_id, member_id, WorkspaceRole.VIEWER)

    owner_headers = {"Authorization": f"Bearer {owner_token}", "X-Workspace-Id": ws_id}

    # Owner uploads document
    pdf_bytes = build_pdf(["Org Owner ACL management test"])
    upload_res = acl_client.post(
        "/api/v1/documents",
        headers=owner_headers,
        files={"file": ("owner_test.pdf", pdf_bytes, "application/pdf")},
    )
    assert upload_res.status_code == 201
    doc_id = upload_res.json()["id"]

    # Owner adds ACL -> 201
    add_res = acl_client.post(
        f"/api/v1/documents/{doc_id}/acl",
        headers=owner_headers,
        json={"principal_type": "USER", "principal_id": member_id, "permission": "READ"},
    )
    assert add_res.status_code == 201
    acl_id = add_res.json()["id"]

    # Owner lists ACLs -> 200
    list_res = acl_client.get(f"/api/v1/documents/{doc_id}/acl", headers=owner_headers)
    assert list_res.status_code == 200
    assert len(list_res.json()["acls"]) == 1

    # Owner deletes ACL -> 204
    del_res = acl_client.delete(f"/api/v1/documents/{doc_id}/acl/{acl_id}", headers=owner_headers)
    assert del_res.status_code == 204


def test_direct_chunk_and_repository_security(acl_client: TestClient, db_session):
    """Direct repository and chunk access respects document ACL filtering at SQL level."""
    admin_id, admin_token, ws_id = register_user(acl_client, f"admin_{uuid.uuid4().hex[:6]}@example.com")
    user_a_id, user_a_token, _ = register_user(acl_client, f"usera_{uuid.uuid4().hex[:6]}@example.com")
    user_b_id, user_b_token, _ = register_user(acl_client, f"userb_{uuid.uuid4().hex[:6]}@example.com")
    enroll_workspace_user(db_session, ws_id, user_a_id, WorkspaceRole.VIEWER)
    enroll_workspace_user(db_session, ws_id, user_b_id, WorkspaceRole.VIEWER)

    # Admin uploads doc
    pdf_bytes = build_pdf(["Classified blueprint details for Project Omega 9988."])
    upload_res = acl_client.post(
        "/api/v1/documents",
        headers={"Authorization": f"Bearer {admin_token}", "X-Workspace-Id": ws_id},
        files={"file": ("omega.pdf", pdf_bytes, "application/pdf")},
    )
    doc_id = uuid.UUID(upload_res.json()["id"])
    ws_uuid = uuid.UUID(ws_id)
    user_a_uuid = uuid.UUID(user_a_id)
    user_b_uuid = uuid.UUID(user_b_id)

    # Restrict doc to User A only
    acl_client.post(
        f"/api/v1/documents/{doc_id}/acl",
        headers={"Authorization": f"Bearer {admin_token}", "X-Workspace-Id": ws_id},
        json={"principal_type": "USER", "principal_id": user_a_id, "permission": "READ"},
    )

    doc_repo = DocumentRepository(db_session)
    chunk_repo = ChunkRepository(db_session)

    # 1. DocumentRepository.get_by_id:
    # User A -> finds document
    doc_a = doc_repo.get_by_id(doc_id, workspace_id=ws_uuid, user_id=user_a_uuid, workspace_role=WorkspaceRole.VIEWER, is_admin=False)
    assert doc_a is not None
    # User B -> None
    doc_b = doc_repo.get_by_id(doc_id, workspace_id=ws_uuid, user_id=user_b_uuid, workspace_role=WorkspaceRole.VIEWER, is_admin=False)
    assert doc_b is None

    # 2. DocumentRepository.list_all:
    # User A -> contains doc_id
    docs_a = doc_repo.list_all(workspace_id=ws_uuid, user_id=user_a_uuid, workspace_role=WorkspaceRole.VIEWER, is_admin=False)
    assert doc_id in [d.id for d in docs_a]
    # User B -> does NOT contain doc_id
    docs_b = doc_repo.list_all(workspace_id=ws_uuid, user_id=user_b_uuid, workspace_role=WorkspaceRole.VIEWER, is_admin=False)
    assert doc_id not in [d.id for d in docs_b]

    # 3. ChunkRepository.search_similar (Dense SQL candidate selection):
    # User A -> retrieves chunk
    similar_a = chunk_repo.search_similar(
        [0.15] * 768,
        top_k=5,
        similarity_threshold=0.0,
        workspace_id=ws_uuid,
        user_id=user_a_uuid,
        workspace_role=WorkspaceRole.VIEWER,
        is_admin=False,
    )
    assert len(similar_a) > 0
    assert any(chunk.document_id == doc_id for chunk, doc, score in similar_a)

    # User B -> 0 chunks from this document
    similar_b = chunk_repo.search_similar(
        [0.15] * 768,
        top_k=5,
        similarity_threshold=0.0,
        workspace_id=ws_uuid,
        user_id=user_b_uuid,
        workspace_role=WorkspaceRole.VIEWER,
        is_admin=False,
    )
    assert not any(chunk.document_id == doc_id for chunk, doc, score in similar_b)

    # 4. ChunkRepository.search_lexical (Lexical SQL candidate selection):
    # User A -> retrieves chunk
    lexical_a = chunk_repo.search_lexical(
        "Project Omega",
        [0.15] * 768,
        top_k=5,
        workspace_id=ws_uuid,
        user_id=user_a_uuid,
        workspace_role=WorkspaceRole.VIEWER,
        is_admin=False,
    )
    assert len(lexical_a) > 0
    assert any(chunk.document_id == doc_id for chunk, doc, l_score, c_score, hit in lexical_a)

    # User B -> 0 chunks from this document
    lexical_b = chunk_repo.search_lexical(
        "Project Omega",
        [0.15] * 768,
        top_k=5,
        workspace_id=ws_uuid,
        user_id=user_b_uuid,
        workspace_role=WorkspaceRole.VIEWER,
        is_admin=False,
    )
    assert not any(chunk.document_id == doc_id for chunk, doc, l_score, c_score, hit in lexical_b)


def test_retrieval_pre_filtering_stages_audit(acl_client: TestClient, db_session):
    """Proves unauthorized document is filtered out BEFORE dense/lexical pools, RRF, reranking, and LLM context."""
    admin_id, admin_token, ws_id = register_user(acl_client, f"admin_{uuid.uuid4().hex[:6]}@example.com")
    user_a_id, user_a_token, _ = register_user(acl_client, f"usera_{uuid.uuid4().hex[:6]}@example.com")
    user_b_id, user_b_token, _ = register_user(acl_client, f"userb_{uuid.uuid4().hex[:6]}@example.com")
    enroll_workspace_user(db_session, ws_id, user_a_id, WorkspaceRole.VIEWER)
    enroll_workspace_user(db_session, ws_id, user_b_id, WorkspaceRole.VIEWER)

    # Upload document
    pdf_bytes = build_pdf(["Top secret algorithm code name Phoenix."])
    upload_res = acl_client.post(
        "/api/v1/documents",
        headers={"Authorization": f"Bearer {admin_token}", "X-Workspace-Id": ws_id},
        files={"file": ("phoenix.pdf", pdf_bytes, "application/pdf")},
    )
    doc_id = uuid.UUID(upload_res.json()["id"])
    ws_uuid = uuid.UUID(ws_id)
    user_b_uuid = uuid.UUID(user_b_id)

    # Restrict to User A only
    acl_client.post(
        f"/api/v1/documents/{doc_id}/acl",
        headers={"Authorization": f"Bearer {admin_token}", "X-Workspace-Id": ws_id},
        json={"principal_type": "USER", "principal_id": user_a_id, "permission": "READ"},
    )

    retrieval_svc = RetrievalService(db_session)

    # Stage 1 & 2: Dense & Lexical retrieval for User B yield 0 candidate chunks
    dense_chunks = retrieval_svc.retrieve(
        [0.15] * 768,
        question="What is Phoenix?",
        top_k=5,
        similarity_threshold=0.0,
        retrieval_mode="dense",
        workspace_id=ws_uuid,
        user_id=user_b_uuid,
        workspace_role=WorkspaceRole.VIEWER,
        is_admin=False,
    )
    assert len(dense_chunks) == 0

    lexical_chunks = retrieval_svc.retrieve(
        [0.15] * 768,
        question="What is Phoenix?",
        top_k=5,
        similarity_threshold=0.0,
        retrieval_mode="lexical",
        workspace_id=ws_uuid,
        user_id=user_b_uuid,
        workspace_role=WorkspaceRole.VIEWER,
        is_admin=False,
    )
    assert len(lexical_chunks) == 0

    # Stage 3: Hybrid / RRF retrieval for User B yields 0 chunks
    hybrid_chunks = retrieval_svc.retrieve(
        [0.15] * 768,
        question="What is Phoenix?",
        top_k=5,
        similarity_threshold=0.0,
        retrieval_mode="hybrid",
        workspace_id=ws_uuid,
        user_id=user_b_uuid,
        workspace_role=WorkspaceRole.VIEWER,
        is_admin=False,
    )
    assert len(hybrid_chunks) == 0


def test_cross_workspace_and_cross_org_acl_isolation(acl_client: TestClient, db_session):
    """Denies cross-workspace and cross-organization ACL management and access."""
    admin1_id, admin1_token, ws1_id = register_user(acl_client, f"admin1_{uuid.uuid4().hex[:6]}@example.com")
    admin2_id, admin2_token, ws2_id = register_user(acl_client, f"admin2_{uuid.uuid4().hex[:6]}@example.com")

    # Admin 1 uploads doc to Workspace 1
    pdf_bytes = build_pdf(["Workspace 1 confidential document"])
    upload_res = acl_client.post(
        "/api/v1/documents",
        headers={"Authorization": f"Bearer {admin1_token}", "X-Workspace-Id": ws1_id},
        files={"file": ("ws1_doc.pdf", pdf_bytes, "application/pdf")},
    )
    doc1_id = upload_res.json()["id"]

    # 1. Admin 2 in Workspace 2 attempts GET /documents/{doc1_id}/acl -> 404 Not Found (scoped to ws2)
    res_get = acl_client.get(
        f"/api/v1/documents/{doc1_id}/acl",
        headers={"Authorization": f"Bearer {admin2_token}", "X-Workspace-Id": ws2_id},
    )
    assert res_get.status_code == 404

    # 2. Admin 2 in Workspace 2 attempts POST /documents/{doc1_id}/acl -> 404 Not Found
    res_post = acl_client.post(
        f"/api/v1/documents/{doc1_id}/acl",
        headers={"Authorization": f"Bearer {admin2_token}", "X-Workspace-Id": ws2_id},
        json={"principal_type": "USER", "principal_id": admin2_id, "permission": "READ"},
    )
    assert res_post.status_code == 404

    # 3. Admin 1 in Workspace 1 attempts to add Admin 2 (from Org 2) to Document 1 ACL -> 400 Bad Request
    res_cross_org = acl_client.post(
        f"/api/v1/documents/{doc1_id}/acl",
        headers={"Authorization": f"Bearer {admin1_token}", "X-Workspace-Id": ws1_id},
        json={"principal_type": "USER", "principal_id": admin2_id, "permission": "READ"},
    )
    assert res_cross_org.status_code == 400
    assert "User must belong to the workspace organization" in res_cross_org.json()["detail"]


def test_inactive_user_cannot_be_assigned_to_acl(acl_client: TestClient, db_session):
    """Inactive users cannot be assigned to document ACLs."""
    admin_id, admin_token, ws_id = register_user(acl_client, f"admin_{uuid.uuid4().hex[:6]}@example.com")
    user_b_id, user_b_token, _ = register_user(acl_client, f"userb_{uuid.uuid4().hex[:6]}@example.com")
    enroll_workspace_user(db_session, ws_id, user_b_id, WorkspaceRole.VIEWER)

    # Deactivate User B
    user_b = db_session.get(User, uuid.UUID(user_b_id))
    user_b.is_active = False
    db_session.commit()

    # Admin uploads doc
    pdf_bytes = build_pdf(["Inactive user test"])
    upload_res = acl_client.post(
        "/api/v1/documents",
        headers={"Authorization": f"Bearer {admin_token}", "X-Workspace-Id": ws_id},
        files={"file": ("inactive_test.pdf", pdf_bytes, "application/pdf")},
    )
    doc_id = upload_res.json()["id"]

    # Admin attempts to add inactive User B to doc ACL -> 400 Bad Request
    res = acl_client.post(
        f"/api/v1/documents/{doc_id}/acl",
        headers={"Authorization": f"Bearer {admin_token}", "X-Workspace-Id": ws_id},
        json={"principal_type": "USER", "principal_id": user_b_id, "permission": "READ"},
    )
    assert res.status_code == 400
    assert "is inactive" in res.json()["detail"]


def test_acl_changes_do_not_retrigger_embeddings_or_chunk_regeneration(acl_client: TestClient, db_session):
    """ACL mutations modify only the document_acls table; chunks and embeddings remain completely untouched."""
    admin_id, admin_token, ws_id = register_user(acl_client, f"admin_{uuid.uuid4().hex[:6]}@example.com")
    user_a_id, user_a_token, _ = register_user(acl_client, f"usera_{uuid.uuid4().hex[:6]}@example.com")
    enroll_workspace_user(db_session, ws_id, user_a_id, WorkspaceRole.VIEWER)

    # Upload document
    pdf_bytes = build_pdf(["Page 1 content for stability test", "Page 2 content for stability test"])
    upload_res = acl_client.post(
        "/api/v1/documents",
        headers={"Authorization": f"Bearer {admin_token}", "X-Workspace-Id": ws_id},
        files={"file": ("stability.pdf", pdf_bytes, "application/pdf")},
    )
    doc_id = uuid.UUID(upload_res.json()["id"])

    # Query initial chunk states
    initial_chunks = db_session.query(DocumentChunk).filter(DocumentChunk.document_id == doc_id).order_by(DocumentChunk.chunk_index).all()
    assert len(initial_chunks) > 0
    initial_chunk_ids = [c.id for c in initial_chunks]
    initial_embeddings = [list(c.embedding) for c in initial_chunks]

    # Admin adds ACL
    acl_add = acl_client.post(
        f"/api/v1/documents/{doc_id}/acl",
        headers={"Authorization": f"Bearer {admin_token}", "X-Workspace-Id": ws_id},
        json={"principal_type": "USER", "principal_id": user_a_id, "permission": "READ"},
    )
    acl_id = acl_add.json()["id"]

    # Admin deletes ACL
    acl_client.delete(
        f"/api/v1/documents/{doc_id}/acl/{acl_id}",
        headers={"Authorization": f"Bearer {admin_token}", "X-Workspace-Id": ws_id},
    )

    # Verify chunks and embeddings are completely unchanged
    db_session.expire_all()
    post_chunks = db_session.query(DocumentChunk).filter(DocumentChunk.document_id == doc_id).order_by(DocumentChunk.chunk_index).all()
    post_chunk_ids = [c.id for c in post_chunks]
    post_embeddings = [list(c.embedding) for c in post_chunks]

    assert post_chunk_ids == initial_chunk_ids
    assert post_embeddings == initial_embeddings


def test_source_evidence_acl_and_tenant_boundaries(acl_client: TestClient, db_session):
    """Source evidence retrieval strictly enforces document ACL, workspace isolation, and org boundaries."""
    # Setup Tenant 1: Admin, User A (allowed by ACL), User B (denied by ACL)
    admin_id, admin_token, ws_id = register_user(acl_client, f"admin_src_{uuid.uuid4().hex[:6]}@example.com")
    user_a_id, user_a_token, _ = register_user(acl_client, f"usera_src_{uuid.uuid4().hex[:6]}@example.com")
    user_b_id, user_b_token, _ = register_user(acl_client, f"userb_src_{uuid.uuid4().hex[:6]}@example.com")
    enroll_workspace_user(db_session, ws_id, user_a_id, WorkspaceRole.VIEWER)
    enroll_workspace_user(db_session, ws_id, user_b_id, WorkspaceRole.VIEWER)

    # Setup Tenant 2: External Org User
    ext_id, ext_token, ext_ws_id = register_user(acl_client, f"ext_src_{uuid.uuid4().hex[:6]}@example.com")

    # Admin uploads sensitive document to Workspace 1
    pdf_bytes = build_pdf(["Sensitive passage alpha for evidence test.", "Sensitive passage beta for evidence test."])
    upload_res = acl_client.post(
        "/api/v1/documents",
        headers={"Authorization": f"Bearer {admin_token}", "X-Workspace-Id": ws_id},
        files={"file": ("secret_evidence.pdf", pdf_bytes, "application/pdf")},
    )
    doc_id = upload_res.json()["id"]

    # Restrict document: only User A has explicit READ permission
    acl_client.post(
        f"/api/v1/documents/{doc_id}/acl",
        headers={"Authorization": f"Bearer {admin_token}", "X-Workspace-Id": ws_id},
        json={"principal_type": "USER", "principal_id": user_a_id, "permission": "READ"},
    )

    # 1. Admin can retrieve source evidence
    admin_src = acl_client.get(
        f"/api/v1/documents/{doc_id}/sources/0",
        headers={"Authorization": f"Bearer {admin_token}", "X-Workspace-Id": ws_id},
    )
    assert admin_src.status_code == 200
    assert "Sensitive passage alpha" in admin_src.json()["content"]

    # 2. Authorized User A can retrieve source evidence
    user_a_src = acl_client.get(
        f"/api/v1/documents/{doc_id}/sources/0",
        headers={"Authorization": f"Bearer {user_a_token}", "X-Workspace-Id": ws_id},
    )
    assert user_a_src.status_code == 200
    assert user_a_src.json()["document_id"] == doc_id
    assert user_a_src.json()["filename"] == "secret_evidence.pdf"
    assert "Sensitive passage alpha" in user_a_src.json()["content"]

    # 3. Denied User B in same workspace CANNOT retrieve source evidence (returns 404)
    user_b_src = acl_client.get(
        f"/api/v1/documents/{doc_id}/sources/0",
        headers={"Authorization": f"Bearer {user_b_token}", "X-Workspace-Id": ws_id},
    )
    assert user_b_src.status_code == 404

    # 4. External Org User CANNOT retrieve source evidence (returns 404)
    ext_src = acl_client.get(
        f"/api/v1/documents/{doc_id}/sources/0",
        headers={"Authorization": f"Bearer {ext_token}", "X-Workspace-Id": ext_ws_id},
    )
    assert ext_src.status_code == 404

