"""Local cross-encoder reranking. Not embeddings, not RRF, not generation.

Reranks an already retrieved candidate pool. Does not search PostgreSQL or call Gemini.
"""

from __future__ import annotations

import math
from dataclasses import replace
from typing import Protocol

from app.core.config import Settings
from app.core.logging import get_logger
from app.services.chat_errors import ChatServiceError
from app.services.retrieval import RetrievedChunk

logger = get_logger(__name__)


class RerankError(ChatServiceError):
    status_code = 502
    public_message = "The AI service is temporarily unavailable. Please try again later."


class Reranker(Protocol):
    def rerank(self, query: str, candidates: list[RetrievedChunk]) -> list[RetrievedChunk]:
        """Score candidates in RRF order. Return the same chunk IDs with rerank_score set."""


class LocalCrossEncoderReranker:
    """CPU CrossEncoder wrapper. The model is loaded on first rerank() only."""

    def __init__(self, settings: Settings) -> None:
        self._model_id = settings.reranker_model
        self._batch_size = settings.rerank_batch_size
        self._max_chars = settings.rerank_max_chars
        self._model = None

    def rerank(self, query: str, candidates: list[RetrievedChunk]) -> list[RetrievedChunk]:
        if not candidates:
            return []
        texts: list[str] = []
        for chunk in candidates:
            if not (chunk.content or "").strip():
                raise RerankError("A retrieved chunk has empty content and cannot be reranked.")
            texts.append(_truncate_tail(chunk.content, self._max_chars, chunk.chunk_id))
        pairs = [(query, text) for text in texts]
        scores = self._predict(pairs)
        if len(scores) != len(candidates):
            raise RerankError("Reranker returned a different number of scores than candidates.")
        scored: list[RetrievedChunk] = []
        for rank, (chunk, score) in enumerate(zip(candidates, scores, strict=True), start=1):
            if not math.isfinite(score):
                raise RerankError("Reranker returned a non-finite score.")
            scored.append(
                replace(
                    chunk,
                    rerank_score=float(score),
                    pre_rerank_rank=rank,
                )
            )
        return scored

    def _predict(self, pairs: list[tuple[str, str]]) -> list[float]:
        model = self._load()
        try:
            raw = model.predict(pairs, batch_size=self._batch_size)
        except RerankError:
            raise
        except Exception as exc:
            raise RerankError("Reranker inference failed.") from exc
        try:
            if hasattr(raw, "tolist"):
                raw = raw.tolist()
            if isinstance(raw, (int, float)):
                return [float(raw)]
            return [float(value) for value in raw]
        except (TypeError, ValueError) as exc:
            raise RerankError("Reranker returned a non-numeric score.") from exc

    def _load(self):
        if self._model is not None:
            return self._model
        logger.info("RERANK loading cross-encoder (model=%s, device=cpu)", self._model_id)
        try:
            from sentence_transformers import CrossEncoder
        except Exception as exc:
            raise RerankError("Reranker dependencies are not available.") from exc
        try:
            self._model = CrossEncoder(self._model_id, device="cpu")
        except Exception as exc:
            raise RerankError("Reranker model failed to load.") from exc
        logger.info("RERANK cross-encoder ready (model=%s)", self._model_id)
        return self._model


def _truncate_tail(content: str, max_chars: int, chunk_id: object) -> str:
    if max_chars <= 0 or len(content) <= max_chars:
        return content
    logger.warning(
        "RERANK truncated chunk tail (chunk_id=%s, chars=%s, max=%s)",
        chunk_id,
        len(content),
        max_chars,
    )
    return content[:max_chars]
