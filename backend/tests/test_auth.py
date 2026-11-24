"""Unit and integration tests for User, security, tokens, memberships, and bootstrap."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from app.core.bootstrap import bootstrap_default_admin
from app.core.security import (
    create_access_token,
    decode_access_token,
    generate_refresh_token,
    hash_password,
    hash_token,
    verify_password,
)
from app.db.models import (
    Organization,
    OrganizationMembership,
    OrganizationRole,
    RefreshToken,
    User,
    Workspace,
    WorkspaceMembership,
    WorkspaceRole,
)
from app.repositories.membership_repository import MembershipRepository
from app.repositories.organization_repository import OrganizationRepository
from app.repositories.refresh_token_repository import RefreshTokenRepository
from app.repositories.user_repository import UserRepository
from app.repositories.workspace_repository import WorkspaceRepository


def test_password_hash_not_plaintext():
    plain = "SuperSecretPassword123!"
    hashed = hash_password(plain)

    assert hashed != plain
    assert hashed.startswith("$argon2id$")
    assert verify_password(plain, hashed) is True
    assert verify_password("WrongPassword123!", hashed) is False


def test_user_creation_and_email_normalization(db_session):
    repo = UserRepository(db_session)
    email = f"  Alice.{uuid.uuid4().hex[:6]}@Example.COM  "
    user = User(
        email=email,
        hashed_password=hash_password("ValidPassword123"),
        full_name="Alice Anderson",
    )
    saved = repo.add(user)

    assert saved.id is not None
    assert saved.email == email.strip().lower()
    assert saved.is_active is True
    assert saved.created_at is not None

    found = repo.get_by_email(email)
    assert found is not None
    assert found.id == saved.id


def test_duplicate_email_rejected(db_session):
    repo = UserRepository(db_session)
    email = f"bob.{uuid.uuid4().hex[:6]}@example.com"
    user1 = User(
        email=email,
        hashed_password=hash_password("Password123"),
        full_name="Bob One",
    )
    repo.add(user1)

    user2 = User(
        email=email,
        hashed_password=hash_password("Password456"),
        full_name="Bob Two",
    )
    with pytest.raises(IntegrityError):
        repo.add(user2)
    db_session.rollback()


def test_access_token_validation():
    user_id = uuid.uuid4()
    email = "carol@example.com"
    token = create_access_token(user_id, email, expires_delta=timedelta(minutes=15))

    claims = decode_access_token(token)
    assert claims is not None
    assert claims["sub"] == str(user_id)
    assert claims["email"] == email
    assert claims["type"] == "access"


def test_expired_access_token():
    user_id = uuid.uuid4()
    email = "expired@example.com"
    # Issue a token that expired 1 minute ago
    token = create_access_token(user_id, email, expires_delta=timedelta(minutes=-1))

    claims = decode_access_token(token)
    assert claims is None


def test_refresh_token_hashing_and_rotation(db_session):
    user_repo = UserRepository(db_session)
    token_repo = RefreshTokenRepository(db_session)

    user = user_repo.add(
        User(
            email=f"token.{uuid.uuid4().hex[:6]}@example.com",
            hashed_password=hash_password("Password123"),
            full_name="Token User",
        )
    )

    raw_token = generate_refresh_token()
    token_hash = hash_token(raw_token)

    # Raw token must NOT equal the stored hash
    assert raw_token != token_hash
    assert len(token_hash) == 64

    expires_at = datetime.now(timezone.utc) + timedelta(days=7)
    record = token_repo.create(user_id=user.id, token_hash=token_hash, expires_at=expires_at)
    assert record.id is not None
    assert record.token_hash == token_hash
    assert record.revoked_at is None

    # Revoke session
    revoked = token_repo.revoke(token_hash)
    assert revoked is True

    updated = token_repo.get_by_hash(token_hash)
    assert updated is not None
    assert updated.revoked_at is not None


def test_user_org_membership(db_session):
    user_repo = UserRepository(db_session)
    org_repo = OrganizationRepository(db_session)
    mem_repo = MembershipRepository(db_session)

    user = user_repo.add(
        User(
            email=f"org_mem_{uuid.uuid4().hex[:6]}@example.com",
            hashed_password=hash_password("Pass123!"),
            full_name="Org Member",
        )
    )
    org = org_repo.add(
        Organization(name="Engineering Org", slug=f"eng-{uuid.uuid4().hex[:6]}")
    )

    mem = mem_repo.add_organization_membership(
        OrganizationMembership(
            organization_id=org.id,
            user_id=user.id,
            role=OrganizationRole.OWNER,
        )
    )
    assert mem.id is not None
    assert mem.role == OrganizationRole.OWNER

    user_orgs = mem_repo.list_user_organizations(user.id)
    assert len(user_orgs) == 1
    assert user_orgs[0].organization_id == org.id


def test_user_workspace_membership(db_session):
    user_repo = UserRepository(db_session)
    org_repo = OrganizationRepository(db_session)
    ws_repo = WorkspaceRepository(db_session)
    mem_repo = MembershipRepository(db_session)

    user = user_repo.add(
        User(
            email=f"ws_mem_{uuid.uuid4().hex[:6]}@example.com",
            hashed_password=hash_password("Pass123!"),
            full_name="WS Member",
        )
    )
    org = org_repo.add(
        Organization(name="WS Org", slug=f"ws-org-{uuid.uuid4().hex[:6]}")
    )
    ws = ws_repo.add(
        Workspace(organization_id=org.id, name="Dev WS", slug="dev-ws")
    )

    mem = mem_repo.add_workspace_membership(
        WorkspaceMembership(
            workspace_id=ws.id,
            user_id=user.id,
            role=WorkspaceRole.WORKSPACE_ADMIN,
        )
    )
    assert mem.id is not None
    assert mem.role == WorkspaceRole.WORKSPACE_ADMIN

    user_workspaces = mem_repo.list_user_workspaces(user.id)
    assert len(user_workspaces) == 1
    assert user_workspaces[0].workspace_id == ws.id


def test_duplicate_membership_rejected(db_session):
    user_repo = UserRepository(db_session)
    org_repo = OrganizationRepository(db_session)
    mem_repo = MembershipRepository(db_session)

    user = user_repo.add(
        User(
            email=f"dup_mem_{uuid.uuid4().hex[:6]}@example.com",
            hashed_password=hash_password("Pass123!"),
            full_name="Dup Member",
        )
    )
    org = org_repo.add(
        Organization(name="Dup Org", slug=f"dup-{uuid.uuid4().hex[:6]}")
    )

    mem_repo.add_organization_membership(
        OrganizationMembership(
            organization_id=org.id,
            user_id=user.id,
            role=OrganizationRole.MEMBER,
        )
    )

    # Duplicate must fail on unique constraint
    with pytest.raises(IntegrityError):
        mem_repo.add_organization_membership(
            OrganizationMembership(
                organization_id=org.id,
                user_id=user.id,
                role=OrganizationRole.ADMIN,
            )
        )
    db_session.rollback()


def test_workspace_belongs_to_org(db_session):
    org_repo = OrganizationRepository(db_session)
    ws_repo = WorkspaceRepository(db_session)

    org1 = org_repo.add(Organization(name="Org One", slug=f"org1-{uuid.uuid4().hex[:6]}"))
    org2 = org_repo.add(Organization(name="Org Two", slug=f"org2-{uuid.uuid4().hex[:6]}"))

    ws = ws_repo.add(Workspace(organization_id=org1.id, name="WS 1", slug="ws-1"))

    assert ws.organization_id == org1.id
    assert ws.organization_id != org2.id


def test_bootstrap_default_admin(db_session):
    admin_email = f"bootstrap_admin_{uuid.uuid4().hex[:6]}@example.com"
    admin_pass = "SecureAdminPass123!"

    user = bootstrap_default_admin(
        db_session,
        email=admin_email,
        password=admin_pass,
        full_name="Bootstrap Admin",
    )
    assert user is not None
    assert user.email == admin_email
    assert verify_password(admin_pass, user.hashed_password) is True

    # Check memberships in default org and workspace
    mem_repo = MembershipRepository(db_session)
    orgs = mem_repo.list_user_organizations(user.id)
    assert any(m.role == OrganizationRole.OWNER and m.organization.slug == "default" for m in orgs)

    workspaces = mem_repo.list_user_workspaces(user.id)
    assert any(
        m.role == WorkspaceRole.WORKSPACE_ADMIN and m.workspace.slug == "default"
        for m in workspaces
    )

    # Idempotent call should not fail
    user_repeat = bootstrap_default_admin(
        db_session,
        email=admin_email,
        password=admin_pass,
        full_name="Bootstrap Admin",
    )
    assert user_repeat.id == user.id
