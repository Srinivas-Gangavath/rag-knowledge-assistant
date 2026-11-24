"""Pydantic schemas for Organization and Workspace membership management."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.db.models import OrganizationRole, WorkspaceRole


class OrgMemberResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    organization_id: UUID
    email: str
    full_name: str
    role: str
    created_at: datetime


class OrgMemberListResponse(BaseModel):
    members: list[OrgMemberResponse]


class OrgMemberAddRequest(BaseModel):
    user_id: UUID | None = None
    email: str | None = None
    role: OrganizationRole = OrganizationRole.MEMBER


class OrgMemberRoleUpdateRequest(BaseModel):
    role: OrganizationRole


class WorkspaceMemberResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    workspace_id: UUID
    email: str
    full_name: str
    role: str
    created_at: datetime


class WorkspaceMemberListResponse(BaseModel):
    members: list[WorkspaceMemberResponse]


class WorkspaceMemberAddRequest(BaseModel):
    user_id: UUID | None = None
    email: str | None = None
    role: WorkspaceRole = WorkspaceRole.CONTRIBUTOR


class WorkspaceMemberRoleUpdateRequest(BaseModel):
    role: WorkspaceRole
