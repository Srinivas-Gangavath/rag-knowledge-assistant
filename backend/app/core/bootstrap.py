"""Idempotent bootstrap utility for creating the initial administrator.

Associates the bootstrapped user as OWNER of the Default Organization
and WORKSPACE_ADMIN of the Default Workspace.
Never exposes default credentials or writes plaintext passwords to migrations.
"""

from __future__ import annotations

import argparse
import sys
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.security import hash_password
from app.db.database import SessionLocal
from app.db.models import (
    Organization,
    OrganizationMembership,
    OrganizationRole,
    User,
    Workspace,
    WorkspaceMembership,
    WorkspaceRole,
)

logger = get_logger(__name__)


def bootstrap_default_admin(
    session: Session,
    *,
    email: str | None = None,
    password: str | None = None,
    full_name: str | None = None,
) -> User | None:
    """Ensure an administrator user exists and has owner/admin membership in the default tenancy.

    Safe, explicit, and idempotent. If no email or password is provided or configured in
    environment settings, this function safely does nothing.
    """
    settings = get_settings()
    target_email = (email or settings.bootstrap_admin_email or "").strip().lower()
    target_password = password or settings.bootstrap_admin_password
    target_name = (full_name or settings.bootstrap_admin_name or "Default Administrator").strip()

    if not target_email or not target_password:
        logger.debug("No bootstrap admin credentials provided; skipping admin bootstrap")
        return None

    # 1. Resolve or create user
    user = session.scalars(select(User).where(User.email == target_email)).first()
    if user is None:
        user = User(
            email=target_email,
            hashed_password=hash_password(target_password),
            full_name=target_name,
            is_active=True,
        )
        session.add(user)
        session.flush()
        logger.info("Created bootstrap admin user: %s (id=%s)", target_email, user.id)
    else:
        logger.debug("Bootstrap admin user already exists: %s (id=%s)", target_email, user.id)

    # 2. Resolve default organization
    default_org = session.scalars(
        select(Organization).where(Organization.slug == "default")
    ).first()
    if default_org is None:
        default_org = Organization(name="Default Organization", slug="default")
        session.add(default_org)
        session.flush()
        logger.info("Created Default Organization (id=%s)", default_org.id)

    # 3. Ensure OWNER membership in default organization
    org_membership = session.scalars(
        select(OrganizationMembership).where(
            OrganizationMembership.organization_id == default_org.id,
            OrganizationMembership.user_id == user.id,
        )
    ).first()
    if org_membership is None:
        org_membership = OrganizationMembership(
            organization_id=default_org.id,
            user_id=user.id,
            role=OrganizationRole.OWNER,
        )
        session.add(org_membership)
        session.flush()
        logger.info("Granted OWNER role on Default Organization to %s", target_email)

    # 4. Resolve default workspace
    default_ws = session.scalars(
        select(Workspace).where(
            Workspace.organization_id == default_org.id,
            Workspace.slug == "default",
        )
    ).first()
    if default_ws is None:
        default_ws = Workspace(
            organization_id=default_org.id,
            name="Default Workspace",
            slug="default",
            settings={},
        )
        session.add(default_ws)
        session.flush()
        logger.info("Created Default Workspace (id=%s)", default_ws.id)

    # 5. Ensure WORKSPACE_ADMIN membership in default workspace
    ws_membership = session.scalars(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == default_ws.id,
            WorkspaceMembership.user_id == user.id,
        )
    ).first()
    if ws_membership is None:
        ws_membership = WorkspaceMembership(
            workspace_id=default_ws.id,
            user_id=user.id,
            role=WorkspaceRole.WORKSPACE_ADMIN,
        )
        session.add(ws_membership)
        session.flush()
        logger.info("Granted WORKSPACE_ADMIN role on Default Workspace to %s", target_email)

    session.commit()
    return user


def main() -> None:
    """CLI entry point: python -m app.core.bootstrap [--email ...] [--password ...] [--name ...]"""
    parser = argparse.ArgumentParser(description="Bootstrap default administrator user.")
    parser.add_argument("--email", help="Administrator email address")
    parser.add_argument("--password", help="Administrator password")
    parser.add_argument("--name", help="Administrator display name")

    args = parser.parse_args()

    with SessionLocal() as session:
        user = bootstrap_default_admin(
            session,
            email=args.email,
            password=args.password,
            full_name=args.name,
        )
        if user:
            print(f"Bootstrap complete: {user.email} (user_id={user.id})")
        else:
            print(
                "Bootstrap skipped: email and password must be supplied via CLI flags "
                "or BOOTSTRAP_ADMIN_EMAIL and BOOTSTRAP_ADMIN_PASSWORD environment variables."
            )
            sys.exit(1)


if __name__ == "__main__":
    main()
