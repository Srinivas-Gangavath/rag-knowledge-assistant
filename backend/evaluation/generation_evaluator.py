"""Run generation evaluation on the same production RAG path.

Retrieval metrics stay independent. For each question the evaluator:

1. Retrieves with RagService.retrieve_chunks (production retrieval).
2. Builds context with RagService.build_context.
3. Builds the production prompt (question + retrieved context only).
4. Calls RagService.generate_answer when chunks exist; otherwise uses the
   production no-context refusal and does not call the LLM.

Expected answers and gold source labels are used only after generation.
"""

from __future__ import annotations

import time
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.logging import get_logger
from app.services.ai.errors import AINetworkError, AIProviderError, AIQuotaExhaustedError, AIRateLimitError
from app.services.ai.provider import AIProvider
from app.services.embedding_service import EmbeddingService
from app.services.rag import NO_CONTEXT_ANSWER, RagService
from app.services.retrieval import debug_payload
from evaluation.evaluator import RetrievalEvaluator
from evaluation.generation import (
    GenerationMetrics,
    GenerationQuestionResult,
    score_generation,
    summarize_generation,
)
from evaluation.metrics import candidate_pool_k, summarize

logger = get_logger(__name__)

CONTEXT_PREVIEW_CHARS = 400
DEFAULT_GENERATION_MIN_INTERVAL_SECONDS = 13.0
RATE_LIMIT_WAIT_SECONDS = 35.0
RATE_LIMIT_RETRIES = 6


class GenerationEvaluator:
    def __init__(
        self,
        session: Session,
        embedding_service: EmbeddingService,
        settings: Settings,
        storage_path: str,
        *,
        provider: AIProvider,
        chunk_size: int | None = None,
        chunk_overlap: int | None = None,
        chunking_strategy: str | None = None,
        generation_min_interval_seconds: float = 0.0,
    ) -> None:
        self._retrieval = RetrievalEvaluator(
            session,
            embedding_service,
            settings,
            storage_path,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            chunking_strategy=chunking_strategy,
        )
        self._rag = RagService(
            session=session,
            settings=settings,
            embedding_service=embedding_service,
            provider=provider,
        )
        self._settings = settings
        self._generation_min_interval_seconds = generation_min_interval_seconds
        self._last_generation_at = 0.0

    @property
    def rag(self) -> RagService:
        return self._rag

    def ingest_corpus(self) -> dict[str, UUID]:
        return self._retrieval.ingest_corpus()

    def evaluate(
        self,
        dataset: dict,
        document_ids: dict[str, UUID],
        *,
        top_k: int,
        similarity_threshold: float,
        on_result=None,
    ) -> GenerationMetrics:
        pool_k = candidate_pool_k(top_k)
        scoped_ids = list(document_ids.values())
        results: list[GenerationQuestionResult] = []
        stop_reason: str | None = None
        remaining = dataset["questions"]
        for item in remaining:
            try:
                result = self._evaluate_question(
                    item,
                    scoped_ids,
                    top_k=top_k,
                    pool_k=pool_k,
                    similarity_threshold=similarity_threshold,
                )
            except AIQuotaExhaustedError:
                stop_reason = "Gemini daily generation quota exhausted."
                logger.warning("EVAL %s", stop_reason)
                break
            except AIRateLimitError:
                stop_reason = (
                    f"Stopped after {len(results)}/{len(remaining)} questions "
                    "because the production LLM rate limit was exceeded."
                )
                logger.warning("EVAL %s", stop_reason)
                break
            except AINetworkError:
                stop_reason = (
                    f"Stopped after {len(results)}/{len(remaining)} questions "
                    "because Gemini was temporarily unavailable."
                )
                logger.warning("EVAL %s", stop_reason)
                break
            except AIProviderError:
                stop_reason = (
                    f"Stopped after {len(results)}/{len(remaining)} questions "
                    "because a Gemini provider error occurred."
                )
                logger.warning("EVAL %s", stop_reason)
                break
            results.append(result)
            if on_result is not None:
                on_result(result)
        retrieval_metrics = summarize(
            [item.retrieval for item in results],
            requested_top_k=top_k,
            pool_k=pool_k,
        )
        return summarize_generation(
            retrieval_metrics,
            results,
            incomplete=stop_reason is not None,
            incomplete_reason=stop_reason,
        )

    def _evaluate_question(
        self,
        item: dict,
        document_ids: list[UUID],
        *,
        top_k: int,
        pool_k: int,
        similarity_threshold: float,
    ) -> GenerationQuestionResult:
        question = item["question"]
        pool_chunks = self._rag.retrieve_chunks(
            question,
            top_k=pool_k,
            similarity_threshold=similarity_threshold,
            document_ids=document_ids,
        )
        llm_chunks = pool_chunks[:top_k]
        debug = debug_payload(question, pool_chunks)
        retrieval = self._retrieval._score_item(
            item,
            debug["results"],
            [chunk.content for chunk in pool_chunks],
            pool_k=pool_k,
        )

        if not llm_chunks:
            generated = NO_CONTEXT_ANSWER
            context = ""
            prompt = ""
            llm_called = False
            logger.info("EVAL %s generation skipped (no retrieved chunks)", item["id"])
        else:
            context = self._rag.build_context(llm_chunks)
            prompt = self._rag.build_prompt(question, llm_chunks, context=context)
            generated = self._generate_answer(prompt)
            llm_called = True
            logger.info(
                "EVAL %s generation completed (chars=%s, sources=%s)",
                item["id"],
                len(generated),
                len(llm_chunks),
            )

        retrieval.generated_answer = generated
        score = score_generation(
            item=item,
            retrieval=retrieval,
            generated_answer=generated,
            context=context,
            prompt=prompt,
            llm_called=llm_called,
            chunks_sent_to_llm=len(llm_chunks),
        )
        return GenerationQuestionResult(
            retrieval=retrieval,
            score=score,
            context=context,
            prompt=prompt,
            chunks_sent_to_llm=len(llm_chunks),
        )

    def _generate_answer(self, prompt: str) -> str:
        self._pace_generation()
        attempts = 0
        while True:
            try:
                answer = self._rag.generate_answer(prompt)
                self._last_generation_at = time.monotonic()
                return answer
            except AIQuotaExhaustedError:
                raise
            except AIRateLimitError:
                attempts += 1
                if attempts > RATE_LIMIT_RETRIES:
                    raise
                logger.warning(
                    "EVAL generation rate-limited; waiting %ss (attempt %s/%s)",
                    RATE_LIMIT_WAIT_SECONDS,
                    attempts,
                    RATE_LIMIT_RETRIES,
                )
                time.sleep(RATE_LIMIT_WAIT_SECONDS)

    def _pace_generation(self) -> None:
        if self._generation_min_interval_seconds <= 0 or self._last_generation_at <= 0:
            return
        elapsed = time.monotonic() - self._last_generation_at
        remaining = self._generation_min_interval_seconds - elapsed
        if remaining > 0:
            logger.info("EVAL pacing generation for %.1fs to stay under API rate limits", remaining)
            time.sleep(remaining)
