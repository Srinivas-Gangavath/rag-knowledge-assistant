"""Run retrieval-only evaluation against the gold dataset.

Generation is not scored here. Each question result still stores expected_answer
and a generated_answer placeholder so retrieval and generation stay separable.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.logging import get_logger
from app.repositories.chunk_repository import ChunkRepository
from app.services.chunker import create_chunker
from app.services.document_service import DocumentService
from app.services.embedding_service import EmbeddingService
from app.services.retrieval import RetrievalService, debug_payload
from app.services.retrieval_filters import RetrievalFilters
from app.services.storage import LocalDocumentStorage
from evaluation.corpus import EVAL_DOCUMENTS, pdf_bytes_for
from evaluation.metrics import (
    ExpectedSource,
    QuestionResult,
    RetrievalMetrics,
    candidate_pool_k,
    expected_keys,
    reciprocal_rank,
    scored_hit_at_k,
    scored_recall_at_k,
    source_key,
    span_hit_at_k,
    summarize,
)

logger = get_logger(__name__)

DATASETS_DIR = Path(__file__).resolve().parent / "datasets"
DEFAULT_DATASET = DATASETS_DIR / "rag_eval.json"
LEXICAL_DATASET = DATASETS_DIR / "rag_eval_lexical.json"
FULL_RANKING_K = 50
EVAL_RETRIEVAL_MODES = ("dense", "lexical", "hybrid")


def load_dataset(path: Path | None = None) -> dict:
    dataset_path = path or DEFAULT_DATASET
    return json.loads(dataset_path.read_text(encoding="utf-8"))


def apply_threshold_and_limit(
    ranked: list[dict],
    *,
    top_k: int,
    similarity_threshold: float,
) -> list[dict]:
    """Replay production retrieval on a full ranking: filter then Top-K."""
    filtered = [item for item in ranked if item["score"] >= similarity_threshold]
    return filtered[:top_k]


class RetrievalEvaluator:
    def __init__(
        self,
        session: Session,
        embedding_service: EmbeddingService,
        settings: Settings,
        storage_path: str,
        *,
        chunk_size: int | None = None,
        chunk_overlap: int | None = None,
        chunking_strategy: str | None = None,
    ) -> None:
        self._session = session
        self._embedding_service = embedding_service
        self._settings = settings
        self._retrieval = RetrievalService(session, settings=settings)
        self._reranker = None
        self._chunk_size = settings.chunk_size if chunk_size is None else chunk_size
        self._chunk_overlap = settings.chunk_overlap if chunk_overlap is None else chunk_overlap
        self._chunking_strategy = (
            settings.chunking_strategy if chunking_strategy is None else chunking_strategy
        )
        self._retrieval_times_ms: list[float] = []
        self._rerank_times_ms: list[float] = []
        self._rerank_candidate_counts: list[int] = []
        self._documents = DocumentService(
            session=session,
            settings=settings,
            chunker=create_chunker(
                settings,
                strategy=self._chunking_strategy,
                chunk_size=self._chunk_size,
                chunk_overlap=self._chunk_overlap,
            ),
            embedding_service=embedding_service,
            storage=LocalDocumentStorage(storage_path),
            autocommit=False,
        )

    @property
    def chunk_size(self) -> int:
        return self._chunk_size

    @property
    def chunk_overlap(self) -> int:
        return self._chunk_overlap

    @property
    def chunking_strategy(self) -> str:
        return self._chunking_strategy

    @property
    def average_retrieval_ms(self) -> float | None:
        if not self._retrieval_times_ms:
            return None
        return sum(self._retrieval_times_ms) / len(self._retrieval_times_ms)

    @property
    def average_rerank_ms(self) -> float | None:
        if not self._rerank_times_ms:
            return None
        return sum(self._rerank_times_ms) / len(self._rerank_times_ms)

    @property
    def embedding_service(self) -> EmbeddingService:
        return self._embedding_service

    def ingest_corpus(self) -> dict[str, UUID]:
        ids: dict[str, UUID] = {}
        for spec in EVAL_DOCUMENTS:
            filename = spec["filename"]
            document = self._documents.ingest_pdf(
                filename,
                "application/pdf",
                pdf_bytes_for(filename),
                category=spec.get("category"),
                source=spec.get("source"),
                tags=spec.get("tags"),
            )
            ids[filename] = document.id
            logger.info(
                "EVAL ingested %s (document_id=%s, pages=%s)",
                filename,
                document.id,
                document.page_count,
            )
        return ids

    def chunk_stats(self, document_ids: dict[str, UUID]) -> dict:
        repo = ChunkRepository(self._session)
        per_document: list[dict] = []
        word_counts: list[int] = []
        total = 0
        for filename, document_id in document_ids.items():
            rows = repo.list_by_document(document_id)
            counts = [len(chunk.content.split()) for chunk in rows]
            total += len(rows)
            word_counts.extend(counts)
            per_document.append(
                {
                    "filename": filename,
                    "chunk_count": len(rows),
                    "average_words": (
                        None if not counts else sum(counts) / len(counts)
                    ),
                }
            )
        return {
            "total_chunk_count": total,
            "average_words_per_chunk": (
                None if not word_counts else sum(word_counts) / len(word_counts)
            ),
            "per_document": per_document,
        }

    def evaluate(
        self,
        dataset: dict,
        document_ids: dict[str, UUID],
        *,
        top_k: int,
        similarity_threshold: float,
        retrieval_mode: str = "dense",
        enable_rerank: bool = False,
    ) -> RetrievalMetrics:
        if retrieval_mode not in EVAL_RETRIEVAL_MODES:
            raise ValueError(
                f"Unsupported evaluation retrieval_mode {retrieval_mode!r}. "
                f"Allowed: {EVAL_RETRIEVAL_MODES}."
            )
        if enable_rerank and retrieval_mode != "hybrid":
            raise ValueError("Reranking evaluation requires retrieval_mode='hybrid'.")
        self._configure_retrieval(enable_rerank=enable_rerank)
        pool_k = candidate_pool_k(top_k)
        scoped_ids = list(document_ids.values())
        results: list[QuestionResult] = []
        self._retrieval_times_ms = []
        self._rerank_times_ms = []
        self._rerank_candidate_counts = []
        for item in dataset["questions"]:
            results.append(
                self._evaluate_question(
                    item,
                    scoped_ids,
                    top_k=top_k,
                    pool_k=pool_k,
                    similarity_threshold=similarity_threshold,
                    retrieval_mode=retrieval_mode,
                )
            )
        return summarize(results, requested_top_k=top_k, pool_k=pool_k)

    def _configure_retrieval(self, *, enable_rerank: bool) -> None:
        """Evaluation never silently falls back. Env rerank settings do not leak in."""
        self._retrieval._settings = self._settings.model_copy(
            update={
                "reranking_enabled": enable_rerank,
                "reranking_fallback": False,
            }
        )
        if enable_rerank and self._reranker is not None:
            self._retrieval._reranker = self._reranker
        elif not enable_rerank:
            self._retrieval._reranker = None

    def evaluate_filter_cases(
        self,
        document_ids: dict[str, UUID],
        cases: tuple,
        *,
        top_k: int,
        similarity_threshold: float,
    ) -> list[QuestionResult]:
        from evaluation.filter_cases import case_to_question_item, filters_for_case

        pool_k = candidate_pool_k(top_k)
        scoped_ids = list(document_ids.values())
        self._configure_retrieval(enable_rerank=False)
        self._retrieval_times_ms = []
        results: list[QuestionResult] = []
        for case in cases:
            results.append(
                self._evaluate_question(
                    case_to_question_item(case),
                    scoped_ids,
                    top_k=top_k,
                    pool_k=pool_k,
                    similarity_threshold=similarity_threshold,
                    filters=filters_for_case(case, document_ids),
                )
            )
        return results

    def rank_all(
        self,
        dataset: dict,
        document_ids: dict[str, UUID],
    ) -> dict[str, tuple[dict, list[tuple[dict, str]]]]:
        """Full ranking at threshold 0.0 for equivalent config slicing."""
        scoped_ids = list(document_ids.values())
        ranked: dict[str, tuple[dict, list[tuple[dict, str]]]] = {}
        for item in dataset["questions"]:
            query_embedding = self._embedding_service.embed_query(item["question"])
            chunks = self._retrieval.retrieve(
                query_embedding,
                question=item["question"],
                top_k=FULL_RANKING_K,
                similarity_threshold=0.0,
                document_ids=scoped_ids,
                retrieval_mode="dense",
            )
            debug_rows = debug_payload(item["question"], chunks)["results"]
            ranked[item["id"]] = (
                item,
                list(zip(debug_rows, [chunk.content for chunk in chunks], strict=True)),
            )
        return ranked

    def metrics_from_ranking(
        self,
        dataset: dict,
        ranked: dict[str, tuple[dict, list[tuple[dict, str]]]],
        *,
        top_k: int,
        similarity_threshold: float,
    ) -> RetrievalMetrics:
        pool_k = candidate_pool_k(top_k)
        results: list[QuestionResult] = []
        for item in dataset["questions"]:
            question, pairs = ranked[item["id"]]
            sliced = [
                pair
                for pair in pairs
                if pair[0]["score"] >= similarity_threshold
            ][:pool_k]
            results.append(
                self._score_item(
                    question,
                    [row for row, _content in sliced],
                    [content for _row, content in sliced],
                    pool_k=pool_k,
                )
            )
        return summarize(results, requested_top_k=top_k, pool_k=pool_k)

    def _evaluate_question(
        self,
        item: dict,
        document_ids: list[UUID],
        *,
        top_k: int,
        pool_k: int,
        similarity_threshold: float,
        filters: RetrievalFilters | None = None,
        retrieval_mode: str = "dense",
    ) -> QuestionResult:
        question = item["question"]
        query_embedding = self._embedding_service.embed_query(question)
        started = time.perf_counter()
        chunks = self._retrieval.retrieve(
            query_embedding,
            question=question,
            top_k=pool_k,
            similarity_threshold=similarity_threshold,
            document_ids=document_ids,
            filters=filters,
            retrieval_mode=retrieval_mode,
        )
        self._retrieval_times_ms.append((time.perf_counter() - started) * 1000)
        rerank_ms = self._retrieval.last_timings_ms.get("rerank")
        if rerank_ms is not None:
            self._rerank_times_ms.append(rerank_ms)
        if self._retrieval.last_rerank_candidate_count is not None:
            self._rerank_candidate_counts.append(self._retrieval.last_rerank_candidate_count)
        debug = debug_payload(question, chunks)
        return self._score_item(
            item,
            debug["results"],
            [chunk.content for chunk in chunks],
            pool_k=pool_k,
            rerank_candidate_count=self._retrieval.last_rerank_candidate_count,
        )

    def _score_item(
        self,
        item: dict,
        retrieved: list[dict],
        contents: list[str],
        *,
        pool_k: int,
        rerank_candidate_count: int | None = None,
    ) -> QuestionResult:
        expected = [
            ExpectedSource(document=source["document"], page=source.get("page"))
            for source in item.get("expected_sources", [])
        ]
        expect_no_context = bool(item.get("expect_no_context"))
        expected_span = item.get("expected_span")
        enriched = []
        for row, content in zip(retrieved, contents, strict=False):
            enriched.append({**row, "content": content})
        if len(enriched) < len(retrieved):
            enriched.extend(retrieved[len(enriched) :])
        retrieved = enriched
        top1 = retrieved[0]["score"] if retrieved else 0.0
        top1_rerank = None if not retrieved else retrieved[0].get("rerank_score")
        gold_pre, gold_post = _gold_rerank_ranks(expected, retrieved)
        no_context_correct = (len(retrieved) == 0) if expect_no_context else None
        logger.info(
            "EVAL %s retrieved=%s pool_k=%s hit@1=%s top1_score=%.4f",
            item["id"],
            len(retrieved),
            pool_k,
            scored_hit_at_k(expected, retrieved, 1, pool_k) if expected else None,
            top1,
        )
        return QuestionResult(
            question_id=item["id"],
            question=item["question"],
            question_type=item.get("type", "unknown"),
            expect_no_context=expect_no_context,
            expected_sources=expected,
            retrieved=retrieved,
            hit_at_1=None if expect_no_context else scored_hit_at_k(expected, retrieved, 1, pool_k),
            hit_at_3=None if expect_no_context else scored_hit_at_k(expected, retrieved, 3, pool_k),
            hit_at_5=None if expect_no_context else scored_hit_at_k(expected, retrieved, 5, pool_k),
            recall_at_5=(
                None
                if expect_no_context
                else scored_recall_at_k(expected, retrieved, 5, pool_k)
            ),
            no_context_correct=no_context_correct,
            top1_similarity=top1,
            expected_answer=item.get("expected_answer"),
            expected_span=expected_span,
            generated_answer=None,
            candidate_pool_k=pool_k,
            retrieved_count=len(retrieved),
            span_hit_at_5=(
                None
                if expect_no_context
                else span_hit_at_k(expected_span, contents, 5)
            ),
            reciprocal_rank=(
                None
                if expect_no_context
                else reciprocal_rank(expected, retrieved)
            ),
            gold_pre_rerank_rank=gold_pre,
            gold_post_rerank_rank=gold_post,
            top1_rerank_score=top1_rerank,
            rerank_candidate_count=rerank_candidate_count,
            final_count=len(retrieved),
        )


def _gold_rerank_ranks(
    expected: list[ExpectedSource],
    retrieved: list[dict],
) -> tuple[int | None, int | None]:
    gold = expected_keys(expected)
    if not gold:
        return None, None
    for row in retrieved:
        if source_key(row["filename"], row.get("page_number")) in gold:
            return row.get("pre_rerank_rank"), row.get("rank")
    return None, None
