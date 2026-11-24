"""Dense cosine retrieval and optional hybrid (dense + lexical FTS + RRF)."""

from __future__ import annotations

from dataclasses import dataclass, replace
from time import perf_counter
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.repositories.chunk_repository import ChunkRepository
from app.services.retrieval_filters import RetrievalFilters, coalesce_filters
from app.services.tracing import SpanName, SpanType, current_tracer

logger = get_logger(__name__)

EVAL_RETRIEVAL_MODE = "lexical"
ALLOWED_RETRIEVE_MODES = ("dense", "hybrid", EVAL_RETRIEVAL_MODE)


@dataclass(frozen=True)
class RetrievedChunk:
    chunk_id: UUID
    document_id: UUID
    content: str
    page_number: int | None
    chunk_index: int
    filename: str
    similarity_score: float
    metadata: dict
    dense_rank: int | None = None
    lexical_rank: int | None = None
    rrf_score: float | None = None
    lexical_score: float | None = None
    retrieval_mode: str | None = None
    rerank_score: float | None = None
    pre_rerank_rank: int | None = None
    rerank_fallback: bool = False


def debug_payload(query: str, chunks: list[RetrievedChunk]) -> dict:
    """Internal retrieval debug view. Not returned by the production chat API."""
    return {
        "query": query,
        "rerank_fallback": any(chunk.rerank_fallback for chunk in chunks),
        "results": [
            {
                "rank": rank,
                "document_id": str(chunk.document_id),
                "filename": chunk.filename,
                "page_number": chunk.page_number,
                "chunk_index": chunk.chunk_index,
                "score": round(chunk.similarity_score, 6),
                "dense_rank": chunk.dense_rank,
                "lexical_rank": chunk.lexical_rank,
                "rrf_score": None if chunk.rrf_score is None else round(chunk.rrf_score, 6),
                "retrieval_mode": chunk.retrieval_mode,
                "rerank_score": (
                    None if chunk.rerank_score is None else round(chunk.rerank_score, 6)
                ),
                "pre_rerank_rank": chunk.pre_rerank_rank,
                "rerank_fallback": chunk.rerank_fallback,
            }
            for rank, chunk in enumerate(chunks, start=1)
        ],
    }


class RetrievalService:
    def __init__(
        self,
        session: Session,
        settings: Settings | None = None,
        reranker=None,
    ) -> None:
        self._chunks = ChunkRepository(session)
        self._settings = settings or get_settings()
        self._reranker = reranker
        self.last_timings_ms: dict[str, float] = {}
        self.last_rerank_candidate_count: int | None = None
        self.last_rerank_fallback = False

    def retrieve(
        self,
        query_embedding: list[float],
        *,
        top_k: int,
        similarity_threshold: float,
        document_ids: list[UUID] | None = None,
        filters: RetrievalFilters | None = None,
        question: str | None = None,
        retrieval_mode: str | None = None,
        workspace_id: UUID | None = None,
        user_id: UUID | None = None,
        workspace_role: Any | None = None,
        is_admin: bool = True,
    ) -> list[RetrievedChunk]:
        self.last_timings_ms = {}
        self.last_rerank_candidate_count = None
        self.last_rerank_fallback = False
        started = perf_counter()
        resolved = coalesce_filters(filters, document_ids)
        if resolved is not None and resolved.has_empty_document_ids():
            self.last_timings_ms["total"] = (perf_counter() - started) * 1000
            return []

        mode = retrieval_mode or self._settings.retrieval_mode
        if mode not in ALLOWED_RETRIEVE_MODES:
            raise ValueError(
                f"Unsupported retrieval_mode {mode!r}. "
                f"Allowed: {ALLOWED_RETRIEVE_MODES}."
            )

        if mode == "dense":
            results = self._dense(
                query_embedding,
                top_k=top_k,
                similarity_threshold=similarity_threshold,
                filters=resolved,
                workspace_id=workspace_id,
                user_id=user_id,
                workspace_role=workspace_role,
                is_admin=is_admin,
            )
        elif mode == EVAL_RETRIEVAL_MODE:
            if question is None:
                raise ValueError("Lexical retrieval requires the original question text.")
            results = self._lexical(
                question,
                query_embedding,
                top_k=top_k,
                filters=resolved,
                workspace_id=workspace_id,
                user_id=user_id,
                workspace_role=workspace_role,
                is_admin=is_admin,
            )
        else:
            if question is None:
                raise ValueError("Hybrid retrieval requires the original question text.")
            results = self._hybrid(
                question,
                query_embedding,
                top_k=top_k,
                similarity_threshold=similarity_threshold,
                filters=resolved,
                workspace_id=workspace_id,
                user_id=user_id,
                workspace_role=workspace_role,
                is_admin=is_admin,
            )

        self.last_timings_ms["total"] = (perf_counter() - started) * 1000
        logger.info(
            "RETRIEVAL selected %s chunks (mode=%s, top_k=%s, threshold=%s, filtered=%s, rerank=%s)",
            len(results),
            mode,
            top_k,
            similarity_threshold,
            resolved is not None,
            self._settings.reranking_enabled and mode == "hybrid",
        )
        return results

    def _dense(
        self,
        query_embedding: list[float],
        *,
        top_k: int,
        similarity_threshold: float,
        filters: RetrievalFilters | None,
        workspace_id: UUID | None = None,
        user_id: UUID | None = None,
        workspace_role: Any | None = None,
        is_admin: bool = True,
    ) -> list[RetrievedChunk]:
        tracer = current_tracer.get()
        meta = {
            "top_k": top_k,
            "similarity_threshold": similarity_threshold,
            "has_filters": filters is not None,
        }
        span_ctx = tracer.span(SpanName.DENSE_RETRIEVAL, SpanType.RETRIEVAL, metadata=meta) if tracer else None
        span_record = span_ctx.__enter__() if span_ctx else None
        try:
            started = perf_counter()
            rows = self._chunks.search_similar(
                query_embedding,
                top_k=top_k,
                similarity_threshold=similarity_threshold,
                filters=filters,
                workspace_id=workspace_id,
                user_id=user_id,
                workspace_role=workspace_role,
                is_admin=is_admin,
            )
            duration = (perf_counter() - started) * 1000
            self.last_timings_ms["dense"] = duration
            if span_record:
                span_record.update_metadata({
                    "candidate_count": len(rows),
                    "latency_ms": round(duration, 2),
                })
            return [
                self._from_dense_row(chunk, document, score, rank)
                for rank, (chunk, document, score) in enumerate(rows, start=1)
            ]
        finally:
            if span_ctx:
                span_ctx.__exit__(None, None, None)

    def _lexical(
        self,
        question: str,
        query_embedding: list[float],
        *,
        top_k: int,
        filters: RetrievalFilters | None,
        workspace_id: UUID | None = None,
        user_id: UUID | None = None,
        workspace_role: Any | None = None,
        is_admin: bool = True,
    ) -> list[RetrievedChunk]:
        tracer = current_tracer.get()
        meta = {
            "top_k": top_k,
            "has_filters": filters is not None,
        }
        span_ctx = tracer.span(SpanName.LEXICAL_RETRIEVAL, SpanType.RETRIEVAL, metadata=meta) if tracer else None
        span_record = span_ctx.__enter__() if span_ctx else None
        try:
            started = perf_counter()
            rows = self._chunks.search_lexical(
                question,
                query_embedding,
                top_k=top_k,
                filters=filters,
                workspace_id=workspace_id,
                user_id=user_id,
                workspace_role=workspace_role,
                is_admin=is_admin,
            )
            duration = (perf_counter() - started) * 1000
            self.last_timings_ms["lexical"] = duration
            if span_record:
                span_record.update_metadata({
                    "candidate_count": len(rows),
                    "latency_ms": round(duration, 2),
                })
            return [
                self._from_lexical_row(chunk, document, lex_score, cosine, rank)
                for rank, (chunk, document, lex_score, cosine, _hit) in enumerate(rows, start=1)
            ]
        finally:
            if span_ctx:
                span_ctx.__exit__(None, None, None)

    def _hybrid(
        self,
        question: str,
        query_embedding: list[float],
        *,
        top_k: int,
        similarity_threshold: float,
        filters: RetrievalFilters | None,
        workspace_id: UUID | None = None,
        user_id: UUID | None = None,
        workspace_role: Any | None = None,
        is_admin: bool = True,
    ) -> list[RetrievedChunk]:
        from app.services.fusion import rrf_fuse

        candidate_k = self._settings.hybrid_candidate_k
        dense = self._dense(
            query_embedding,
            top_k=candidate_k,
            similarity_threshold=similarity_threshold,
            filters=filters,
            workspace_id=workspace_id,
            user_id=user_id,
            workspace_role=workspace_role,
            is_admin=is_admin,
        )
        lexical = self._lexical(
            question,
            query_embedding,
            top_k=candidate_k,
            filters=filters,
            workspace_id=workspace_id,
            user_id=user_id,
            workspace_role=workspace_role,
            is_admin=is_admin,
        )
        fuse_k = (
            self._settings.rerank_candidate_k
            if self._settings.reranking_enabled
            else top_k
        )
        tracer = current_tracer.get()
        meta = {
            "dense_count": len(dense),
            "lexical_count": len(lexical),
            "rrf_k": self._settings.hybrid_rrf_k,
            "top_k": fuse_k,
        }
        span_ctx = tracer.span(SpanName.HYBRID_RRF, SpanType.RETRIEVAL, metadata=meta) if tracer else None
        span_record = span_ctx.__enter__() if span_ctx else None
        try:
            started = perf_counter()
            fused = rrf_fuse(
                dense,
                lexical,
                rrf_k=self._settings.hybrid_rrf_k,
                top_k=fuse_k,
            )
            duration = (perf_counter() - started) * 1000
            self.last_timings_ms["rrf"] = duration
            if span_record:
                span_record.update_metadata({
                    "fused_count": len(fused),
                    "latency_ms": round(duration, 2),
                })
        finally:
            if span_ctx:
                span_ctx.__exit__(None, None, None)

        if not self._settings.reranking_enabled:
            return fused
        return self._rerank_fused(question, fused, top_k=top_k)

    def _rerank_fused(
        self,
        question: str,
        fused: list[RetrievedChunk],
        *,
        top_k: int,
    ) -> list[RetrievedChunk]:
        from app.services.rerank import RerankError

        if not fused:
            return []
        self.last_rerank_candidate_count = len(fused)
        tracer = current_tracer.get()
        meta = {
            "enabled": True,
            "candidate_count": len(fused),
            "model": "flashrank",
            "top_k": top_k,
        }
        span_ctx = tracer.span(SpanName.RERANKING, SpanType.RETRIEVAL, metadata=meta) if tracer else None
        span_record = span_ctx.__enter__() if span_ctx else None
        started = perf_counter()
        try:
            scored = self._get_reranker().rerank(question, fused)
            ordered = _sort_reranked(scored)[:top_k]
            duration = (perf_counter() - started) * 1000
            self.last_timings_ms["rerank"] = duration
            if span_record:
                span_record.update_metadata({
                    "selected_count": len(ordered),
                    "latency_ms": round(duration, 2),
                })
            return [
                replace(chunk, retrieval_mode="hybrid+rerank", rerank_fallback=False)
                for chunk in ordered
            ]
        except Exception as exc:
            duration = (perf_counter() - started) * 1000
            self.last_timings_ms["rerank"] = duration
            if span_record:
                span_record.update_metadata({
                    "latency_ms": round(duration, 2),
                    "error": type(exc).__name__,
                })
            if not isinstance(exc, RerankError):
                logger.exception("RERANK inference failed")
            if self._settings.reranking_fallback:
                logger.error("RERANK failed; using RRF ordering")
                self.last_rerank_fallback = True
                return [
                    replace(chunk, rerank_fallback=True)
                    for chunk in fused[:top_k]
                ]
            if isinstance(exc, RerankError):
                raise
            raise RerankError("Reranker inference failed.") from exc
        finally:
            if span_ctx:
                span_ctx.__exit__(None, None, None)

    def _get_reranker(self):
        if self._reranker is None:
            from app.services.rerank import LocalCrossEncoderReranker

            self._reranker = LocalCrossEncoderReranker(self._settings)
        return self._reranker

    def _from_dense_row(self, chunk, document, score: float, rank: int) -> RetrievedChunk:
        return RetrievedChunk(
            chunk_id=chunk.id,
            document_id=document.id,
            content=chunk.content,
            page_number=chunk.page_number,
            chunk_index=chunk.chunk_index,
            filename=document.original_filename,
            similarity_score=score,
            metadata=dict(chunk.chunk_metadata or {}),
            dense_rank=rank,
            retrieval_mode="dense",
        )

    def _from_lexical_row(
        self,
        chunk,
        document,
        lexical_score: float,
        cosine: float,
        rank: int,
    ) -> RetrievedChunk:
        return RetrievedChunk(
            chunk_id=chunk.id,
            document_id=document.id,
            content=chunk.content,
            page_number=chunk.page_number,
            chunk_index=chunk.chunk_index,
            filename=document.original_filename,
            similarity_score=cosine,
            metadata=dict(chunk.chunk_metadata or {}),
            lexical_rank=rank,
            lexical_score=lexical_score,
            retrieval_mode="lexical",
        )


def _sort_reranked(chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
    return sorted(
        chunks,
        key=lambda item: (
            -(item.rerank_score if item.rerank_score is not None else float("-inf")),
            -item.similarity_score,
            str(item.chunk_id),
        ),
    )
