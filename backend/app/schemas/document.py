from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import DocumentStatus
from app.schemas.metadata import DocumentMetadataFields, parse_tags_form


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    filename: str
    original_filename: str
    file_type: str
    file_size: int
    status: DocumentStatus
    page_count: int | None
    category: str | None = None
    source: str | None = None
    tags: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class DocumentListResponse(BaseModel):
    documents: list[DocumentResponse] = Field(default_factory=list)


class DocumentSourceEvidenceResponse(BaseModel):
    document_id: UUID
    filename: str
    page_number: int | None
    chunk_index: int
    content: str
    is_truncated: bool = False


def parse_upload_metadata(
    category: str | None,
    source: str | None,
    tags: str | None,
) -> DocumentMetadataFields:
    parsed_tags = parse_tags_form(tags)
    payload: dict = {}
    if category is not None:
        payload["category"] = category
    if source is not None:
        payload["source"] = source
    if parsed_tags is not None:
        payload["tags"] = parsed_tags
    return DocumentMetadataFields.model_validate(payload)
