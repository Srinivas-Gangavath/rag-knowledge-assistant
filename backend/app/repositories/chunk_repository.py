from __future__ import annotations

from uuid import UUID

from sqlalchemy import case, false, func, literal, or_, select
from sqlalchemy.orm import Session

from app.core.document_access import build_document_acl_filter
from app.core.workspace_context import WorkspaceContextProvider
from app.db.models import Document, DocumentChunk, DocumentStatus, WorkspaceRole
from app.services.lexical import escape_like_pattern, extract_identifiers
from app.services.retrieval_filters import RetrievalFilters, coalesce_filters


class ChunkRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def _resolve_chunk_workspace_id(self, chunk: DocumentChunk) -> None:
        if getattr(chunk, "workspace_id", None) is not None:
            return
        if getattr(chunk, "document", None) is not None and getattr(chunk.document, "workspace_id", None) is not None:
            chunk.workspace_id = chunk.document.workspace_id
        elif chunk.document_id is not None:
            doc = self._session.get(Document, chunk.document_id)
            if doc is not None and doc.workspace_id is not None:
                chunk.workspace_id = doc.workspace_id
        if getattr(chunk, "workspace_id", None) is None:
            chunk.workspace_id = WorkspaceContextProvider.get_default_workspace_id(self._session)

    def add(self, chunk: DocumentChunk) -> DocumentChunk:
        self._resolve_chunk_workspace_id(chunk)
        self._session.add(chunk)
        self._session.flush()
        return chunk

    def add_many(self, chunks: list[DocumentChunk]) -> list[DocumentChunk]:
        for chunk in chunks:
            self._resolve_chunk_workspace_id(chunk)
        self._session.add_all(chunks)
        self._session.flush()
        return chunks

    def get_by_id(self, chunk_id: UUID) -> DocumentChunk | None:
        return self._session.get(DocumentChunk, chunk_id)

    def list_by_document(self, document_id: UUID, workspace_id: UUID | None = None) -> list[DocumentChunk]:
        statement = select(DocumentChunk).where(DocumentChunk.document_id == document_id)
        if workspace_id is not None:
            statement = statement.where(DocumentChunk.workspace_id == workspace_id)
        statement = statement.order_by(DocumentChunk.chunk_index)
        return list(self._session.scalars(statement))

    def get_by_document_and_index(
        self,
        document_id: UUID,
        chunk_index: int,
        workspace_id: UUID | None = None,
    ) -> DocumentChunk | None:
        statement = select(DocumentChunk).where(
            DocumentChunk.document_id == document_id,
            DocumentChunk.chunk_index == chunk_index,
        )
        if workspace_id is not None:
            statement = statement.where(DocumentChunk.workspace_id == workspace_id)
        return self._session.scalars(statement).first()

    def search_similar(
        self,
        query_embedding: list[float],
        *,
        top_k: int,
        similarity_threshold: float,
        document_ids: list[UUID] | None = None,
        filters: RetrievalFilters | None = None,
        workspace_id: UUID | None = None,
        user_id: UUID | None = None,
        workspace_role: WorkspaceRole | None = None,
        is_admin: bool = True,
    ) -> list[tuple[DocumentChunk, Document, float]]:
        """Rank COMPLETED document chunks by cosine similarity in PostgreSQL.

        pgvector `<=>` is cosine *distance*. Exposed score is cosine similarity:
        similarity = 1 - cosine_distance.

        The threshold comparison is inclusive: similarity >= RAG_SIMILARITY_THRESHOLD.
        Metadata predicates and Document ACL filters are applied in this SELECT,
        before ORDER BY and LIMIT. Top-K is therefore among the filtered, authorized
        candidate set, not a global Top-K later filtered in Python.
        """
        resolved = coalesce_filters(filters, document_ids)
        if resolved is not None and resolved.has_empty_document_ids():
            return []

        distance = DocumentChunk.embedding.cosine_distance(query_embedding)
        similarity = (literal(1.0) - distance).label("similarity_score")
        statement = (
            select(DocumentChunk, Document, similarity)
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(Document.status == DocumentStatus.COMPLETED)
            .where(similarity >= similarity_threshold)
        )
        if workspace_id is not None:
            statement = statement.where(DocumentChunk.workspace_id == workspace_id)
        if not is_admin:
            acl_filter = build_document_acl_filter(user_id, workspace_role, is_admin)
            if acl_filter is not None:
                statement = statement.where(acl_filter)
        statement = self._apply_metadata_filters(statement, resolved)
        statement = statement.order_by(distance).limit(top_k)
        return [
            (chunk, document, float(score))
            for chunk, document, score in self._session.execute(statement).all()
        ]

    def search_lexical(
        self,
        question: str,
        query_embedding: list[float],
        *,
        top_k: int,
        document_ids: list[UUID] | None = None,
        filters: RetrievalFilters | None = None,
        workspace_id: UUID | None = None,
        user_id: UUID | None = None,
        workspace_role: WorkspaceRole | None = None,
        is_admin: bool = True,
    ) -> list[tuple[DocumentChunk, Document, float, float, bool]]:
        """Rank COMPLETED chunks by PostgreSQL FTS (simple) plus identifier ILIKE.

        Uses plainto_tsquery — never to_tsquery — so users cannot inject tsquery
        operators. Ranking is ts_rank_cd (lexical/FTS, not BM25).

        Metadata filters and Document ACL authorization predicates are applied in
        this SELECT before ORDER BY/LIMIT.
        """
        resolved = coalesce_filters(filters, document_ids)
        if resolved is not None and resolved.has_empty_document_ids():
            return []

        identifiers = extract_identifiers(question)
        if not identifiers and not any(char.isalnum() for char in question or ""):
            return []

        tsquery = func.plainto_tsquery("simple", question)
        fts_match = DocumentChunk.content_tsv.op("@@")(tsquery)
        lexical_score = func.ts_rank_cd(DocumentChunk.content_tsv, tsquery).label(
            "lexical_score"
        )

        identifier_clauses = [
            DocumentChunk.content.ilike(
                f"%{escape_like_pattern(token)}%",
                escape="\\",
            )
            for token in identifiers
        ]
        identifier_hit = (
            or_(*identifier_clauses) if identifier_clauses else false()
        )
        match = fts_match if not identifier_clauses else or_(fts_match, identifier_hit)
        identifier_flag = case((identifier_hit, 1), else_=0).label("identifier_hit")

        distance = DocumentChunk.embedding.cosine_distance(query_embedding)
        cosine = (literal(1.0) - distance).label("similarity_score")
        statement = (
            select(DocumentChunk, Document, lexical_score, cosine, identifier_flag)
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(Document.status == DocumentStatus.COMPLETED)
            .where(match)
        )
        if workspace_id is not None:
            statement = statement.where(DocumentChunk.workspace_id == workspace_id)
        if not is_admin:
            acl_filter = build_document_acl_filter(user_id, workspace_role, is_admin)
            if acl_filter is not None:
                statement = statement.where(acl_filter)
        statement = self._apply_metadata_filters(statement, resolved)
        statement = statement.order_by(
            identifier_flag.desc(),
            lexical_score.desc(),
            distance,
        ).limit(top_k)
        return [
            (chunk, document, float(lex_score or 0.0), float(cosine_score), bool(hit))
            for chunk, document, lex_score, cosine_score, hit in self._session.execute(
                statement
            ).all()
        ]

    def _apply_metadata_filters(self, statement, filters: RetrievalFilters | None):
        if filters is None:
            return statement
        if filters.document_ids is not None:
            statement = statement.where(Document.id.in_(filters.document_ids))
        if filters.category is not None:
            statement = statement.where(Document.category == filters.category)
        if filters.source is not None:
            statement = statement.where(Document.source == filters.source)
        if filters.tags:
            statement = statement.where(Document.tags.contains(list(filters.tags)))
        if filters.uploaded_from is not None:
            statement = statement.where(Document.created_at >= filters.uploaded_from)
        if filters.uploaded_to is not None:
            statement = statement.where(Document.created_at <= filters.uploaded_to)
        if filters.page_from is not None:
            statement = statement.where(DocumentChunk.page_number >= filters.page_from)
        if filters.page_to is not None:
            statement = statement.where(DocumentChunk.page_number <= filters.page_to)
        return statement
