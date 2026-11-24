"""Pydantic schemas for Document Access Control Lists (ACL)."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import DocumentPermission, PrincipalType


class DocumentAclCreate(BaseModel):
    principal_type: PrincipalType = Field(default=PrincipalType.USER, description="Type of principal: USER or WORKSPACE_ROLE")
    principal_id: str = Field(..., min_length=1, max_length=255, description="UUID string or email for USER, or role name (e.g. VIEWER) for WORKSPACE_ROLE")
    permission: DocumentPermission = Field(default=DocumentPermission.READ, description="Permission granted: READ, WRITE, or ADMIN")


class DocumentAclItem(BaseModel):
    id: UUID
    document_id: UUID
    principal_type: PrincipalType
    principal_id: str
    permission: DocumentPermission
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DocumentAclListResponse(BaseModel):
    acls: list[DocumentAclItem]
