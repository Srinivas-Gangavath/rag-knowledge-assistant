"""Stage 2 metadata filter validation and SQL-before-Top-K retrieval tests."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.db.models import Document, DocumentChunk, DocumentStatus
from app.schemas.chat import ChatRequest
from app.schemas.metadata import RetrievalFiltersRequest
from app.services.retrieval import RetrievalService
from app.services.retrieval_filters import RetrievalFilters, coalesce_filters


def _vector(x: float, y: float = 0.0) -> list[float]:
    values = [0.0] * 768
    values[0] = x
    values[1] = y
    return values


def _completed_document(
    session,
    filename: str,
    chunks: list[tuple[str, int, list[float]]],
    *,
    category: str | None = None,
    source: str | None = None,
    tags: list[str] | None = None,
    created_at: datetime | None = None,
) -> Document:
    document = Document(
        id=uuid4(),
        filename="original.pdf",
        original_filename=filename,
        file_path="/storage/documents/test/original.pdf",
        file_type="application/pdf",
        file_size=100,
        status=DocumentStatus.COMPLETED,
        page_count=len(chunks),
        category=category,
        source=source,
        tags=[] if tags is None else tags,
        created_at=created_at or datetime.now(timezone.utc),
    )
    session.add(document)
    session.flush()
    for index, (content, page_number, embedding) in enumerate(chunks):
        session.add(
            DocumentChunk(
                document_id=document.id,
                chunk_index=index,
                content=content,
                page_number=page_number,
                embedding=embedding,
                chunk_metadata={
                    "document_id": str(document.id),
                    "filename": filename,
                    "page_number": page_number,
                    "chunk_index": index,
                    "chunking_strategy": "fixed_word_window",
                },
            )
        )
    session.flush()
    return document


def test_coalesce_wraps_legacy_document_ids():
    doc_id = uuid4()
    wrapped = coalesce_filters(None, [doc_id])
    assert wrapped is not None
    assert wrapped.document_ids == [doc_id]


def test_coalesce_empty_document_ids_stays_empty():
    wrapped = coalesce_filters(None, [])
    assert wrapped is not None
    assert wrapped.has_empty_document_ids()


def test_coalesce_none_means_no_filter():
    assert coalesce_filters(None, None) is None


def test_filter_request_empty_object_is_unconstrained():
    parsed = RetrievalFiltersRequest.model_validate({})
    assert parsed.is_unconstrained()
    assert parsed.to_domain() is None


def test_filter_request_rejects_unknown_field():
    with pytest.raises(ValidationError):
        RetrievalFiltersRequest.model_validate({"category": "policy", "unknown": "x"})


def test_filter_request_rejects_nested_unknown_field():
    with pytest.raises(ValidationError):
        ChatRequest.model_validate(
            {
                "question": "What is the refund period?",
                "filters": {"category": "policy", "operator": "gt"},
            }
        )


def test_filter_request_rejects_invalid_uuid_and_duplicates_and_overflow():
    with pytest.raises(ValidationError):
        RetrievalFiltersRequest.model_validate({"document_ids": ["not-a-uuid"]})
    doc_id = uuid4()
    with pytest.raises(ValidationError):
        RetrievalFiltersRequest.model_validate({"document_ids": [str(doc_id), str(doc_id)]})
    with pytest.raises(ValidationError):
        RetrievalFiltersRequest.model_validate(
            {"document_ids": [str(uuid4()) for _ in range(51)]}
        )


def test_filter_request_rejects_invalid_labels_tags_dates_and_pages():
    with pytest.raises(ValidationError):
        RetrievalFiltersRequest.model_validate({"category": "Finance"})
    with pytest.raises(ValidationError):
        RetrievalFiltersRequest.model_validate({"source": "internal source"})
    with pytest.raises(ValidationError):
        RetrievalFiltersRequest.model_validate({"tags": ["Bad Tag"]})
    with pytest.raises(ValidationError):
        RetrievalFiltersRequest.model_validate({"tags": [f"t{i}" for i in range(9)]})
    with pytest.raises(ValidationError):
        RetrievalFiltersRequest.model_validate({"uploaded_from": "not-a-date"})
    with pytest.raises(ValidationError):
        RetrievalFiltersRequest.model_validate({"uploaded_from": "2026-01-01T00:00:00"})
    with pytest.raises(ValidationError):
        RetrievalFiltersRequest.model_validate(
            {
                "uploaded_from": "2026-12-31T00:00:00Z",
                "uploaded_to": "2026-01-01T00:00:00Z",
            }
        )
    with pytest.raises(ValidationError):
        RetrievalFiltersRequest.model_validate({"page_from": 0})
    with pytest.raises(ValidationError):
        RetrievalFiltersRequest.model_validate({"page_to": 0})
    with pytest.raises(ValidationError):
        RetrievalFiltersRequest.model_validate({"page_from": 5, "page_to": 1})


def test_chat_request_without_filters_remains_valid():
    parsed = ChatRequest.model_validate({"question": "What is the refund period?"})
    assert parsed.filters is None


def test_filtering_happens_before_top_k(db_session):
    """Global Top-K would return policy docs; finance filter must return finance docs."""
    policy_a = _completed_document(
        db_session,
        "a-policy.pdf",
        [("policy match A", 1, _vector(1.0, 0.0))],
        category="policy",
    )
    policy_b = _completed_document(
        db_session,
        "b-policy.pdf",
        [("policy match B", 1, _vector(0.95, 0.05))],
        category="policy",
    )
    finance_c = _completed_document(
        db_session,
        "c-finance.pdf",
        [("finance match C", 1, _vector(0.8, 0.2))],
        category="finance",
    )
    finance_d = _completed_document(
        db_session,
        "d-finance.pdf",
        [("finance match D", 1, _vector(0.7, 0.3))],
        category="finance",
    )

    unfiltered = RetrievalService(db_session).retrieve(
        _vector(1, 0),
        top_k=2,
        similarity_threshold=0.0,
        document_ids=[policy_a.id, policy_b.id, finance_c.id, finance_d.id],
    )
    assert [item.document_id for item in unfiltered] == [policy_a.id, policy_b.id]

    filtered = RetrievalService(db_session).retrieve(
        _vector(1, 0),
        top_k=2,
        similarity_threshold=0.0,
        document_ids=[policy_a.id, policy_b.id, finance_c.id, finance_d.id],
        filters=RetrievalFilters(category="finance"),
    )
    assert [item.document_id for item in filtered] == [finance_c.id, finance_d.id]
    assert all(item.document_id not in {policy_a.id, policy_b.id} for item in filtered)


def test_category_and_source_filters(db_session):
    keep = _completed_document(
        db_session,
        "keep.pdf",
        [("keep", 1, _vector(1, 0))],
        category="policy",
        source="internal",
    )
    other_category = _completed_document(
        db_session,
        "other-cat.pdf",
        [("other cat", 1, _vector(1, 0))],
        category="hr",
        source="internal",
    )
    other_source = _completed_document(
        db_session,
        "other-src.pdf",
        [("other src", 1, _vector(1, 0))],
        category="policy",
        source="vendor",
    )

    by_category = RetrievalService(db_session).retrieve(
        _vector(1, 0),
        top_k=5,
        similarity_threshold=0.0,
        document_ids=[keep.id, other_category.id, other_source.id],
        filters=RetrievalFilters(category="policy"),
    )
    assert {item.document_id for item in by_category} == {keep.id, other_source.id}

    by_source = RetrievalService(db_session).retrieve(
        _vector(1, 0),
        top_k=5,
        similarity_threshold=0.0,
        document_ids=[keep.id, other_category.id, other_source.id],
        filters=RetrievalFilters(source="internal"),
    )
    assert {item.document_id for item in by_source} == {keep.id, other_category.id}


def test_tags_require_all_requested_labels(db_session):
    both = _completed_document(
        db_session,
        "both.pdf",
        [("both tags", 1, _vector(1, 0))],
        tags=["benefits", "leave"],
    )
    one = _completed_document(
        db_session,
        "one.pdf",
        [("one tag", 1, _vector(1, 0))],
        tags=["benefits"],
    )
    none = _completed_document(
        db_session,
        "none.pdf",
        [("no tags", 1, _vector(1, 0))],
        tags=[],
    )
    ids = [both.id, one.id, none.id]

    single = RetrievalService(db_session).retrieve(
        _vector(1, 0),
        top_k=5,
        similarity_threshold=0.0,
        document_ids=ids,
        filters=RetrievalFilters(tags=["benefits"]),
    )
    assert {item.document_id for item in single} == {both.id, one.id}

    required_all = RetrievalService(db_session).retrieve(
        _vector(1, 0),
        top_k=5,
        similarity_threshold=0.0,
        document_ids=ids,
        filters=RetrievalFilters(tags=["benefits", "leave"]),
    )
    assert [item.document_id for item in required_all] == [both.id]


def test_page_and_date_and_combined_filters(db_session):
    early = datetime(2025, 1, 15, tzinfo=timezone.utc)
    late = datetime(2026, 6, 15, tzinfo=timezone.utc)
    policy = _completed_document(
        db_session,
        "policy.pdf",
        [
            ("page one", 1, _vector(1, 0)),
            ("page three", 3, _vector(0.9, 0.1)),
        ],
        category="policy",
        created_at=early,
    )
    handbook = _completed_document(
        db_session,
        "handbook.pdf",
        [("handbook page one", 1, _vector(0.95, 0.05))],
        category="hr",
        created_at=late,
    )
    ids = [policy.id, handbook.id]

    pages = RetrievalService(db_session).retrieve(
        _vector(1, 0),
        top_k=5,
        similarity_threshold=0.0,
        document_ids=ids,
        filters=RetrievalFilters(page_from=1, page_to=1),
    )
    assert {item.page_number for item in pages} == {1}

    page_from_only = RetrievalService(db_session).retrieve(
        _vector(1, 0),
        top_k=5,
        similarity_threshold=0.0,
        document_ids=ids,
        filters=RetrievalFilters(page_from=3),
    )
    assert [item.page_number for item in page_from_only] == [3]

    dates = RetrievalService(db_session).retrieve(
        _vector(1, 0),
        top_k=5,
        similarity_threshold=0.0,
        document_ids=ids,
        filters=RetrievalFilters(
            uploaded_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
            uploaded_to=datetime(2026, 12, 31, tzinfo=timezone.utc),
        ),
    )
    assert [item.document_id for item in dates] == [handbook.id]

    combined = RetrievalService(db_session).retrieve(
        _vector(1, 0),
        top_k=5,
        similarity_threshold=0.0,
        document_ids=ids,
        filters=RetrievalFilters(
            document_ids=[policy.id],
            category="policy",
            page_from=1,
            page_to=1,
        ),
    )
    assert len(combined) == 1
    assert combined[0].document_id == policy.id
    assert combined[0].page_number == 1

    empty_ids = RetrievalService(db_session).retrieve(
        _vector(1, 0),
        top_k=5,
        similarity_threshold=0.0,
        document_ids=[],
        filters=RetrievalFilters(category="policy"),
    )
    assert empty_ids == []

    missing_category = RetrievalService(db_session).retrieve(
        _vector(1, 0),
        top_k=5,
        similarity_threshold=0.0,
        document_ids=ids,
        filters=RetrievalFilters(category="finance"),
    )
    assert missing_category == []


def test_completed_and_threshold_and_order_unchanged_with_filters(db_session):
    keep = _completed_document(
        db_session,
        "keep.pdf",
        [
            ("best", 1, _vector(1, 0)),
            ("ok", 2, _vector(0.8, 0.6)),
            ("weak", 3, _vector(0, 1)),
        ],
        category="policy",
    )
    processing = Document(
        filename="original.pdf",
        original_filename="draft.pdf",
        file_path="/storage/documents/test/original.pdf",
        file_type="application/pdf",
        file_size=100,
        status=DocumentStatus.PROCESSING,
        page_count=1,
        category="policy",
        tags=[],
    )
    db_session.add(processing)
    db_session.flush()
    db_session.add(
        DocumentChunk(
            document_id=processing.id,
            chunk_index=0,
            content="processing policy",
            page_number=1,
            embedding=_vector(1, 0),
            chunk_metadata={},
        )
    )
    db_session.flush()

    results = RetrievalService(db_session).retrieve(
        _vector(1, 0),
        top_k=5,
        similarity_threshold=0.5,
        filters=RetrievalFilters(category="policy"),
    )
    ours = [item for item in results if item.document_id in {keep.id, processing.id}]
    assert [item.content for item in ours] == ["best", "ok"]
    scores = [item.similarity_score for item in ours]
    assert scores == sorted(scores, reverse=True)
    assert all(item.document_id != processing.id for item in results)
