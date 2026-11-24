"""Pydantic schemas for Audit Logging API."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AuditLogItem(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    organization_id: UUID
    workspace_id: UUID | None = None
    actor_user_id: UUID | None = None
    actor_email_snapshot: str | None = None
    event_type: str
    action: str
    outcome: str
    resource_type: str | None = None
    resource_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, alias="metadata_")
    ip_address: str | None = None
    user_agent: str | None = None
    request_id: str | None = None
    created_at: datetime
    previous_hash: str | None = None
    event_hash: str


class AuditLogListResponse(BaseModel):
    items: list[AuditLogItem]
    total: int
    page: int
    page_size: int
    has_more: bool


class AuditLogVerifyResponse(BaseModel):
    is_valid: bool
    events_verified: int
    message: str
    error_detail: str | None = None
