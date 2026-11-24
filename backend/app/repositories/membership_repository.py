"""Database access for OrganizationMembership and WorkspaceMembership records."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.db.models import (
    OrganizationMembership,
    OrganizationRole,
    Workspace,
    WorkspaceMembership,
    WorkspaceRole,
)


class MembershipRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    # Organization memberships
    def add_organization_membership(
        self,
        membership: OrganizationMembership,
    ) -> OrganizationMembership:
        self._session.add(membership)
        self._session.flush()
        return membership

    def get_organization_membership(
        self,
        organization_id: UUID,
        user_id: UUID,
    ) -> OrganizationMembership | None:
        statement = select(OrganizationMembership).where(
            OrganizationMembership.organization_id == organization_id,
            OrganizationMembership.user_id == user_id,
        )
        return self._session.scalars(statement).first()

    def list_user_organizations(
        self,
        user_id: UUID,
    ) -> list[OrganizationMembership]:
        statement = (
            select(OrganizationMembership)
            .options(joinedload(OrganizationMembership.organization))
            .where(OrganizationMembership.user_id == user_id)
            .order_by(OrganizationMembership.created_at.asc())
        )
        return list(self._session.scalars(statement))

    def list_organization_members(
        self,
        organization_id: UUID,
    ) -> list[OrganizationMembership]:
        statement = (
            select(OrganizationMembership)
            .options(joinedload(OrganizationMembership.user))
            .where(OrganizationMembership.organization_id == organization_id)
            .order_by(OrganizationMembership.created_at.asc())
        )
        return list(self._session.scalars(statement))

    def count_organization_owners(self, organization_id: UUID) -> int:
        statement = (
            select(func.count())
            .select_from(OrganizationMembership)
            .where(
                OrganizationMembership.organization_id == organization_id,
                OrganizationMembership.role == OrganizationRole.OWNER,
            )
        )
        return self._session.scalar(statement) or 0

    def update_organization_role(
        self,
        organization_id: UUID,
        user_id: UUID,
        new_role: OrganizationRole,
    ) -> OrganizationMembership | None:
        membership = self.get_organization_membership(organization_id, user_id)
        if membership is None:
            return None
        membership.role = new_role
        self._session.flush()
        return membership

    def delete_organization_membership(
        self,
        organization_id: UUID,
        user_id: UUID,
    ) -> bool:
        membership = self.get_organization_membership(organization_id, user_id)
        if membership is None:
            return False
        # Clean up any workspace memberships belonging to this org
        ws_memberships = self._session.scalars(
            select(WorkspaceMembership)
            .join(Workspace, Workspace.id == WorkspaceMembership.workspace_id)
            .where(
                Workspace.organization_id == organization_id,
                WorkspaceMembership.user_id == user_id,
            )
        ).all()
        for wm in ws_memberships:
            self._session.delete(wm)

        self._session.delete(membership)
        self._session.flush()
        return True

    # Workspace memberships
    def add_workspace_membership(
        self,
        membership: WorkspaceMembership,
    ) -> WorkspaceMembership:
        self._session.add(membership)
        self._session.flush()
        return membership

    def get_workspace_membership(
        self,
        workspace_id: UUID,
        user_id: UUID,
    ) -> WorkspaceMembership | None:
        statement = select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == workspace_id,
            WorkspaceMembership.user_id == user_id,
        )
        return self._session.scalars(statement).first()

    def list_user_workspaces(
        self,
        user_id: UUID,
    ) -> list[WorkspaceMembership]:
        statement = (
            select(WorkspaceMembership)
            .options(
                joinedload(WorkspaceMembership.workspace),
            )
            .where(WorkspaceMembership.user_id == user_id)
            .order_by(WorkspaceMembership.created_at.asc())
        )
        return list(self._session.scalars(statement))

    def list_workspace_members(
        self,
        workspace_id: UUID,
    ) -> list[WorkspaceMembership]:
        statement = (
            select(WorkspaceMembership)
            .options(joinedload(WorkspaceMembership.user))
            .where(WorkspaceMembership.workspace_id == workspace_id)
            .order_by(WorkspaceMembership.created_at.asc())
        )
        return list(self._session.scalars(statement))

    def update_workspace_role(
        self,
        workspace_id: UUID,
        user_id: UUID,
        new_role: WorkspaceRole,
    ) -> WorkspaceMembership | None:
        membership = self.get_workspace_membership(workspace_id, user_id)
        if membership is None:
            return None
        membership.role = new_role
        self._session.flush()
        return membership

    def delete_workspace_membership(
        self,
        workspace_id: UUID,
        user_id: UUID,
    ) -> bool:
        membership = self.get_workspace_membership(workspace_id, user_id)
        if membership is None:
            return False
        self._session.delete(membership)
        self._session.flush()
        return True
