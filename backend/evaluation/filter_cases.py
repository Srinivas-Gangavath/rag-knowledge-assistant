"""Stage 2 metadata-filter evaluation cases.

Uses the existing evaluation PDFs and Q1 ("What is the refund period?").
Unfiltered baseline remains the full rag_eval.json run; these cases measure
filter behavior against that same corpus and retrieval parameters.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.services.retrieval_filters import RetrievalFilters
from evaluation.metrics import ExpectedSource


REFUND_QUESTION = "What is the refund period?"
POLICY_SOURCE = ExpectedSource("company-policy.pdf", 1)


@dataclass(frozen=True)
class MetadataFilterCase:
    id: str
    name: str
    question: str
    expected_sources: tuple[ExpectedSource, ...]
    expect_no_context: bool
    isolate_corpus: bool = True
    document_ids_from: tuple[str, ...] | None = None
    empty_document_ids: bool = False
    category: str | None = None
    source: str | None = None
    tags: tuple[str, ...] | None = None
    page_from: int | None = None
    page_to: int | None = None


FILTER_CASES: tuple[MetadataFilterCase, ...] = (
    MetadataFilterCase(
        id="F1",
        name="no_filter",
        question=REFUND_QUESTION,
        expected_sources=(POLICY_SOURCE,),
        expect_no_context=False,
    ),
    MetadataFilterCase(
        id="F2",
        name="correct_category",
        question=REFUND_QUESTION,
        expected_sources=(POLICY_SOURCE,),
        expect_no_context=False,
        category="policy",
    ),
    MetadataFilterCase(
        id="F3",
        name="wrong_category",
        question=REFUND_QUESTION,
        expected_sources=(POLICY_SOURCE,),
        expect_no_context=False,
        category="hr",
    ),
    MetadataFilterCase(
        id="F4",
        name="document_ids_isolation",
        question=REFUND_QUESTION,
        expected_sources=(POLICY_SOURCE,),
        expect_no_context=False,
        document_ids_from=("company-policy.pdf",),
    ),
    MetadataFilterCase(
        id="F5",
        name="empty_document_ids",
        question=REFUND_QUESTION,
        expected_sources=(),
        expect_no_context=True,
        isolate_corpus=False,
        empty_document_ids=True,
    ),
    MetadataFilterCase(
        id="F6",
        name="impossible_category",
        question=REFUND_QUESTION,
        expected_sources=(),
        expect_no_context=True,
        category="does-not-exist",
    ),
    MetadataFilterCase(
        id="F7",
        name="category_and_page",
        question=REFUND_QUESTION,
        expected_sources=(POLICY_SOURCE,),
        expect_no_context=False,
        category="policy",
        page_from=1,
        page_to=1,
    ),
    MetadataFilterCase(
        id="F8",
        name="tags_all_match",
        question=REFUND_QUESTION,
        expected_sources=(POLICY_SOURCE,),
        expect_no_context=False,
        tags=("refunds",),
    ),
    MetadataFilterCase(
        id="F9",
        name="tags_all_mismatch",
        question=REFUND_QUESTION,
        expected_sources=(),
        expect_no_context=True,
        tags=("refunds", "benefits"),
    ),
)


def filters_for_case(
    case: MetadataFilterCase,
    document_ids: dict[str, UUID],
) -> RetrievalFilters | None:
    scoped: list[UUID] | None = None
    if case.empty_document_ids:
        scoped = []
    elif case.document_ids_from is not None:
        scoped = [document_ids[name] for name in case.document_ids_from]
    return RetrievalFilters(
        document_ids=scoped,
        category=case.category,
        source=case.source,
        tags=None if case.tags is None else list(case.tags),
        page_from=case.page_from,
        page_to=case.page_to,
    )


def case_to_question_item(case: MetadataFilterCase) -> dict:
    return {
        "id": case.id,
        "question": case.question,
        "type": case.name,
        "expected_answer": None,
        "expected_sources": [
            {"document": source.document, "page": source.page}
            for source in case.expected_sources
        ],
        "expect_no_context": case.expect_no_context,
    }
