"""Shared validation for document metadata and retrieval filters.

Unknown fields are rejected. Labels are a controlled allowlist of characters,
not a query language. These filters are retrieval controls, not authorization.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.services.retrieval_filters import RetrievalFilters

METADATA_LABEL_PATTERN = re.compile(r"^[a-z0-9_-]+$")
MAX_METADATA_LABEL_LENGTH = 64
MAX_TAGS = 8
MAX_DOCUMENT_IDS = 50


def normalize_metadata_label(value: str, *, field_name: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field_name} must not be blank.")
    if len(cleaned) > MAX_METADATA_LABEL_LENGTH:
        raise ValueError(f"{field_name} must be at most {MAX_METADATA_LABEL_LENGTH} characters.")
    if not METADATA_LABEL_PATTERN.fullmatch(cleaned):
        raise ValueError(
            f"{field_name} may contain only lowercase letters, numbers, underscore, and hyphen."
        )
    return cleaned


def normalize_tag_list(values: list[str]) -> list[str]:
    if len(values) > MAX_TAGS:
        raise ValueError(f"At most {MAX_TAGS} tags are allowed.")
    normalized: list[str] = []
    seen: set[str] = set()
    for item in values:
        if not isinstance(item, str):
            raise ValueError("Each tag must be a string.")
        label = normalize_metadata_label(item, field_name="tag")
        if label in seen:
            continue
        seen.add(label)
        normalized.append(label)
    return normalized


def parse_tags_form(value: str | None) -> list[str] | None:
    """Parse optional multipart `tags` (JSON array or comma-separated)."""
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    if stripped.startswith("["):
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ValueError("tags must be a JSON array of strings.") from exc
        if not isinstance(parsed, list):
            raise ValueError("tags must be a JSON array of strings.")
        if not all(isinstance(item, str) for item in parsed):
            raise ValueError("Each tag must be a string.")
        return parsed
    return [part.strip() for part in stripped.split(",") if part.strip()]


class DocumentMetadataFields(BaseModel):
    """Optional category/source/tags stored on the documents table."""

    model_config = ConfigDict(extra="forbid")

    category: str | None = None
    source: str | None = None
    tags: list[str] | None = None

    @field_validator("category", "source")
    @classmethod
    def validate_label(cls, value: str | None, info) -> str | None:
        if value is None:
            return None
        return normalize_metadata_label(value, field_name=info.field_name)

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return normalize_tag_list(value)


class DocumentMetadataUpdate(DocumentMetadataFields):
    """PATCH body. Omitted fields are left unchanged; null clears category/source."""


class RetrievalFiltersRequest(BaseModel):
    """API-facing retrieval filters. All provided predicates are AND-ed in SQL.

    Metadata filters restrict the candidate set before cosine Top-K. They are
    not authentication, authorization, or tenancy controls.
    """

    model_config = ConfigDict(extra="forbid")

    document_ids: list[UUID] | None = Field(default=None, max_length=MAX_DOCUMENT_IDS)
    category: str | None = None
    source: str | None = None
    tags: list[str] | None = Field(default=None, max_length=MAX_TAGS)
    uploaded_from: datetime | None = None
    uploaded_to: datetime | None = None
    page_from: int | None = Field(default=None, ge=1)
    page_to: int | None = Field(default=None, ge=1)

    @field_validator("document_ids")
    @classmethod
    def unique_document_ids(cls, value: list[UUID] | None) -> list[UUID] | None:
        if value is None:
            return None
        if len(value) != len(set(value)):
            raise ValueError("document_ids must be unique.")
        return value

    @field_validator("category", "source")
    @classmethod
    def validate_label(cls, value: str | None, info) -> str | None:
        if value is None:
            return None
        return normalize_metadata_label(value, field_name=info.field_name)

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        return normalize_tag_list(value)

    @field_validator("uploaded_from", "uploaded_to")
    @classmethod
    def require_aware_datetime(cls, value: datetime | None, info) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
            raise ValueError(f"{info.field_name} must be a timezone-aware ISO datetime.")
        return value

    @model_validator(mode="after")
    def validate_ranges(self) -> RetrievalFiltersRequest:
        if (
            self.uploaded_from is not None
            and self.uploaded_to is not None
            and self.uploaded_from > self.uploaded_to
        ):
            raise ValueError("uploaded_from must be less than or equal to uploaded_to.")
        if (
            self.page_from is not None
            and self.page_to is not None
            and self.page_from > self.page_to
        ):
            raise ValueError("page_from must be less than or equal to page_to.")
        return self

    def is_unconstrained(self) -> bool:
        return (
            self.document_ids is None
            and self.category is None
            and self.source is None
            and self.tags is None
            and self.uploaded_from is None
            and self.uploaded_to is None
            and self.page_from is None
            and self.page_to is None
        )

    def to_domain(self) -> RetrievalFilters | None:
        if self.is_unconstrained():
            return None
        return RetrievalFilters(
            document_ids=None if self.document_ids is None else list(self.document_ids),
            category=self.category,
            source=self.source,
            tags=None if self.tags is None else list(self.tags),
            uploaded_from=self.uploaded_from,
            uploaded_to=self.uploaded_to,
            page_from=self.page_from,
            page_to=self.page_to,
        )
