"""API tests for authentication, boundaries, and cross-workspace security isolation."""

from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.db.database import get_db
from app.db.models import Document, DocumentStatus, OrganizationRole, WorkspaceRole
from app.main import app
from app.repositories.document_repository import DocumentRepository
from app.services.conversation_service import ConversationService
from tests.conftest import make_settings, postgres_available


@pytest.fixture
def auth_client(db_session) -> TestClient:
    if not postgres_available():
        pytest.skip("PostgreSQL is not available for API tests.")

    def override_db():
        yield db_session

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def test_register_user(auth_client: TestClient):
    email = f"register_{uuid.uuid4().hex[:6]}@example.com"
    response = auth_client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "SecurePassword123!",
            "full_name": "Test Register User",
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert "access_token" in body
    assert body["token_type"] == "bearer"
    assert body["user"]["email"] == email.lower()
    assert body["user"]["full_name"] == "Test Register User"
    assert get_settings().auth_cookie_name in response.cookies


def test_duplicate_email_registration_fails(auth_client: TestClient):
    email = f"dup_reg_{uuid.uuid4().hex[:6]}@example.com"
    res1 = auth_client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "Password123!",
            "full_name": "First User",
        },
    )
    assert res1.status_code == 201

    res2 = auth_client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "Password123!",
            "full_name": "Second User",
        },
    )
    assert res2.status_code == 400
    assert "already exists" in res2.json()["detail"]


def test_login_success(auth_client: TestClient):
    email = f"login_{uuid.uuid4().hex[:6]}@example.com"
    password = "CorrectPassword123!"
    auth_client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "full_name": "Login User"},
    )

    response = auth_client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert response.status_code == 200
    body = response.json()
    assert "access_token" in body
    assert get_settings().auth_cookie_name in response.cookies


def test_login_invalid_credentials(auth_client: TestClient):
    email = f"invalid_{uuid.uuid4().hex[:6]}@example.com"
    # Non-existent user
    res1 = auth_client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "WrongPassword!"},
    )
    assert res1.status_code == 401
    assert "Invalid email or password" in res1.json()["detail"]

    # Existing user with wrong password
    auth_client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "GoodPassword123!", "full_name": "Valid User"},
    )
    res2 = auth_client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "BadPassword123!"},
    )
    assert res2.status_code == 401
    assert "Invalid email or password" in res2.json()["detail"]


def test_refresh_token_rotation(auth_client: TestClient):
    email = f"refresh_{uuid.uuid4().hex[:6]}@example.com"
    reg_res = auth_client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "Password123!", "full_name": "Refresh User"},
    )
    cookie_name = get_settings().auth_cookie_name
    initial_cookie = reg_res.cookies.get(cookie_name)
    assert initial_cookie is not None

    # Call refresh endpoint with the cookie
    refresh_res = auth_client.post("/api/v1/auth/refresh")
    assert refresh_res.status_code == 200
    new_body = refresh_res.json()
    assert "access_token" in new_body

    rotated_cookie = refresh_res.cookies.get(cookie_name)
    assert rotated_cookie is not None
    assert rotated_cookie != initial_cookie


def test_logout_revokes_session(auth_client: TestClient):
    email = f"logout_{uuid.uuid4().hex[:6]}@example.com"
    auth_client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "Password123!", "full_name": "Logout User"},
    )

    logout_res = auth_client.post("/api/v1/auth/logout")
    assert logout_res.status_code == 204

    # Subsequent refresh must fail
    refresh_res = auth_client.post("/api/v1/auth/refresh")
    assert refresh_res.status_code == 401


def test_get_me(auth_client: TestClient):
    email = f"me_{uuid.uuid4().hex[:6]}@example.com"
    reg = auth_client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "Password123!", "full_name": "Me User"},
    )
    token = reg.json()["access_token"]

    response = auth_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    me = response.json()
    assert me["email"] == email
    assert me["full_name"] == "Me User"
    assert len(me["organizations"]) >= 1
    assert me["organizations"][0]["role"] == "OWNER"
    assert len(me["workspaces"]) >= 1
    assert me["workspaces"][0]["role"] == "WORKSPACE_ADMIN"


def test_unauthenticated_boundaries_denied(auth_client: TestClient):
    """Verify that operational APIs reject unauthenticated requests with 401."""
    # Health remains public
    health_res = auth_client.get("/api/v1/health")
    assert health_res.status_code == 200

    # Documents requires auth
    docs_res = auth_client.get("/api/v1/documents")
    assert docs_res.status_code == 401

    # Conversations requires auth
    convs_res = auth_client.get("/api/v1/conversations")
    assert convs_res.status_code == 401

    # Chat requires auth
    chat_res = auth_client.post("/api/v1/chat", json={"question": "Hello?"})
    assert chat_res.status_code == 401


def test_arbitrary_workspace_id_denied(auth_client: TestClient):
    """Users cannot access arbitrary workspace IDs they do not belong to."""
    email = f"arbitrary_ws_{uuid.uuid4().hex[:6]}@example.com"
    reg = auth_client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "Password123!", "full_name": "User Arb"},
    )
    token = reg.json()["access_token"]

    fake_ws_id = str(uuid.uuid4())
    response = auth_client.get(
        "/api/v1/documents",
        headers={
            "Authorization": f"Bearer {token}",
            "X-Workspace-Id": fake_ws_id,
        },
    )
    assert response.status_code == 403
    assert "access" in response.json()["detail"].lower()


def test_cross_workspace_isolation(auth_client: TestClient, db_session):
    """Verify that User A in Workspace A cannot access resources in Workspace B."""
    # Register User A
    user_a_email = f"user_a_{uuid.uuid4().hex[:6]}@example.com"
    res_a = auth_client.post(
        "/api/v1/auth/register",
        json={"email": user_a_email, "password": "Password123!", "full_name": "User A"},
    )
    token_a = res_a.json()["access_token"]
    me_a = auth_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token_a}"},
    ).json()
    ws_a_id = me_a["workspaces"][0]["id"]

    # Register User B
    user_b_email = f"user_b_{uuid.uuid4().hex[:6]}@example.com"
    res_b = auth_client.post(
        "/api/v1/auth/register",
        json={"email": user_b_email, "password": "Password123!", "full_name": "User B"},
    )
    token_b = res_b.json()["access_token"]
    me_b = auth_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token_b}"},
    ).json()
    ws_b_id = me_b["workspaces"][0]["id"]

    # 1. User A tries to switch to Workspace B via header -> 403
    cross_res = auth_client.get(
        "/api/v1/documents",
        headers={
            "Authorization": f"Bearer {token_a}",
            "X-Workspace-Id": ws_b_id,
        },
    )
    assert cross_res.status_code == 403

    # 2. Insert a document into Workspace B
    doc_repo = DocumentRepository(db_session)
    doc_b = doc_repo.add(
        Document(
            workspace_id=uuid.UUID(ws_b_id),
            filename="secret_b.pdf",
            original_filename="secret_b.pdf",
            file_path="/storage/secret_b.pdf",
            file_type="application/pdf",
            file_size=512,
            status=DocumentStatus.COMPLETED,
        )
    )

    # 3. User A tries to access Document B directly -> 404 (not in User A's workspace)
    doc_get_res = auth_client.get(
        f"/api/v1/documents/{doc_b.id}",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert doc_get_res.status_code == 404

    # 4. Create conversation in Workspace B
    conv_b_res = auth_client.post(
        "/api/v1/conversations",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert conv_b_res.status_code == 201
    conv_b_id = conv_b_res.json()["id"]

    # 5. User A tries to access Conversation B -> 404
    conv_get_res = auth_client.get(
        f"/api/v1/conversations/{conv_b_id}",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert conv_get_res.status_code == 404
