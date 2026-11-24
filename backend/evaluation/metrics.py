"""Retrieval metrics derived from gold document/page labels.

Hit@K is only reported when the candidate pool requested from retrieval is at
least K. A run that retrieved with top_k=3 therefore reports Hit@1 and Hit@3,
not Hit@5. When the evaluator needs Hit@1/3/5 together it retrieves
max(5, top_k) candidates and scores each K from that prefix.
"""

from __future__ import annotations

from dataclasses import dataclass, field

METRIC_KS = (1, 3, 5)


def candidate_pool_k(top_k: int) -> int:
    if top_k <= 0:
        raise ValueError("top_k must be greater than 0.")
    return max(top_k, max(METRIC_KS))


@dataclass(frozen=True)
class ExpectedSource:
    document: str
    page: int | None = None


@dataclass
class QuestionResult:
    question_id: str
    question: str
    question_type: str
    expect_no_context: bool
    expected_sources: list[ExpectedSource]
    retrieved: list[dict]
    hit_at_1: bool | None
    hit_at_3: bool | None
    hit_at_5: bool | None
    recall_at_5: float | None
    no_context_correct: bool | None
    top1_similarity: float | None
    expected_answer: str | None = None
    expected_span: str | None = None
    generated_answer: str | None = None
    candidate_pool_k: int = 5
    retrieved_count: int = 0
    span_hit_at_5: bool | None = None
    reciprocal_rank: float | None = None
    gold_pre_rerank_rank: int | None = None
    gold_post_rerank_rank: int | None = None
    top1_rerank_score: float | None = None
    rerank_candidate_count: int | None = None
    final_count: int = 0


@dataclass
class RetrievalMetrics:
    questions_evaluated: int
    grounded_questions: int
    no_context_questions: int
    hit_at_1: float | None
    hit_at_3: float | None
    hit_at_5: float | None
    recall_at_5: float | None
    average_similarity: float | None
    no_context_correct: int
    no_context_total: int
    no_context_false_retrieval: int
    requested_top_k: int
    candidate_pool_k: int
    span_hit_at_5: float | None = None
    mrr: float | None = None
    mean_reciprocal_rank: float | None = None
    question_results: list[QuestionResult] = field(default_factory=list)


def source_key(document: str, page: int | None) -> tuple[str, int | None]:
    return (document, page)


def retrieved_keys(retrieved: list[dict], limit: int | None = None) -> set[tuple[str, int | None]]:
    items = retrieved if limit is None else retrieved[:limit]
    return {source_key(item["filename"], item.get("page_number")) for item in items}


def expected_keys(expected: list[ExpectedSource]) -> set[tuple[str, int | None]]:
    return {source_key(item.document, item.page) for item in expected}


def hit_at_k(expected: list[ExpectedSource], retrieved: list[dict], k: int) -> bool:
    if not expected or k <= 0:
        return False
    return bool(expected_keys(expected) & retrieved_keys(retrieved, k))


def scored_hit_at_k(
    expected: list[ExpectedSource],
    retrieved: list[dict],
    k: int,
    pool_k: int,
) -> bool | None:
    """Hit@K is undefined when the retrieval candidate pool is smaller than K."""
    if k > pool_k:
        return None
    return hit_at_k(expected, retrieved, k)


def recall_at_k(expected: list[ExpectedSource], retrieved: list[dict], k: int) -> float:
    gold = expected_keys(expected)
    if not gold:
        return 0.0
    return len(gold & retrieved_keys(retrieved, k)) / len(gold)


def scored_recall_at_k(
    expected: list[ExpectedSource],
    retrieved: list[dict],
    k: int,
    pool_k: int,
) -> float | None:
    if k > pool_k:
        return None
    return recall_at_k(expected, retrieved, k)


def span_hit_at_k(span: str | None, contents: list[str], k: int) -> bool | None:
    if not span:
        return None
    needle = span.casefold()
    return any(needle in text.casefold() for text in contents[:k])


def reciprocal_rank(
    expected: list[ExpectedSource],
    retrieved: list[dict],
    k: int | None = None,
) -> float:
    gold = expected_keys(expected)
    if not gold or (k is not None and k <= 0):
        return 0.0
    items = retrieved if k is None else retrieved[:k]
    for rank, item in enumerate(items, start=1):
        if source_key(item["filename"], item.get("page_number")) in gold:
            return 1.0 / rank
    return 0.0


def mean(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def summarize(
    results: list[QuestionResult],
    *,
    requested_top_k: int,
    pool_k: int,
) -> RetrievalMetrics:
    grounded = [item for item in results if not item.expect_no_context]
    no_context = [item for item in results if item.expect_no_context]
    hit1 = [1.0 if item.hit_at_1 else 0.0 for item in grounded if item.hit_at_1 is not None]
    hit3 = [1.0 if item.hit_at_3 else 0.0 for item in grounded if item.hit_at_3 is not None]
    hit5 = [1.0 if item.hit_at_5 else 0.0 for item in grounded if item.hit_at_5 is not None]
    recall = [item.recall_at_5 for item in grounded if item.recall_at_5 is not None]
    reciprocal_ranks = []
    for item in grounded:
        if item.reciprocal_rank is not None:
            reciprocal_ranks.append(item.reciprocal_rank)
        elif item.expected_sources:
            reciprocal_ranks.append(reciprocal_rank(item.expected_sources, item.retrieved))
    span_hits = [1.0 if item.span_hit_at_5 else 0.0 for item in grounded if item.span_hit_at_5 is not None]
    similarities = [item.top1_similarity for item in results if item.top1_similarity is not None]
    no_context_correct = sum(1 for item in no_context if item.no_context_correct)
    mrr_val = mean(reciprocal_ranks)
    return RetrievalMetrics(
        questions_evaluated=len(results),
        grounded_questions=len(grounded),
        no_context_questions=len(no_context),
        hit_at_1=mean(hit1),
        hit_at_3=mean(hit3),
        hit_at_5=mean(hit5),
        recall_at_5=mean(recall),
        average_similarity=mean(similarities),
        no_context_correct=no_context_correct,
        no_context_total=len(no_context),
        no_context_false_retrieval=len(no_context) - no_context_correct,
        requested_top_k=requested_top_k,
        candidate_pool_k=pool_k,
        span_hit_at_5=mean(span_hits),
        mrr=mrr_val,
        mean_reciprocal_rank=mrr_val,
        question_results=results,
    )
