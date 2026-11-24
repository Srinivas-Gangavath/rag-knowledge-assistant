from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.document_access import build_document_acl_filter
from app.core.workspace_context import WorkspaceContextProvider
from app.db.models import Document, DocumentAcl, DocumentStatus, WorkspaceRole


class DocumentRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, document: Document) -> Document:
        if getattr(document, "workspace_id", None) is None:
            document.workspace_id = WorkspaceContextProvider.get_default_workspace_id(self._session)
        self._session.add(document)
        self._session.flush()
        return document

    def get_by_id(
        self,
        document_id: UUID,
        workspace_id: UUID | None = None,
        *,
        user_id: UUID | None = None,
        workspace_role: WorkspaceRole | None = None,
        is_admin: bool = True,
    ) -> Document | None:
        statement = select(Document).options(selectinload(Document.acls)).where(Document.id == document_id)
        if workspace_id is not None:
            statement = statement.where(Document.workspace_id == workspace_id)
        if not is_admin:
            acl_filter = build_document_acl_filter(user_id, workspace_role, is_admin)
            if acl_filter is not None:
                statement = statement.where(acl_filter)
        return self._session.scalars(statement).first()

    def list_all(
        self,
        workspace_id: UUID | None = None,
        *,
        user_id: UUID | None = None,
        workspace_role: WorkspaceRole | None = None,
        is_admin: bool = True,
    ) -> list[Document]:
        statement = select(Document).options(selectinload(Document.acls))
        if workspace_id is not None:
            statement = statement.where(Document.workspace_id == workspace_id)
        if not is_admin:
            acl_filter = build_document_acl_filter(user_id, workspace_role, is_admin)
            if acl_filter is not None:
                statement = statement.where(acl_filter)
        statement = statement.order_by(
            Document.created_at.desc(),
            Document.id.desc(),
        )
        return list(self._session.scalars(statement))

    def update_status(
        self,
        document_id: UUID,
        status: DocumentStatus,
        workspace_id: UUID | None = None,
    ) -> Document | None:
        document = self.get_by_id(document_id, workspace_id=workspace_id)
        if document is None:
            return None
        document.status = status
        self._session.flush()
        return document

    def update_page_count(
        self,
        document_id: UUID,
        page_count: int,
        workspace_id: UUID | None = None,
    ) -> Document | None:
        document = self.get_by_id(document_id, workspace_id=workspace_id)
        if document is None:
            return None
        document.page_count = page_count
        self._session.flush()
        return document

    def update_metadata(
        self,
        document_id: UUID,
        updates: dict,
        workspace_id: UUID | None = None,
    ) -> Document | None:
        document = self.get_by_id(document_id, workspace_id=workspace_id)
        if document is None:
            return None
        for field, value in updates.items():
            setattr(document, field, value)
        document.updated_at = datetime.now(timezone.utc)
        self._session.flush()
        return document

    def delete(self, document_id: UUID, workspace_id: UUID | None = None) -> bool:
        document = self.get_by_id(document_id, workspace_id=workspace_id)
        if document is None:
            return False
        self._session.delete(document)
        self._session.flush()
        return True

    # Document ACL management
    def list_acls(self, document_id: UUID, workspace_id: UUID | None = None) -> list[DocumentAcl]:
        statement = (
            select(DocumentAcl)
            .join(Document, Document.id == DocumentAcl.document_id)
            .where(DocumentAcl.document_id == document_id)
        )
        if workspace_id is not None:
            statement = statement.where(Document.workspace_id == workspace_id)
        statement = statement.order_by(DocumentAcl.created_at.asc())
        return list(self._session.scalars(statement))

    def add_acl(self, acl: DocumentAcl) -> DocumentAcl:
        self._session.add(acl)
        self._session.flush()
        return acl

    def get_acl(self, acl_id: UUID, document_id: UUID | None = None) -> DocumentAcl | None:
        statement = select(DocumentAcl).where(DocumentAcl.id == acl_id)
        if document_id is not None:
            statement = statement.where(DocumentAcl.document_id == document_id)
        return self._session.scalars(statement).first()

    def delete_acl(self, acl_id: UUID, document_id: UUID | None = None) -> bool:
        acl = self.get_acl(acl_id, document_id=document_id)
        if acl is None:
            return False
        self._session.delete(acl)
        self._session.flush()
        return True
