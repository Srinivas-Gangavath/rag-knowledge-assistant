"""Integration and authorization tests for Workspace and Organization management APIs."""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.db.database import get_db
from app.db.models import Organization, OrganizationMembership, OrganizationRole, Workspace, WorkspaceMembership, WorkspaceRole
from app.main import app
from app.repositories.membership_repository import MembershipRepository
from tests.conftest import postgres_available


@pytest.fixture
def ws_client(db_session) -> TestClient:
    if not postgres_available():
        pytest.skip("PostgreSQL is not available for API tests.")

    def override_db():
        yield db_session

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def register_user(client: TestClient, email: str, name: str = "Test User") -> tuple[str, str, str, str]:
    """Helper returning (user_id, token, default_workspace_id, organization_id)."""
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
    org_id = me["workspaces"][0]["organization_id"]
    return user_id, token, ws_id, org_id


def test_workspace_lifecycle_crud(ws_client: TestClient, db_session):
    """Test workspace creation, retrieval, update, archival, and listing."""
    owner_id, owner_token, _, org_id = register_user(
        ws_client, f"ws_owner_{uuid.uuid4().hex[:6]}@example.com", "WS Owner"
    )
    headers = {"Authorization": f"Bearer {owner_token}"}

    # 1. Create a new workspace
    create_res = ws_client.post(
        "/api/v1/workspaces",
        headers=headers,
        json={
            "organization_id": org_id,
            "name": "Research & Development",
            "slug": "rnd",
            "settings": {"retrieval_mode": "hybrid"},
        },
    )
    assert create_res.status_code == 201
    created_ws = create_res.json()
    assert created_ws["name"] == "Research & Development"
    assert created_ws["slug"] == "rnd"
    assert created_ws["is_archived"] is False
    assert created_ws["role"] == "WORKSPACE_ADMIN"
    rnd_id = created_ws["id"]

    # 2. Get workspace details
    get_res = ws_client.get(f"/api/v1/workspaces/{rnd_id}", headers=headers)
    assert get_res.status_code == 200
    assert get_res.json()["id"] == rnd_id

    # 3. Update workspace details
    update_res = ws_client.patch(
        f"/api/v1/workspaces/{rnd_id}",
        headers=headers,
        json={"name": "R&D Advanced", "settings": {"retrieval_mode": "dense"}},
    )
    assert update_res.status_code == 200
    assert update_res.json()["name"] == "R&D Advanced"

    # 4. List workspaces
    list_res = ws_client.get("/api/v1/workspaces", headers=headers)
    assert list_res.status_code == 200
    ws_list = list_res.json()["workspaces"]
    assert any(w["id"] == rnd_id for w in ws_list)

    # 5. Archive workspace (safe lifecycle deletion)
    del_res = ws_client.delete(f"/api/v1/workspaces/{rnd_id}", headers=headers)
    assert del_res.status_code == 204

    # Verify is_archived is True
    get_after = ws_client.get(f"/api/v1/workspaces/{rnd_id}", headers=headers)
    assert get_after.json()["is_archived"] is True


def test_workspace_membership_management(ws_client: TestClient, db_session):
    """Test adding, listing, updating role, and removing workspace members."""
    admin_id, admin_token, ws_id, org_id = register_user(
        ws_client, f"admin_mem_{uuid.uuid4().hex[:6]}@example.com", "Admin Mem"
    )
    user_id, _, _, _ = register_user(
        ws_client, f"collab_{uuid.uuid4().hex[:6]}@example.com", "Collaborator"
    )
    admin_headers = {"Authorization": f"Bearer {admin_token}"}

    # First add user to organization as MEMBER
    add_org_mem = ws_client.post(
        f"/api/v1/organizations/{org_id}/members",
        headers=admin_headers,
        json={"user_id": user_id, "role": "MEMBER"},
    )
    assert add_org_mem.status_code == 201

    # 1. Add collaborator to workspace as VIEWER
    add_ws_mem = ws_client.post(
        f"/api/v1/workspaces/{ws_id}/members",
        headers=admin_headers,
        json={"user_id": user_id, "role": "VIEWER"},
    )
    assert add_ws_mem.status_code == 201
    assert add_ws_mem.json()["role"] == "VIEWER"

    # 2. List workspace members
    list_res = ws_client.get(f"/api/v1/workspaces/{ws_id}/members", headers=admin_headers)
    assert list_res.status_code == 200
    members = list_res.json()["members"]
    assert len(members) >= 2
    assert any(m["user_id"] == user_id and m["role"] == "VIEWER" for m in members)

    # 3. Update collaborator role to CONTRIBUTOR
    patch_mem = ws_client.patch(
        f"/api/v1/workspaces/{ws_id}/members/{user_id}",
        headers=admin_headers,
        json={"role": "CONTRIBUTOR"},
    )
    assert patch_mem.status_code == 200
    assert patch_mem.json()["role"] == "CONTRIBUTOR"

    # 4. Remove collaborator from workspace
    del_mem = ws_client.delete(f"/api/v1/workspaces/{ws_id}/members/{user_id}", headers=admin_headers)
    assert del_mem.status_code == 204

    # Verify removal
    list_after = ws_client.get(f"/api/v1/workspaces/{ws_id}/members", headers=admin_headers)
    assert not any(m["user_id"] == user_id for m in list_after.json()["members"])


def test_organization_membership_management(ws_client: TestClient, db_session):
    """Test listing org members, updating org roles, and removing org members."""
    owner_id, owner_token, _, org_id = register_user(
        ws_client, f"org_owner_{uuid.uuid4().hex[:6]}@example.com", "Org Owner"
    )
    member_id, _, _, _ = register_user(
        ws_client, f"org_member_{uuid.uuid4().hex[:6]}@example.com", "Org Member"
    )
    owner_headers = {"Authorization": f"Bearer {owner_token}"}

    # 1. Add member to organization
    add_res = ws_client.post(
        f"/api/v1/organizations/{org_id}/members",
        headers=owner_headers,
        json={"user_id": member_id, "role": "MEMBER"},
    )
    assert add_res.status_code == 201
    assert add_res.json()["role"] == "MEMBER"

    # 2. List organization members
    list_res = ws_client.get(f"/api/v1/organizations/{org_id}/members", headers=owner_headers)
    assert list_res.status_code == 200
    members = list_res.json()["members"]
    assert any(m["user_id"] == member_id for m in members)

    # 3. Promote member to ADMIN
    patch_res = ws_client.patch(
        f"/api/v1/organizations/{org_id}/members/{member_id}",
        headers=owner_headers,
        json={"role": "ADMIN"},
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["role"] == "ADMIN"

    # 4. Remove member
    del_res = ws_client.delete(f"/api/v1/organizations/{org_id}/members/{member_id}", headers=owner_headers)
    assert del_res.status_code == 204

    # Verify member is removed
    list_after = ws_client.get(f"/api/v1/organizations/{org_id}/members", headers=owner_headers)
    assert not any(m["user_id"] == member_id for m in list_after.json()["members"])
