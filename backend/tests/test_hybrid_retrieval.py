"""PostgreSQL FTS lexical retrieval, identifier ILIKE, and hybrid RRF tests."""

from datetime import datetime, timezone
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.db.models import Document, DocumentChunk, DocumentStatus
from app.repositories.chunk_repository import ChunkRepository
from app.services.embedding_service import EmbeddingService
from app.services.lexical import escape_like_pattern, extract_identifiers
from app.services.rag import RagService
from app.services.retrieval import RetrievalService
from app.services.retrieval_filters import RetrievalFilters
from tests.conftest import make_settings


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
                },
            )
        )
    session.flush()
    return document


def _hybrid_service(session, **overrides) -> RetrievalService:
    settings = make_settings(retrieval_mode="hybrid", **overrides)
    return RetrievalService(session, settings=settings)


def test_extract_identifiers_from_hyphenated_tokens():
    found = extract_identifiers(
        "Compare POL-HR-2041 with SKU-PRO-99 and OPS-ROT-3300 please"
    )
    assert found == ["POL-HR-2041", "SKU-PRO-99", "OPS-ROT-3300"]
    assert extract_identifiers("What is 2041?") == []
    assert extract_identifiers("What is POL?") == []
    assert extract_identifiers("PIN-DOCS-4411 and SUP-DESK-440") == [
        "PIN-DOCS-4411",
        "SUP-DESK-440",
    ]


def test_escape_like_pattern_escapes_wildcards():
    assert "%" in escape_like_pattern("100%")
    assert escape_like_pattern("a%b_c\\d") == "a\\%b\\_c\\\\d"


def test_lexical_exact_word_and_multiple_terms(db_session):
    document = _completed_document(
        db_session,
        "policy.pdf",
        [
            ("Customers may request a refund within 30 days of purchase.", 1, _vector(0, 1)),
            ("Office snacks are restocked on Fridays.", 2, _vector(0, 1)),
        ],
    )
    repo = ChunkRepository(db_session)
    refund = repo.search_lexical(
        "refund purchase",
        _vector(1, 0),
        top_k=5,
        document_ids=[document.id],
    )
    assert refund[0][0].content.startswith("Customers may request a refund")
    snacks = repo.search_lexical(
        "snacks",
        _vector(1, 0),
        top_k=5,
        document_ids=[document.id],
    )
    assert snacks[0][0].content.startswith("Office snacks")
    missing = repo.search_lexical(
        "xylophone-not-in-corpus",
        _vector(1, 0),
        top_k=5,
        document_ids=[document.id],
    )
    assert missing == []


def test_lexical_punctuation_and_empty_tsquery(db_session):
    document = _completed_document(
        db_session,
        "policy.pdf",
        [("Refund policy text about purchases.", 1, _vector(1, 0))],
    )
    repo = ChunkRepository(db_session)
    assert (
        repo.search_lexical("???", _vector(1, 0), top_k=5, document_ids=[document.id])
        == []
    )
    assert (
        repo.search_lexical("!!!", _vector(1, 0), top_k=5, document_ids=[document.id])
        == []
    )
    quoted = repo.search_lexical(
        '"refund"',
        _vector(1, 0),
        top_k=5,
        document_ids=[document.id],
    )
    assert quoted[0][0].content.startswith("Refund policy")


def test_lexical_identifier_case_insensitive_and_unrelated(db_session):
    document = _completed_document(
        db_session,
        "handbook.pdf",
        [
            ("The employee code of conduct identifier is POL-HR-2041.", 2, _vector(0, 1)),
            ("Holiday calendar for the Bengaluru office.", 1, _vector(0, 1)),
        ],
    )
    repo = ChunkRepository(db_session)
    rows = repo.search_lexical(
        "what is pol-hr-2041?",
        _vector(1, 0),
        top_k=5,
        document_ids=[document.id],
    )
    assert "POL-HR-2041" in rows[0][0].content
    assert rows[0][4] is True
    unrelated = repo.search_lexical(
        "What is SKU-PRO-99?",
        _vector(1, 0),
        top_k=5,
        document_ids=[document.id],
    )
    assert unrelated == []


def test_lexical_multiple_identifiers(db_session):
    first = _completed_document(
        db_session,
        "handbook.pdf",
        [("Code of conduct POL-HR-2041 must be acknowledged.", 2, _vector(0, 1))],
    )
    second = _completed_document(
        db_session,
        "pricing.pdf",
        [("The price identifier SKU-PRO-99 applies to the Pro plan.", 4, _vector(0, 1))],
    )
    rows = ChunkRepository(db_session).search_lexical(
        "POL-HR-2041 and SKU-PRO-99",
        _vector(1, 0),
        top_k=5,
        document_ids=[first.id, second.id],
    )
    contents = {row[0].content for row in rows}
    assert any("POL-HR-2041" in text for text in contents)
    assert any("SKU-PRO-99" in text for text in contents)


def test_lexical_malicious_input_is_plain_text(db_session):
    document = _completed_document(
        db_session,
        "policy.pdf",
        [("foo and bar appear together in this refund sentence.", 1, _vector(1, 0))],
    )
    repo = ChunkRepository(db_session)
    for question in (
        "foo | bar",
        "foo & !bar",
        "foo:*",
        "'; DROP TABLE document_chunks; --",
    ):
        rows = repo.search_lexical(
            question,
            _vector(1, 0),
            top_k=5,
            document_ids=[document.id],
        )
        assert isinstance(rows, list)
    or_query = repo.search_lexical(
        "foo | missingtokenxyz",
        _vector(1, 0),
        top_k=5,
        document_ids=[document.id],
    )
    assert or_query == []


def test_lexical_filters_before_candidate_limit(db_session):
    policy = _completed_document(
        db_session,
        "policy.pdf",
        [("alphaomega appears in the policy handbook once.", 1, _vector(1, 0))],
        category="policy",
    )
    finance_chunks = [
        (f"alphaomega finance filler chunk number {index}", index + 1, _vector(1, 0))
        for index in range(12)
    ]
    finance = _completed_document(
        db_session,
        "finance.pdf",
        finance_chunks,
        category="finance",
    )
    rows = ChunkRepository(db_session).search_lexical(
        "alphaomega",
        _vector(1, 0),
        top_k=5,
        filters=RetrievalFilters(category="policy"),
    )
    ours = [row for row in rows if row[1].id in {policy.id, finance.id}]
    assert len(ours) == 1
    assert ours[0][1].id == policy.id
    assert all(row[1].id != finance.id for row in ours)


def test_lexical_metadata_filters_and_empty_document_ids(db_session):
    keep = _completed_document(
        db_session,
        "keep.pdf",
        [("Refund token lives here.", 2, _vector(1, 0))],
        category="policy",
        source="internal",
        tags=["refunds"],
        created_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
    )
    drop = _completed_document(
        db_session,
        "drop.pdf",
        [("Refund token lives here too.", 9, _vector(1, 0))],
        category="finance",
        source="vendor",
        tags=["pricing"],
        created_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )
    repo = ChunkRepository(db_session)
    scoped = [keep.id, drop.id]
    assert (
        repo.search_lexical(
            "Refund token",
            _vector(1, 0),
            top_k=5,
            document_ids=[],
        )
        == []
    )
    by_category = repo.search_lexical(
        "Refund token",
        _vector(1, 0),
        top_k=5,
        document_ids=scoped,
        filters=RetrievalFilters(category="policy"),
    )
    assert [row[1].id for row in by_category] == [keep.id]
    by_source = repo.search_lexical(
        "Refund token",
        _vector(1, 0),
        top_k=5,
        document_ids=scoped,
        filters=RetrievalFilters(source="internal"),
    )
    assert [row[1].id for row in by_source] == [keep.id]
    by_tags = repo.search_lexical(
        "Refund token",
        _vector(1, 0),
        top_k=5,
        document_ids=scoped,
        filters=RetrievalFilters(tags=["refunds"]),
    )
    assert [row[1].id for row in by_tags] == [keep.id]
    by_dates = repo.search_lexical(
        "Refund token",
        _vector(1, 0),
        top_k=5,
        document_ids=scoped,
        filters=RetrievalFilters(
            uploaded_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
            uploaded_to=datetime(2026, 12, 31, tzinfo=timezone.utc),
        ),
    )
    assert [row[1].id for row in by_dates] == [keep.id]
    by_pages = repo.search_lexical(
        "Refund token",
        _vector(1, 0),
        top_k=5,
        document_ids=scoped,
        filters=RetrievalFilters(page_from=1, page_to=3),
    )
    assert [row[1].id for row in by_pages] == [keep.id]


def test_filters_apply_to_dense_and_lexical_branches(db_session):
    policy = _completed_document(
        db_session,
        "policy.pdf",
        [("Sharedtoken refund language in policy.", 1, _vector(1, 0))],
        category="policy",
    )
    finance = _completed_document(
        db_session,
        "finance.pdf",
        [("Sharedtoken refund language in finance.", 1, _vector(1, 0))],
        category="finance",
    )
    repo = ChunkRepository(db_session)
    filters = RetrievalFilters(category="policy")
    dense = repo.search_similar(
        _vector(1, 0),
        top_k=20,
        similarity_threshold=0.0,
        filters=filters,
    )
    lexical = repo.search_lexical(
        "Sharedtoken",
        _vector(1, 0),
        top_k=20,
        filters=filters,
    )
    dense_ids = {row[1].id for row in dense if row[1].id in {policy.id, finance.id}}
    lexical_ids = {row[1].id for row in lexical if row[1].id in {policy.id, finance.id}}
    assert dense_ids == {policy.id}
    assert lexical_ids == {policy.id}
    assert finance.id not in dense_ids
    assert finance.id not in lexical_ids


def test_empty_document_ids_skips_both_hybrid_branches(db_session, monkeypatch):
    service = _hybrid_service(db_session)
    similar = MagicMock(return_value=[])
    lexical = MagicMock(return_value=[])
    monkeypatch.setattr(service._chunks, "search_similar", similar)
    monkeypatch.setattr(service._chunks, "search_lexical", lexical)
    results = service.retrieve(
        _vector(1, 0),
        top_k=5,
        similarity_threshold=0.7,
        document_ids=[],
        question="What is POL-HR-2041?",
        retrieval_mode="hybrid",
    )
    assert results == []
    similar.assert_not_called()
    lexical.assert_not_called()


def test_dense_mode_never_calls_lexical(db_session, monkeypatch):
    document = _completed_document(
        db_session,
        "policy.pdf",
        [("Refund within 30 days.", 1, _vector(1, 0))],
    )
    service = RetrievalService(db_session, settings=make_settings())
    lexical = MagicMock(return_value=[])
    monkeypatch.setattr(service._chunks, "search_lexical", lexical)
    results = service.retrieve(
        _vector(1, 0),
        top_k=5,
        similarity_threshold=0.5,
        document_ids=[document.id],
        question="What is the refund period?",
        retrieval_mode="dense",
    )
    assert results[0].content.startswith("Refund")
    lexical.assert_not_called()


def test_hybrid_candidate_k_is_used_before_final_top_k(db_session, monkeypatch):
    service = _hybrid_service(db_session, hybrid_candidate_k=20)
    similar = MagicMock(return_value=[])
    lexical = MagicMock(return_value=[])
    monkeypatch.setattr(service._chunks, "search_similar", similar)
    monkeypatch.setattr(service._chunks, "search_lexical", lexical)
    service.retrieve(
        _vector(1, 0),
        top_k=5,
        similarity_threshold=0.7,
        question="refund period",
        retrieval_mode="hybrid",
    )
    assert similar.call_args.kwargs["top_k"] == 20
    assert lexical.call_args.kwargs["top_k"] == 20


def test_hybrid_lexical_only_below_threshold_survives(db_session):
    document = _completed_document(
        db_session,
        "handbook.pdf",
        [("The employee code of conduct identifier is POL-HR-2041.", 2, _vector(0, 1))],
    )
    results = _hybrid_service(db_session).retrieve(
        _vector(1, 0),
        top_k=5,
        similarity_threshold=0.7,
        document_ids=[document.id],
        question="What is POL-HR-2041?",
        retrieval_mode="hybrid",
    )
    assert len(results) == 1
    assert "POL-HR-2041" in results[0].content
    assert results[0].similarity_score < 0.7
    assert results[0].lexical_rank == 1
    assert results[0].dense_rank is None


def test_hybrid_dense_below_threshold_excluded_from_dense_branch(db_session):
    document = _completed_document(
        db_session,
        "policy.pdf",
        [("Unrelated snacks inventory list.", 1, _vector(0, 1))],
    )
    dense = RetrievalService(db_session, settings=make_settings()).retrieve(
        _vector(1, 0),
        top_k=5,
        similarity_threshold=0.7,
        document_ids=[document.id],
        retrieval_mode="dense",
    )
    assert dense == []
    hybrid = _hybrid_service(db_session).retrieve(
        _vector(1, 0),
        top_k=5,
        similarity_threshold=0.7,
        document_ids=[document.id],
        question="Unrelated snacks inventory",
        retrieval_mode="hybrid",
    )
    if hybrid:
        assert hybrid[0].dense_rank is None


def test_hybrid_lexical_empty_uses_dense(db_session):
    document = _completed_document(
        db_session,
        "policy.pdf",
        [("Customers may request a refund within 30 days of purchase.", 1, _vector(1, 0))],
    )
    results = _hybrid_service(db_session).retrieve(
        _vector(1, 0),
        top_k=5,
        similarity_threshold=0.5,
        document_ids=[document.id],
        question="???",
        retrieval_mode="hybrid",
    )
    assert len(results) == 1
    assert results[0].dense_rank == 1
    assert results[0].lexical_rank is None


def test_hybrid_dense_empty_uses_lexical(db_session):
    document = _completed_document(
        db_session,
        "handbook.pdf",
        [("The identifier is POL-HR-2041 in this handbook.", 2, _vector(0, 1))],
    )
    results = _hybrid_service(db_session).retrieve(
        _vector(1, 0),
        top_k=5,
        similarity_threshold=0.7,
        document_ids=[document.id],
        question="What is POL-HR-2041?",
        retrieval_mode="hybrid",
    )
    assert len(results) == 1
    assert results[0].lexical_rank == 1
    assert results[0].dense_rank is None


def test_hybrid_both_empty(db_session):
    document = _completed_document(
        db_session,
        "policy.pdf",
        [("Office snacks are restocked on Fridays.", 1, _vector(0, 1))],
    )
    results = _hybrid_service(db_session).retrieve(
        _vector(1, 0),
        top_k=5,
        similarity_threshold=0.7,
        document_ids=[document.id],
        question="xylophone-not-in-corpus",
        retrieval_mode="hybrid",
    )
    assert results == []


def test_hybrid_both_branches_fuse_and_dedupe(db_session):
    document = _completed_document(
        db_session,
        "policy.pdf",
        [("Customers may request a refund within 30 days of purchase.", 1, _vector(1, 0))],
    )
    results = _hybrid_service(db_session).retrieve(
        _vector(1, 0),
        top_k=5,
        similarity_threshold=0.5,
        document_ids=[document.id],
        question="refund purchase",
        retrieval_mode="hybrid",
    )
    assert len(results) == 1
    assert results[0].dense_rank == 1
    assert results[0].lexical_rank == 1
    assert results[0].rrf_score == pytest.approx(1 / 61 + 1 / 61)
    assert results[0].similarity_score >= 0.5


def test_hybrid_lexical_error_does_not_fallback_to_dense(db_session, monkeypatch):
    _completed_document(
        db_session,
        "policy.pdf",
        [("Refund within 30 days.", 1, _vector(1, 0))],
    )
    service = _hybrid_service(db_session)
    monkeypatch.setattr(
        service._chunks,
        "search_lexical",
        MagicMock(side_effect=RuntimeError("lexical index missing")),
    )
    with pytest.raises(RuntimeError, match="lexical index missing"):
        service.retrieve(
            _vector(1, 0),
            top_k=5,
            similarity_threshold=0.5,
            question="refund",
            retrieval_mode="hybrid",
        )


def test_hybrid_requires_question():
    service = RetrievalService(MagicMock(), settings=make_settings(retrieval_mode="hybrid"))
    with pytest.raises(ValueError, match="original question"):
        service.retrieve(
            _vector(1, 0),
            top_k=5,
            similarity_threshold=0.7,
            retrieval_mode="hybrid",
        )


def test_hybrid_one_query_embedding():
    provider = MagicMock()
    provider.create_embedding.return_value = [0.2] * 768
    retrieval = MagicMock()
    retrieval.retrieve.return_value = []
    settings = make_settings(retrieval_mode="hybrid")
    service = RagService(
        session=MagicMock(),
        settings=settings,
        embedding_service=EmbeddingService(provider, settings),
        retrieval=retrieval,
        provider=provider,
    )
    service.retrieve_chunks("What is POL-HR-2041?", retrieval_mode="hybrid")
    provider.create_embedding.assert_called_once()
    assert retrieval.retrieve.call_args.kwargs["question"] == "What is POL-HR-2041?"
    assert retrieval.retrieve.call_args.kwargs["retrieval_mode"] == "hybrid"


def test_chat_sources_keep_cosine_not_rrf():
    from app.services.rag import sources_from_chunks
    from app.services.retrieval import RetrievedChunk

    chunk = RetrievedChunk(
        chunk_id=uuid4(),
        document_id=uuid4(),
        content="POL-HR-2041",
        page_number=2,
        chunk_index=0,
        filename="handbook.pdf",
        similarity_score=0.41,
        metadata={},
        rrf_score=0.032,
        dense_rank=None,
        lexical_rank=1,
        retrieval_mode="hybrid",
    )
    sources = sources_from_chunks([chunk])
    assert sources[0].similarity_score == 0.41
    assert not hasattr(sources[0], "rrf_score")
