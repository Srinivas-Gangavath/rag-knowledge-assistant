from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.api.deps import get_document_service
from app.core.permissions import Permission
from app.db.database import get_db
from app.schemas.acl import DocumentAclCreate, DocumentAclItem, DocumentAclListResponse
from app.schemas.document import (
    DocumentListResponse,
    DocumentResponse,
    DocumentSourceEvidenceResponse,
    parse_upload_metadata,
)
from app.schemas.metadata import DocumentMetadataUpdate
from app.services.document_errors import MissingUploadError
from app.services.document_service import DocumentService

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("", response_model=DocumentResponse, status_code=201)
def upload_document(
    file: UploadFile = File(...),
    category: str | None = Form(default=None),
    source: str | None = Form(default=None),
    tags: str | None = Form(default=None),
    service: DocumentService = Depends(get_document_service),
) -> DocumentResponse:
    service.require_permission(Permission.DOCUMENT_CREATE)
    data = file.file.read()
    if not file.filename and not data:
        raise MissingUploadError()
    try:
        metadata = parse_upload_metadata(category, source, tags)
    except ValueError as exc:
        raise RequestValidationError(
            [
                {
                    "loc": ("body", "tags"),
                    "msg": str(exc),
                    "type": "value_error",
                }
            ]
        ) from exc
    except ValidationError as exc:
        raise RequestValidationError(exc.errors()) from exc
    document = service.ingest_pdf(
        file.filename,
        file.content_type,
        data,
        category=metadata.category,
        source=metadata.source,
        tags=metadata.tags,
    )
    return DocumentResponse.model_validate(document)


@router.get("", response_model=DocumentListResponse)
def list_documents(
    service: DocumentService = Depends(get_document_service),
) -> DocumentListResponse:
    service.require_permission(Permission.DOCUMENT_READ)
    documents = service.list_documents()
    return DocumentListResponse(
        documents=[DocumentResponse.model_validate(item) for item in documents]
    )


@router.get("/{document_id}", response_model=DocumentResponse)
def get_document(
    document_id: UUID,
    service: DocumentService = Depends(get_document_service),
) -> DocumentResponse:
    service.require_permission(Permission.DOCUMENT_READ)
    document = service.get_document(document_id)
    return DocumentResponse.model_validate(document)


@router.get(
    "/{document_id}/sources/{chunk_index}",
    response_model=DocumentSourceEvidenceResponse,
)
def get_document_source_evidence(
    document_id: UUID,
    chunk_index: int,
    service: DocumentService = Depends(get_document_service),
) -> DocumentSourceEvidenceResponse:
    service.require_permission(Permission.DOCUMENT_READ)
    document, chunk, content, is_truncated = service.get_source_evidence(document_id, chunk_index)
    return DocumentSourceEvidenceResponse(
        document_id=document.id,
        filename=document.original_filename or document.filename,
        page_number=chunk.page_number,
        chunk_index=chunk.chunk_index,
        content=content,
        is_truncated=is_truncated,
    )


@router.patch("/{document_id}", response_model=DocumentResponse)
def patch_document(
    document_id: UUID,
    payload: DocumentMetadataUpdate,
    service: DocumentService = Depends(get_document_service),
) -> DocumentResponse:
    service.require_permission(Permission.DOCUMENT_UPDATE)
    document = service.update_metadata(
        document_id,
        payload.model_dump(exclude_unset=True),
    )
    return DocumentResponse.model_validate(document)


@router.delete("/{document_id}", status_code=204)
def delete_document(
    document_id: UUID,
    service: DocumentService = Depends(get_document_service),
) -> Response:
    service.require_permission(Permission.DOCUMENT_DELETE)
    service.delete_document(document_id)
    return Response(status_code=204)


# Document ACL Endpoints
@router.get("/{document_id}/acl", response_model=DocumentAclListResponse)
def list_document_acls(
    document_id: UUID,
    service: DocumentService = Depends(get_document_service),
) -> DocumentAclListResponse:
    service.require_permission(Permission.WORKSPACE_MEMBER_MANAGE)
    acls = service.list_document_acls(document_id)
    return DocumentAclListResponse(
        acls=[DocumentAclItem.model_validate(a) for a in acls]
    )


@router.post("/{document_id}/acl", response_model=DocumentAclItem, status_code=201)
def add_document_acl(
    document_id: UUID,
    payload: DocumentAclCreate,
    service: DocumentService = Depends(get_document_service),
) -> DocumentAclItem:
    service.require_permission(Permission.WORKSPACE_MEMBER_MANAGE)
    acl = service.add_document_acl(
        document_id,
        payload.principal_type,
        payload.principal_id,
        payload.permission,
    )
    return DocumentAclItem.model_validate(acl)


@router.delete("/{document_id}/acl/{acl_id}", status_code=204)
def delete_document_acl(
    document_id: UUID,
    acl_id: UUID,
    service: DocumentService = Depends(get_document_service),
) -> Response:
    service.require_permission(Permission.WORKSPACE_MEMBER_MANAGE)
    service.delete_document_acl(document_id, acl_id)
    return Response(status_code=204)

