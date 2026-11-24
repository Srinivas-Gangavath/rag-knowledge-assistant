from uuid import uuid4

from app.db.models import Document, DocumentChunk, DocumentStatus
from app.services.retrieval import RetrievalService
import pytest


def _vector(x: float, y: float = 0.0) -> list[float]:
    """768-d vector in the first two dimensions for deterministic cosine tests."""
    values = [0.0] * 768
    values[0] = x
    values[1] = y
    return values


def _completed_document(session, filename: str, chunks: list[tuple[str, int, list[float]]]) -> Document:
    document = Document(
        id=uuid4(),
        filename="original.pdf",
        original_filename=filename,
        file_path="/storage/documents/test/original.pdf",
        file_type="application/pdf",
        file_size=100,
        status=DocumentStatus.COMPLETED,
        page_count=len(chunks),
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


def _ours(results, *documents):
    ids = {document.id for document in documents}
    return [item for item in results if item.document_id in ids]


def test_similarity_ranking_top_k_threshold_and_metadata(db_session):
    policy = _completed_document(
        db_session,
        "company-policy.pdf",
        [
            ("Customers may request a refund within 30 days of purchase.", 1, _vector(1, 0)),
            ("Office snacks are restocked on Fridays.", 2, _vector(0, 1)),
        ],
    )
    handbook = _completed_document(
        db_session,
        "handbook.pdf",
        [
            ("Remote work is allowed on Wednesdays.", 4, _vector(0.6, 0.8)),
        ],
    )

    results = _ours(
        RetrievalService(db_session).retrieve(
            _vector(1, 0),
            top_k=5,
            similarity_threshold=0.1,
        ),
        policy,
        handbook,
    )

    assert [item.filename for item in results] == ["company-policy.pdf", "handbook.pdf"]
    assert results[0].similarity_score > results[1].similarity_score
    assert results[0].content.startswith("Customers may request a refund")
    assert results[0].document_id == policy.id
    assert results[0].page_number == 1
    assert results[0].chunk_index == 0
    assert results[0].metadata["filename"] == "company-policy.pdf"
    assert "Office snacks" not in [item.content for item in results]


def test_top_k_is_respected(db_session):
    document = _completed_document(
        db_session,
        "many.pdf",
        [
            ("alpha", 1, _vector(1, 0)),
            ("beta", 2, _vector(0.8, 0.6)),
            ("gamma", 3, _vector(0.6, 0.8)),
        ],
    )

    results = _ours(
        RetrievalService(db_session).retrieve(
            _vector(1, 0),
            top_k=2,
            similarity_threshold=0.55,
        ),
        document,
    )

    assert len(results) == 2
    assert [item.content for item in results] == ["alpha", "beta"]


def test_threshold_excludes_low_similarity(db_session):
    document = _completed_document(
        db_session,
        "policy.pdf",
        [
            ("refund within 30 days", 1, _vector(1, 0)),
            ("unrelated snacks", 2, _vector(0, 1)),
        ],
    )

    results = _ours(
        RetrievalService(db_session).retrieve(
            _vector(1, 0),
            top_k=5,
            similarity_threshold=0.5,
        ),
        document,
    )

    assert len(results) == 1
    assert results[0].content == "refund within 30 days"
    assert results[0].similarity_score >= 0.5


def test_processing_documents_are_not_retrieved(db_session):
    document = Document(
        filename="original.pdf",
        original_filename="draft.pdf",
        file_path="/storage/documents/test/original.pdf",
        file_type="application/pdf",
        file_size=100,
        status=DocumentStatus.PROCESSING,
        page_count=1,
    )
    db_session.add(document)
    db_session.flush()
    db_session.add(
        DocumentChunk(
            document_id=document.id,
            chunk_index=0,
            content="secret draft refund text",
            page_number=1,
            embedding=_vector(1, 0),
            chunk_metadata={},
        )
    )
    db_session.flush()

    results = RetrievalService(db_session).retrieve(
        _vector(1, 0),
        top_k=5,
        similarity_threshold=0.0,
    )
    assert all(item.document_id != document.id for item in results)


def test_failed_documents_are_not_retrieved(db_session):
    document = Document(
        filename="original.pdf",
        original_filename="broken.pdf",
        file_path="/storage/documents/test/original.pdf",
        file_type="application/pdf",
        file_size=100,
        status=DocumentStatus.FAILED,
        page_count=1,
    )
    db_session.add(document)
    db_session.flush()
    db_session.add(
        DocumentChunk(
            document_id=document.id,
            chunk_index=0,
            content="failed document refund text",
            page_number=1,
            embedding=_vector(1, 0),
            chunk_metadata={},
        )
    )
    db_session.flush()

    results = RetrievalService(db_session).retrieve(
        _vector(1, 0),
        top_k=5,
        similarity_threshold=0.0,
    )
    assert all(item.document_id != document.id for item in results)


def test_multiple_documents_are_ranked_together(db_session):
    weaker = _completed_document(db_session, "a.pdf", [("first doc", 1, _vector(0, 1))])
    better = _completed_document(db_session, "b.pdf", [("second doc", 8, _vector(1, 0))])

    results = _ours(
        RetrievalService(db_session).retrieve(
            _vector(1, 0),
            top_k=50,
            similarity_threshold=0.0,
        ),
        weaker,
        better,
    )

    assert results[0].document_id == better.id
    assert results[0].filename == "b.pdf"
    assert results[0].page_number == 8
    assert results[1].filename == "a.pdf"


def test_top_k_caps_when_more_chunks_exist_than_limit(db_session):
    chunks = [(f"chunk{i}", i + 1, _vector(1.0, 0.15 * i)) for i in range(7)]
    document = _completed_document(db_session, "many.pdf", chunks)

    results = _ours(
        RetrievalService(db_session).retrieve(
            _vector(1, 0),
            top_k=5,
            similarity_threshold=0.5,
        ),
        document,
    )

    assert len(results) == 5
    assert [item.content for item in results] == [f"chunk{i}" for i in range(5)]
    scores = [item.similarity_score for item in results]
    assert scores == sorted(scores, reverse=True)


def test_threshold_includes_score_equal_to_threshold(db_session):
    document = _completed_document(
        db_session,
        "policy.pdf",
        [
            ("exactly at threshold", 1, _vector(0.6, 0.8)),
            ("below threshold", 2, _vector(0, 1)),
        ],
    )

    included = _ours(
        RetrievalService(db_session).retrieve(
            _vector(1, 0),
            top_k=5,
            similarity_threshold=0.6,
        ),
        document,
    )
    excluded = _ours(
        RetrievalService(db_session).retrieve(
            _vector(1, 0),
            top_k=5,
            similarity_threshold=0.61,
        ),
        document,
    )

    assert [item.content for item in included] == ["exactly at threshold"]
    assert included[0].similarity_score == pytest.approx(0.6, abs=1e-6)
    assert excluded == []


def test_empty_document_id_filter_returns_no_results(db_session):
    _completed_document(db_session, "policy.pdf", [("refund", 1, _vector(1, 0))])
    results = RetrievalService(db_session).retrieve(
        _vector(1, 0),
        top_k=5,
        similarity_threshold=0.0,
        document_ids=[],
    )
    assert results == []


def test_document_id_filter_isolates_corpus(db_session):
    keep = _completed_document(db_session, "keep.pdf", [("keep text", 1, _vector(1, 0))])
    drop = _completed_document(db_session, "drop.pdf", [("drop text", 1, _vector(1, 0))])

    results = RetrievalService(db_session).retrieve(
        _vector(1, 0),
        top_k=5,
        similarity_threshold=0.0,
        document_ids=[keep.id],
    )

    assert [item.document_id for item in results] == [keep.id]
    assert all(item.document_id != drop.id for item in results)


def test_deleted_document_is_not_retrieved(db_session):
    document = _completed_document(
        db_session,
        "gone.pdf",
        [("delete me from retrieval", 2, _vector(1, 0))],
    )
    before = RetrievalService(db_session).retrieve(
        _vector(1, 0),
        top_k=5,
        similarity_threshold=0.0,
        document_ids=[document.id],
    )
    assert len(before) == 1
    assert before[0].page_number == 2
    assert before[0].chunk_index == 0

    db_session.delete(document)
    db_session.flush()

    after = RetrievalService(db_session).retrieve(
        _vector(1, 0),
        top_k=5,
        similarity_threshold=0.0,
        document_ids=[document.id],
    )
    assert after == []


def test_debug_payload_ranks_metadata_without_chunk_text(db_session):
    from app.services.retrieval import debug_payload

    document = _completed_document(
        db_session,
        "company-policy.pdf",
        [("Customers may request a refund within 30 days of purchase.", 4, _vector(1, 0))],
    )
    chunks = RetrievalService(db_session).retrieve(
        _vector(1, 0),
        top_k=5,
        similarity_threshold=0.0,
        document_ids=[document.id],
    )
    payload = debug_payload("What is the refund period?", chunks)

    assert payload["query"] == "What is the refund period?"
    assert payload["results"][0]["rank"] == 1
    assert payload["results"][0]["document_id"] == str(document.id)
    assert payload["results"][0]["filename"] == "company-policy.pdf"
    assert payload["results"][0]["page_number"] == 4
    assert payload["results"][0]["chunk_index"] == 0
    assert payload["results"][0]["score"] > 0
    assert "content" not in payload["results"][0]
    assert "Customers may request a refund" not in str(payload)

