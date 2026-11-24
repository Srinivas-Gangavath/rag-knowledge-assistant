"""Workspace context foundation for tenancy resolution.

In Phase 1.1, the application is single-tenant and unauthenticated.
This module provides a deterministic workspace context provider that resolves
the default bootstrap workspace without trusting arbitrary client input.
In Phase 1.2+, this will resolve from authenticated user principals and memberships.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.permissions import Permission
from app.db.models import OrganizationRole, WorkspaceRole


@dataclass(frozen=True)
class WorkspaceContext:
    workspace_id: UUID
    organization_id: UUID
    workspace_slug: str
    organization_slug: str
    user_id: UUID | None = None
    workspace_role: WorkspaceRole | None = None
    organization_role: OrganizationRole | None = None
    permissions: frozenset[Permission] = field(default_factory=frozenset)

    def can(self, permission: Permission) -> bool:
        """Check if this workspace context has the specified permission."""
        return permission in self.permissions


class WorkspaceContextProvider:
    """Resolves active workspace context.

    Provides deterministic fallback to the bootstrap organization/workspace
    for single-tenant compatibility.
    """

    DEFAULT_WORKSPACE_SLUG = "default"
    DEFAULT_ORG_SLUG = "default"

    @classmethod
    def get_default_workspace(cls, session: Session):
        from app.db.models import Organization, Workspace

        statement = select(Workspace).where(Workspace.slug == cls.DEFAULT_WORKSPACE_SLUG).limit(1)
        workspace = session.scalars(statement).first()
        if workspace is None:
            org_stmt = (
                select(Organization).where(Organization.slug == cls.DEFAULT_ORG_SLUG).limit(1)
            )
            org = session.scalars(org_stmt).first()
            if org is None:
                org = Organization(name="Default Organization", slug=cls.DEFAULT_ORG_SLUG)
                session.add(org)
                session.flush()
            workspace = Workspace(
                organization_id=org.id,
                name="Default Workspace",
                slug=cls.DEFAULT_WORKSPACE_SLUG,
                settings={},
            )
            session.add(workspace)
            session.flush()
        return workspace

    @classmethod
    def get_default_workspace_id(cls, session: Session) -> UUID:
        workspace = cls.get_default_workspace(session)
        return workspace.id

    @classmethod
    def get_context(cls, session: Session) -> WorkspaceContext:
        workspace = cls.get_default_workspace(session)
        org_slug = (
            workspace.organization.slug
            if workspace.organization is not None
            else cls.DEFAULT_ORG_SLUG
        )
        return WorkspaceContext(
            workspace_id=workspace.id,
            organization_id=workspace.organization_id,
            workspace_slug=workspace.slug,
            organization_slug=org_slug,
        )
