"""Pydantic schemas for Workspace management."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator


class WorkspaceCreateRequest(BaseModel):
    organization_id: UUID
    name: str
    slug: str | None = None
    settings: dict[str, Any] = {}

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Workspace name cannot be blank.")
        return cleaned

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip().lower()
        if not re.match(r"^[a-z0-9-]+$", cleaned):
            raise ValueError("Slug must contain only lowercase letters, numbers, and hyphens.")
        return cleaned


class WorkspaceUpdateRequest(BaseModel):
    name: str | None = None
    slug: str | None = None
    settings: dict[str, Any] | None = None
    is_archived: bool | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Workspace name cannot be blank.")
        return cleaned

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip().lower()
        if not re.match(r"^[a-z0-9-]+$", cleaned):
            raise ValueError("Slug must contain only lowercase letters, numbers, and hyphens.")
        return cleaned


class WorkspaceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    name: str
    slug: str
    is_archived: bool
    settings: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    role: str | None = None


class WorkspaceListResponse(BaseModel):
    workspaces: list[WorkspaceResponse]
