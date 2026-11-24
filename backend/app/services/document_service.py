"""Orchestrates PDF ingestion: validate, store, parse, chunk, embed, persist, and ACL access control."""

from uuid import UUID, uuid4

from fastapi import HTTPException, status
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.document_access import can_access_document, is_workspace_admin_context
from app.core.logging import get_logger
from app.core.permissions import Permission
from app.core.workspace_context import WorkspaceContext, WorkspaceContextProvider
from app.db.models import (
    AuditEventType,
    AuditOutcome,
    Document,
    DocumentAcl,
    DocumentChunk,
    DocumentPermission,
    DocumentStatus,
    PrincipalType,
    User,
    Workspace,
    WorkspaceRole,
)
from app.repositories.chunk_repository import ChunkRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.membership_repository import MembershipRepository
from app.repositories.user_repository import UserRepository
from app.schemas.metadata import DocumentMetadataFields
from app.services.ai import get_ai_provider
from app.services.ai.errors import AIProviderError
from app.services.audit_service import AuditLogService
from app.services.chunker import ChunkingStrategy, create_chunker
from app.services.document_errors import (
    DocumentNotFoundError,
    DocumentServiceError,
    EmptyPdfError,
    InvalidDocumentMetadataError,
)
from app.services.embedding_service import EmbeddingService
from app.services.pdf_parser import PdfParser
from app.services.storage import ORIGINAL_FILENAME, LocalDocumentStorage
from app.services.upload_validator import original_filename_for_metadata, validate_pdf_upload

logger = get_logger(__name__)


class DocumentService:
    def __init__(
        self,
        session: Session,
        settings: Settings | None = None,
        parser: PdfParser | None = None,
        chunker: ChunkingStrategy | None = None,
        embedding_service: EmbeddingService | None = None,
        storage: LocalDocumentStorage | None = None,
        autocommit: bool = True,
        workspace_id: UUID | None = None,
        workspace_context: WorkspaceContext | None = None,
    ) -> None:
        self._session = session
        self._settings = settings or get_settings()
        self._documents = DocumentRepository(session)
        self._chunks = ChunkRepository(session)
        self._parser = parser or PdfParser()
        self._chunker = chunker or create_chunker(self._settings)
        self._storage = storage or LocalDocumentStorage(self._settings.storage_path)
        self._embedding_service = embedding_service
        self._autocommit = autocommit
        self._workspace_id = (
            workspace_id
            if workspace_id is not None
            else WorkspaceContextProvider.get_default_workspace_id(session)
        )
        self._workspace_context = workspace_context
        self._user_id = workspace_context.user_id if workspace_context else None
        self._workspace_role = workspace_context.workspace_role if workspace_context else None
        self._is_admin = is_workspace_admin_context(workspace_context)

    def _get_org_id(self) -> UUID:
        if self._workspace_context and self._workspace_context.organization_id:
            return self._workspace_context.organization_id
        workspace = self._session.get(Workspace, self._workspace_id)
        if workspace and workspace.organization_id:
            return workspace.organization_id
        return self._workspace_id

    def _get_actor_email(self) -> str | None:
        if self._user_id:
            user = self._session.get(User, self._user_id)
            if user:
                return user.email
        return None

    def require_permission(self, permission: Permission) -> None:
        if self._workspace_context is not None and not self._workspace_context.can(permission):
            try:
                AuditLogService.record_event(
                    self._session,
                    organization_id=self._get_org_id(),
                    workspace_id=self._workspace_id,
                    actor_user_id=self._user_id,
                    actor_email=self._get_actor_email(),
                    event_type=AuditEventType.PERMISSION_DENIED,
                    action="permission_check",
                    outcome=AuditOutcome.DENIED,
                    metadata={"permission": permission.value},
                    autocommit=True,
                )
            except Exception as exc:
                logger.warning("Failed to record permission denied audit event: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission denied: {permission.value} capability required",
            )

    def _chunking_strategy_name(self) -> str:
        name = getattr(self._chunker, "name", None)
        if isinstance(name, str) and name:
            return name
        return self._settings.chunking_strategy

    def _embeddings(self) -> EmbeddingService:
        if self._embedding_service is None:
            self._embedding_service = EmbeddingService(
                get_ai_provider(),
                self._settings,
            )
        return self._embedding_service

    def list_documents(self) -> list[Document]:
        return self._documents.list_all(
            workspace_id=self._workspace_id,
            user_id=self._user_id,
            workspace_role=self._workspace_role,
            is_admin=self._is_admin,
        )

    def get_document(self, document_id: UUID) -> Document:
        document = self._documents.get_by_id(
            document_id,
            workspace_id=self._workspace_id,
            user_id=self._user_id,
            workspace_role=self._workspace_role,
            is_admin=self._is_admin,
        )
        if document is None:
            raise DocumentNotFoundError()

        AuditLogService.record_event(
            self._session,
            organization_id=self._get_org_id(),
            workspace_id=self._workspace_id,
            actor_user_id=self._user_id,
            actor_email=self._get_actor_email(),
            event_type=AuditEventType.DOCUMENT_VIEWED,
            action="READ",
            outcome=AuditOutcome.SUCCESS,
            resource_type="document",
            resource_id=str(document.id),
            metadata={"filename": document.original_filename},
        )
        return document

    def get_source_evidence(
        self,
        document_id: UUID,
        chunk_index: int,
    ) -> tuple[Document, DocumentChunk, str, bool]:
        if chunk_index < 0:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Source chunk #{chunk_index} not found for document",
            )
        self.require_permission(Permission.DOCUMENT_READ)
        document = self.get_document(document_id)
        chunk = self._chunks.get_by_document_and_index(
            document_id=document.id,
            chunk_index=chunk_index,
            workspace_id=self._workspace_id,
        )
        if chunk is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Source chunk #{chunk_index} not found for document",
            )
        max_chars = self._settings.max_source_evidence_chars
        content = chunk.content or ""
        if len(content) > max_chars:
            return document, chunk, content[:max_chars], True
        return document, chunk, content, False

    def delete_document(self, document_id: UUID) -> None:
        document = self.get_document(document_id)
        if not can_access_document(self._workspace_context, document, action="delete"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Permission denied: DELETE capability required",
            )
        deleted = self._documents.delete(document_id, workspace_id=self._workspace_id)
        if not deleted:
            raise DocumentNotFoundError()

        AuditLogService.record_event(
            self._session,
            organization_id=self._get_org_id(),
            workspace_id=self._workspace_id,
            actor_user_id=self._user_id,
            actor_email=self._get_actor_email(),
            event_type=AuditEventType.DOCUMENT_DELETED,
            action="DELETE",
            outcome=AuditOutcome.SUCCESS,
            resource_type="document",
            resource_id=str(document_id),
            metadata={"filename": document.original_filename},
        )
        self._commit()
        self._storage.delete_original(document_id)
        logger.info("Document deleted (document_id=%s)", document_id)

    def ingest_pdf(
        self,
        filename: str | None,
        content_type: str | None,
        data: bytes,
        *,
        category: str | None = None,
        source: str | None = None,
        tags: list[str] | None = None,
    ) -> Document:
        validate_pdf_upload(filename, content_type, data, self._settings)
        metadata = self._normalized_metadata(category=category, source=source, tags=tags)

        document_id = uuid4()
        document = Document(
            id=document_id,
            workspace_id=self._workspace_id,
            filename=ORIGINAL_FILENAME,
            original_filename=original_filename_for_metadata(filename),
            file_path="",
            file_type="application/pdf",
            file_size=len(data),
            status=DocumentStatus.UPLOADED,
            category=metadata.category,
            source=metadata.source,
            tags=list(metadata.tags or []),
        )
        self._documents.add(document)
        self._session.flush()
        logger.info("Document upload accepted (document_id=%s)", document_id)

        try:
            savepoint = self._session.begin_nested()
            try:
                self._process(document, data)
                savepoint.commit()
            except Exception:
                savepoint.rollback()
                # Drop stale in-memory PROCESSING/COMPLETED/chunk state so it
                # cannot be flushed when FAILED is committed.
                self._session.expire_all()
                raise

            AuditLogService.record_event(
                self._session,
                organization_id=self._get_org_id(),
                workspace_id=self._workspace_id,
                actor_user_id=self._user_id,
                actor_email=self._get_actor_email(),
                event_type=AuditEventType.DOCUMENT_CREATED,
                action="CREATE",
                outcome=AuditOutcome.SUCCESS,
                resource_type="document",
                resource_id=str(document.id),
                metadata={
                    "filename": document.original_filename,
                    "page_count": document.page_count,
                },
            )
            self._commit()
            return self._require_document(document_id)
        except DocumentServiceError:
            self._mark_failed(document_id)
            self._commit()
            raise
        except AIProviderError:
            self._mark_failed(document_id)
            self._commit()
            raise
        except Exception:
            logger.exception("Document ingestion failed (document_id=%s)", document_id)
            self._mark_failed(document_id)
            self._commit()
            raise DocumentServiceError()

    def update_metadata(self, document_id: UUID, updates: dict) -> Document:
        """Update category/source/tags only. Chunks and embeddings stay unchanged."""
        document = self.get_document(document_id)
        if not can_access_document(self._workspace_context, document, action="write"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Permission denied: WRITE access on document required",
            )

        allowed = {"category", "source", "tags"}
        unknown = set(updates) - allowed
        if unknown:
            raise InvalidDocumentMetadataError()
        if updates:
            try:
                DocumentMetadataFields.model_validate(updates)
            except ValidationError as exc:
                raise InvalidDocumentMetadataError() from exc
        updated_doc = self._documents.update_metadata(document_id, updates, workspace_id=self._workspace_id)
        if updated_doc is None:
            raise DocumentNotFoundError()

        AuditLogService.record_event(
            self._session,
            organization_id=self._get_org_id(),
            workspace_id=self._workspace_id,
            actor_user_id=self._user_id,
            actor_email=self._get_actor_email(),
            event_type=AuditEventType.DOCUMENT_UPDATED,
            action="UPDATE",
            outcome=AuditOutcome.SUCCESS,
            resource_type="document",
            resource_id=str(document_id),
            metadata={"fields": sorted(updates.keys())},
        )
        self._commit()
        logger.info(
            "Document metadata updated (document_id=%s, fields=%s)",
            document_id,
            sorted(updates),
        )
        return updated_doc

    # Document ACL Operations
    def list_document_acls(self, document_id: UUID) -> list[DocumentAcl]:
        document = self.get_document(document_id)
        if not can_access_document(self._workspace_context, document, action="manage_acl"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Permission denied: Administrative authority required to view ACLs",
            )
        acls = self._documents.list_acls(document_id, workspace_id=self._workspace_id)
        AuditLogService.record_event(
            self._session,
            organization_id=self._get_org_id(),
            workspace_id=self._workspace_id,
            actor_user_id=self._user_id,
            actor_email=self._get_actor_email(),
            event_type=AuditEventType.DOCUMENT_ACL_VIEWED,
            action="READ",
            outcome=AuditOutcome.SUCCESS,
            resource_type="document_acl",
            resource_id=str(document.id),
        )
        return acls

    def add_document_acl(
        self,
        document_id: UUID,
        principal_type: PrincipalType,
        principal_id: str,
        permission: DocumentPermission,
    ) -> DocumentAcl:
        document = self.get_document(document_id)
        if not can_access_document(self._workspace_context, document, action="manage_acl"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Permission denied: Administrative authority required to manage ACLs",
            )

        principal_id_clean = principal_id.strip()

        if principal_type == PrincipalType.USER:
            user_repo = UserRepository(self._session)
            member_repo = MembershipRepository(self._session)

            user = None
            try:
                target_uid = UUID(principal_id_clean)
                user = user_repo.get_by_id(target_uid)
            except (ValueError, TypeError):
                user = user_repo.get_by_email(principal_id_clean)

            if user is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"User '{principal_id_clean}' not found",
                )

            if not user.is_active:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"User '{principal_id_clean}' is inactive",
                )

            # Validate that the user belongs to the current workspace or organization
            ws_membership = member_repo.get_workspace_membership(self._workspace_id, user.id)
            if ws_membership is None:
                org_id = self._workspace_context.organization_id if self._workspace_context else None
                if org_id is None:
                    workspace = self._session.get(Workspace, self._workspace_id)
                    org_id = workspace.organization_id if workspace else None
                org_membership = member_repo.get_organization_membership(org_id, user.id) if org_id else None
                if org_membership is None:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="User must belong to the workspace organization before being added to document ACL",
                    )

            target_principal_id = str(user.id)
        elif principal_type == PrincipalType.WORKSPACE_ROLE:
            valid_roles = {r.value for r in WorkspaceRole}
            if principal_id_clean not in valid_roles:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid workspace role '{principal_id_clean}'. Must be one of {sorted(valid_roles)}",
                )
            target_principal_id = principal_id_clean
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported principal type '{principal_type}'",
            )

        acl = DocumentAcl(
            document_id=document.id,
            principal_type=principal_type,
            principal_id=target_principal_id,
            permission=permission,
        )
        try:
            self._documents.add_acl(acl)
            AuditLogService.record_event(
                self._session,
                organization_id=self._get_org_id(),
                workspace_id=self._workspace_id,
                actor_user_id=self._user_id,
                actor_email=self._get_actor_email(),
                event_type=AuditEventType.DOCUMENT_ACL_ADDED,
                action="CREATE",
                outcome=AuditOutcome.SUCCESS,
                resource_type="document_acl",
                resource_id=str(acl.id),
                metadata={
                    "document_id": str(document.id),
                    "principal_type": str(principal_type),
                    "principal_id": target_principal_id,
                    "permission": str(permission),
                },
            )
            self._commit()
        except Exception as exc:
            self._session.rollback()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="ACL entry already exists or is invalid",
            ) from exc

        return acl

    def delete_document_acl(self, document_id: UUID, acl_id: UUID) -> None:
        document = self.get_document(document_id)
        if not can_access_document(self._workspace_context, document, action="manage_acl"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Permission denied: Administrative authority required to manage ACLs",
            )
        deleted = self._documents.delete_acl(acl_id, document_id=document.id)
        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="ACL entry not found",
            )
        AuditLogService.record_event(
            self._session,
            organization_id=self._get_org_id(),
            workspace_id=self._workspace_id,
            actor_user_id=self._user_id,
            actor_email=self._get_actor_email(),
            event_type=AuditEventType.DOCUMENT_ACL_REMOVED,
            action="DELETE",
            outcome=AuditOutcome.SUCCESS,
            resource_type="document_acl",
            resource_id=str(acl_id),
            metadata={"document_id": str(document.id)},
        )
        self._commit()


    def _normalized_metadata(
        self,
        *,
        category: str | None,
        source: str | None,
        tags: list[str] | None,
    ) -> DocumentMetadataFields:
        try:
            return DocumentMetadataFields(
                category=category,
                source=source,
                tags=None if tags is None else list(tags),
            )
        except ValidationError as exc:
            raise InvalidDocumentMetadataError() from exc

    def _process(self, document: Document, data: bytes) -> None:
        document.status = DocumentStatus.PROCESSING
        self._session.flush()

        stored_path = self._storage.save_original(document.id, data)
        document.file_path = stored_path
        self._session.flush()

        pages = self._parser.parse_path(stored_path)
        extractable = [page for page in pages if page.text]
        if not extractable:
            logger.error("PDF contained no extractable text (document_id=%s)", document.id)
            raise EmptyPdfError()

        text_chunks = self._chunker.chunk(extractable)
        if not text_chunks:
            logger.error("Chunker produced no chunks (document_id=%s)", document.id)
            raise EmptyPdfError()

        vectors = self._embeddings().embed_documents(
            [chunk.content for chunk in text_chunks]
        )
        records = [
            DocumentChunk(
                workspace_id=document.workspace_id,
                document_id=document.id,
                chunk_index=chunk.chunk_index,
                content=chunk.content,
                page_number=chunk.page_number,
                embedding=vector,
                chunk_metadata={
                    "document_id": str(document.id),
                    "filename": document.original_filename,
                    "page_number": chunk.page_number,
                    "chunk_index": chunk.chunk_index,
                    "chunking_strategy": self._chunking_strategy_name(),
                },
            )
            for chunk, vector in zip(text_chunks, vectors, strict=True)
        ]
        self._chunks.add_many(records)

        document.page_count = len(pages)
        document.status = DocumentStatus.COMPLETED
        self._session.flush()
        logger.info(
            "Document ingestion completed (document_id=%s, pages=%s, chunks=%s)",
            document.id,
            document.page_count,
            len(records),
        )

    def _mark_failed(self, document_id: UUID) -> None:
        document = self._documents.update_status(document_id, DocumentStatus.FAILED, workspace_id=self._workspace_id)
        if document is None:
            return
        logger.error("Document marked FAILED (document_id=%s)", document_id)

    def _require_document(self, document_id: UUID) -> Document:
        document = self._documents.get_by_id(document_id, workspace_id=self._workspace_id)
        if document is None:
            raise DocumentNotFoundError()
        return document

    def _commit(self) -> None:
        if self._autocommit:
            self._session.commit()
