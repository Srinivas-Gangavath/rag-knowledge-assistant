"""Database access for Workspace records."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import OrganizationMembership, OrganizationRole, Workspace, WorkspaceMembership


class WorkspaceRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, workspace: Workspace) -> Workspace:
        self._session.add(workspace)
        self._session.flush()
        return workspace

    def update(self, workspace: Workspace) -> Workspace:
        self._session.flush()
        return workspace

    def get_by_id(self, workspace_id: UUID) -> Workspace | None:
        return self._session.get(Workspace, workspace_id)

    def get_by_slug(self, organization_id: UUID, slug: str) -> Workspace | None:
        statement = select(Workspace).where(
            Workspace.organization_id == organization_id,
            Workspace.slug == slug,
        )
        return self._session.scalars(statement).first()

    def get_default(self) -> Workspace | None:
        statement = select(Workspace).where(Workspace.slug == "default").limit(1)
        return self._session.scalars(statement).first()

    def list_by_organization(self, organization_id: UUID) -> list[Workspace]:
        statement = (
            select(Workspace)
            .where(Workspace.organization_id == organization_id)
            .order_by(Workspace.created_at.asc())
        )
        return list(self._session.scalars(statement))

    def archive(self, workspace_id: UUID) -> Workspace | None:
        workspace = self.get_by_id(workspace_id)
        if workspace is None:
            return None
        workspace.is_archived = True
        self._session.flush()
        return workspace

    def delete(self, workspace_id: UUID) -> bool:
        workspace = self.get_by_id(workspace_id)
        if workspace is None:
            return False
        self._session.delete(workspace)
        self._session.flush()
        return True

    def list_accessible_workspaces(self, user_id: UUID) -> list[tuple[Workspace, str]]:
        """List all workspaces accessible to the user with their effective role."""
        results: dict[UUID, tuple[Workspace, str]] = {}

        # 1. Workspaces with direct membership
        stmt = (
            select(Workspace, WorkspaceMembership.role)
            .join(WorkspaceMembership, WorkspaceMembership.workspace_id == Workspace.id)
            .where(WorkspaceMembership.user_id == user_id)
            .order_by(Workspace.created_at.asc())
        )
        for ws, role in self._session.execute(stmt):
            results[ws.id] = (ws, role.value if hasattr(role, "value") else str(role))

        # 2. Workspaces in organizations where user is OWNER or ADMIN
        org_stmt = (
            select(Workspace, OrganizationMembership.role)
            .join(
                OrganizationMembership,
                OrganizationMembership.organization_id == Workspace.organization_id,
            )
            .where(
                OrganizationMembership.user_id == user_id,
                OrganizationMembership.role.in_([OrganizationRole.OWNER, OrganizationRole.ADMIN]),
            )
            .order_by(Workspace.created_at.asc())
        )
        for ws, org_role in self._session.execute(org_stmt):
            if ws.id not in results or org_role == OrganizationRole.OWNER:
                results[ws.id] = (ws, "WORKSPACE_ADMIN")

        return list(results.values())
