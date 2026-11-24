"""RAG orchestration: query embed → retrieve → context → prompt → generate."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from time import perf_counter
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.services.ai import get_ai_provider
from app.services.ai.errors import AIEmptyResponseError
from app.services.ai.provider import AIProvider
from app.services.chat_errors import EmptyQuestionError, QuestionTooLongError
from app.services.context_builder import ContextBuilder
from app.services.embedding_service import EmbeddingService
from app.services.rag_prompt import PromptTurn, RagPromptBuilder
from app.services.retrieval import RetrievedChunk, RetrievalService, debug_payload
from app.services.retrieval_filters import RetrievalFilters
from app.services.tracing import SpanName, SpanType, current_tracer

logger = get_logger(__name__)

NO_CONTEXT_ANSWER = "I couldn't find relevant information in the uploaded documents."


@dataclass(frozen=True)
class RagSource:
    document_id: UUID
    filename: str
    page_number: int | None
    chunk_index: int
    similarity_score: float


@dataclass(frozen=True)
class RagAnswer:
    answer: str
    sources: list[RagSource]


def sources_from_chunks(chunks: list[RetrievedChunk]) -> list[RagSource]:
    return [
        RagSource(
            document_id=chunk.document_id,
            filename=chunk.filename,
            page_number=chunk.page_number,
            chunk_index=chunk.chunk_index,
            similarity_score=chunk.similarity_score,
        )
        for chunk in chunks
    ]


class RagService:
    def __init__(
        self,
        session: Session,
        settings: Settings | None = None,
        embedding_service: EmbeddingService | None = None,
        retrieval: RetrievalService | None = None,
        context_builder: ContextBuilder | None = None,
        prompt_builder: RagPromptBuilder | None = None,
        provider: AIProvider | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._retrieval = retrieval or RetrievalService(session, settings=self._settings)
        self._context_builder = context_builder or ContextBuilder()
        self._prompt_builder = prompt_builder or RagPromptBuilder()
        self._embedding_service = embedding_service
        self._provider = provider

    def _embeddings(self) -> EmbeddingService:
        if self._embedding_service is None:
            self._embedding_service = EmbeddingService(
                self._llm(),
                self._settings,
            )
        return self._embedding_service

    def _llm(self) -> AIProvider:
        if self._provider is None:
            self._provider = get_ai_provider()
        return self._provider

    def validate_question(self, question: str) -> str:
        cleaned = question.strip() if question else ""
        if not cleaned:
            raise EmptyQuestionError()
        if len(cleaned) > self._settings.max_question_length:
            raise QuestionTooLongError()
        return cleaned

    def _validated_question(self, question: str) -> str:
        return self.validate_question(question)

    def retrieve_chunks(
        self,
        question: str,
        *,
        top_k: int | None = None,
        similarity_threshold: float | None = None,
        document_ids: list[UUID] | None = None,
        filters: RetrievalFilters | None = None,
        retrieval_mode: str | None = None,
        workspace_id: UUID | None = None,
        user_id: UUID | None = None,
        workspace_role: Any | None = None,
        is_admin: bool = True,
    ) -> list[RetrievedChunk]:
        tracer = current_tracer.get()
        meta = {
            "provider": "gemini",
            "model": self._settings.embedding_model,
            "operation_type": "QUERY",
            "dimension": self._settings.embedding_dimension,
            "item_count": 1,
        }
        embed_ctx = tracer.span(SpanName.EMBEDDING, SpanType.AI_PROVIDER, metadata=meta) if tracer else None
        embed_rec = embed_ctx.__enter__() if embed_ctx else None
        try:
            started_emb = perf_counter()
            query_embedding = self._embeddings().embed_query(question)
            emb_dur = (perf_counter() - started_emb) * 1000
            if embed_rec:
                embed_rec.update_metadata({"latency_ms": round(emb_dur, 2)})
        finally:
            if embed_ctx:
                embed_ctx.__exit__(None, None, None)

        return self._retrieval.retrieve(
            query_embedding,
            question=question,
            top_k=self._settings.rag_top_k if top_k is None else top_k,
            similarity_threshold=(
                self._settings.rag_similarity_threshold
                if similarity_threshold is None
                else similarity_threshold
            ),
            document_ids=document_ids,
            filters=filters,
            retrieval_mode=retrieval_mode or self._settings.retrieval_mode,
            workspace_id=workspace_id,
            user_id=user_id,
            workspace_role=workspace_role,
            is_admin=is_admin,
        )

    def build_context(self, chunks: list[RetrievedChunk]) -> str:
        tracer = current_tracer.get()
        ctx_meta = {"chunk_count": len(chunks)}
        ctx_span = tracer.span(SpanName.CONTEXT_BUILD, SpanType.INTERNAL, metadata=ctx_meta) if tracer else None
        ctx_rec = ctx_span.__enter__() if ctx_span else None
        try:
            started_ctx = perf_counter()
            context = self._context_builder.build(chunks)
            dur_ctx = (perf_counter() - started_ctx) * 1000
            if ctx_rec:
                ctx_rec.update_metadata({
                    "estimated_context_chars": len(context),
                    "latency_ms": round(dur_ctx, 2),
                })
            return context
        finally:
            if ctx_span:
                ctx_span.__exit__(None, None, None)

    def build_prompt(
        self,
        question: str,
        chunks: list[RetrievedChunk],
        *,
        context: str | None = None,
        history: Sequence[PromptTurn] | None = None,
    ) -> str:
        resolved = self.build_context(chunks) if context is None else context
        return self._prompt_builder.build(question, resolved, history=history)

    def generate_answer(self, prompt: str) -> str:
        tracer = current_tracer.get()
        meta = {
            "provider": "gemini",
            "model": self._settings.llm_model,
        }
        llm_ctx = tracer.span(SpanName.LLM_GENERATION, SpanType.AI_PROVIDER, metadata=meta) if tracer else None
        llm_rec = llm_ctx.__enter__() if llm_ctx else None
        try:
            started_llm = perf_counter()
            generated = self._llm().generate_text(prompt)
            dur_llm = (perf_counter() - started_llm) * 1000
            if not generated or not generated.strip():
                raise AIEmptyResponseError("Gemini returned an empty generation response.")
            if llm_rec:
                llm_rec.update_metadata({
                    "latency_ms": round(dur_llm, 2),
                    "token_usage_available": False,
                })
            return generated.strip()
        finally:
            if llm_ctx:
                llm_ctx.__exit__(None, None, None)

    def stream_tokens(self, prompt: str) -> Iterator[str]:
        produced = False
        for token in self._llm().stream_text(prompt):
            if not token:
                continue
            produced = True
            yield token
        if not produced:
            raise AIEmptyResponseError("Gemini returned an empty generation response.")

    def retrieval_debug(
        self,
        question: str,
        chunks: list[RetrievedChunk] | None = None,
        *,
        workspace_id: UUID | None = None,
        user_id: UUID | None = None,
        workspace_role: Any | None = None,
        is_admin: bool = True,
    ) -> dict:
        retrieved = chunks if chunks is not None else self.retrieve_chunks(
            question,
            workspace_id=workspace_id,
            user_id=user_id,
            workspace_role=workspace_role,
            is_admin=is_admin,
        )
        return debug_payload(question, retrieved)

    def answer(
        self,
        question: str,
        history: Sequence[PromptTurn] | None = None,
        *,
        document_ids: list[UUID] | None = None,
        filters: RetrievalFilters | None = None,
        workspace_id: UUID | None = None,
        user_id: UUID | None = None,
        workspace_role: Any | None = None,
        is_admin: bool = True,
    ) -> RagAnswer:
        cleaned = self.validate_question(question)
        chunks = self.retrieve_chunks(
            cleaned,
            document_ids=document_ids,
            filters=filters,
            workspace_id=workspace_id,
            user_id=user_id,
            workspace_role=workspace_role,
            is_admin=is_admin,
        )
        if not chunks:
            logger.info("RETRIEVAL returned no relevant chunks; skipping generation")
            return RagAnswer(answer=NO_CONTEXT_ANSWER, sources=[])

        prompt = self.build_prompt(cleaned, chunks, history=history)
        answer = self.generate_answer(prompt)
        logger.info("GENERATION completed (characters=%s)", len(answer))
        return RagAnswer(answer=answer, sources=sources_from_chunks(chunks))
