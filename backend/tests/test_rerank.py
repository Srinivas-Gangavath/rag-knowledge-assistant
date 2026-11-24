"""Stage 4 local cross-encoder reranking. Tests never download model weights."""

from dataclasses import replace
from datetime import datetime, timezone
from types import ModuleType
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.db.models import Document, DocumentChunk, DocumentStatus
from app.main import app
from app.api.v1.conversations import get_conversation_service
from app.db.database import get_db
from app.schemas.chat import ChatRequest, ChatSource
from app.services.conversation_service import ConversationService
from app.services.embedding_service import EmbeddingService
from app.services.rag import RagService, sources_from_chunks
from app.services.rerank import LocalCrossEncoderReranker, RerankError
from app.services.retrieval import RetrievedChunk, RetrievalService, debug_payload
from app.services.retrieval_filters import RetrievalFilters
from tests.conftest import make_settings, postgres_available
from tests.helpers.sse import parse_sse


def _vector(x: float, y: float = 0.0) -> list[float]:
    values = [0.0] * 768
    values[0] = x
    values[1] = y
    return values


def _chunk(
    *,
    content: str = "Refund within 30 days of purchase.",
    filename: str = "policy.pdf",
    score: float = 0.8,
    chunk_id: UUID | None = None,
    page_number: int = 1,
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id or uuid4(),
        document_id=uuid4(),
        content=content,
        page_number=page_number,
        chunk_index=0,
        filename=filename,
        similarity_score=score,
        metadata={},
        retrieval_mode="hybrid",
    )


def _completed_document(
    session,
    filename: str,
    chunks: list[tuple[str, int, list[float]]],
    *,
    category: str | None = None,
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
        created_at=datetime.now(timezone.utc),
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


class FakeReranker:
    def __init__(self, scores=None, error: Exception | None = None) -> None:
        self.scores = scores
        self.error = error
        self.calls: list[tuple[str, list[UUID]]] = []
        self.pair_texts: list[list[str]] = []

    def rerank(self, query: str, candidates: list[RetrievedChunk]) -> list[RetrievedChunk]:
        self.calls.append((query, [chunk.chunk_id for chunk in candidates]))
        self.pair_texts.append([chunk.content for chunk in candidates])
        if self.error is not None:
            raise self.error
        if not candidates:
            return []
        scores = self.scores
        if scores is None:
            scores = [float(len(candidates) - index) for index in range(len(candidates))]
        return [
            replace(chunk, rerank_score=float(score), pre_rerank_rank=rank)
            for rank, (chunk, score) in enumerate(zip(candidates, scores, strict=True), start=1)
        ]


def _rerank_service(session, reranker, **overrides) -> RetrievalService:
    settings = make_settings(
        retrieval_mode="hybrid",
        reranking_enabled=True,
        **{"reranking_fallback": False, **overrides},
    )
    return RetrievalService(session, settings=settings, reranker=reranker)


def test_reranker_empty_candidate_list_returns_empty():
    reranker = LocalCrossEncoderReranker(make_settings())
    assert reranker.rerank("refund period", []) == []
    assert reranker._model is None


def test_reranker_builds_query_candidate_pairs_and_batches_once():
    settings = make_settings(rerank_batch_size=16)
    reranker = LocalCrossEncoderReranker(settings)
    model = MagicMock()
    model.predict.return_value = [0.2, 0.9]
    reranker._model = model
    first = _chunk(content="store credit only")
    second = _chunk(content="purchase refund in 30 days")
    scored = reranker.rerank("purchase refund period", [first, second])
    model.predict.assert_called_once()
    pairs, kwargs = model.predict.call_args.args[0], model.predict.call_args.kwargs
    assert pairs == [
        ("purchase refund period", "store credit only"),
        ("purchase refund period", "purchase refund in 30 days"),
    ]
    assert kwargs["batch_size"] == 16
    assert [chunk.chunk_id for chunk in scored] == [first.chunk_id, second.chunk_id]
    assert [chunk.rerank_score for chunk in scored] == [0.2, 0.9]
    assert [chunk.pre_rerank_rank for chunk in scored] == [1, 2]


def test_reranker_score_count_mismatch_fails():
    reranker = LocalCrossEncoderReranker(make_settings())
    model = MagicMock()
    model.predict.return_value = [0.1]
    reranker._model = model
    with pytest.raises(RerankError, match="different number of scores"):
        reranker.rerank("q", [_chunk(), _chunk()])


def test_reranker_non_finite_score_fails():
    reranker = LocalCrossEncoderReranker(make_settings())
    model = MagicMock()
    model.predict.return_value = [0.1, float("nan")]
    reranker._model = model
    with pytest.raises(RerankError, match="non-finite"):
        reranker.rerank("q", [_chunk(), _chunk()])


def test_reranker_empty_chunk_content_fails():
    reranker = LocalCrossEncoderReranker(make_settings())
    reranker._model = MagicMock()
    with pytest.raises(RerankError, match="empty content"):
        reranker.rerank("q", [_chunk(content="   ")])
    reranker._model.predict.assert_not_called()


def test_reranker_inference_failure():
    reranker = LocalCrossEncoderReranker(make_settings())
    model = MagicMock()
    model.predict.side_effect = RuntimeError("cuda oom")
    reranker._model = model
    with pytest.raises(RerankError, match="inference failed"):
        reranker.rerank("q", [_chunk()])


def test_reranker_model_loading_failure(monkeypatch):
    fake_module = ModuleType("sentence_transformers")

    class Boom:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("download failed")

    fake_module.CrossEncoder = Boom
    monkeypatch.setitem(__import__("sys").modules, "sentence_transformers", fake_module)
    reranker = LocalCrossEncoderReranker(make_settings())
    with pytest.raises(RerankError, match="failed to load"):
        reranker.rerank("q", [_chunk()])


def test_reranker_does_not_construct_model_in_init():
    reranker = LocalCrossEncoderReranker(make_settings())
    assert reranker._model is None


def test_chunk_truncation_safety_cap_does_not_mutate_stored_content(caplog):
    reranker = LocalCrossEncoderReranker(make_settings(rerank_max_chars=8))
    model = MagicMock()
    model.predict.return_value = [0.5]
    reranker._model = model
    chunk = _chunk(content="abcdefghijklmnop")
    scored = reranker.rerank("q", [chunk])
    pairs = model.predict.call_args.args[0]
    assert pairs == [("q", "abcdefgh")]
    assert chunk.content == "abcdefghijklmnop"
    assert scored[0].content == "abcdefghijklmnop"
    assert str(chunk.chunk_id) in caplog.text


def test_no_model_construction_when_reranking_disabled(db_session, monkeypatch):
    constructed = []

    class Tracking:
        def __init__(self, settings):
            constructed.append(settings)

        def rerank(self, query, candidates):
            raise AssertionError("reranker should not run")

    monkeypatch.setattr("app.services.rerank.LocalCrossEncoderReranker", Tracking)
    document = _completed_document(
        db_session,
        "policy.pdf",
        [("Customers may request a refund within 30 days of purchase.", 1, _vector(1, 0))],
    )
    disabled = RetrievalService(
        db_session,
        settings=make_settings(retrieval_mode="hybrid", reranking_enabled=False),
    )
    disabled.retrieve(
        _vector(1, 0),
        top_k=5,
        similarity_threshold=0.5,
        document_ids=[document.id],
        question="refund period",
        retrieval_mode="hybrid",
    )
    dense = RetrievalService(
        db_session,
        settings=make_settings(retrieval_mode="dense", reranking_enabled=True),
    )
    dense.retrieve(
        _vector(1, 0),
        top_k=5,
        similarity_threshold=0.5,
        document_ids=[document.id],
        question="refund period",
        retrieval_mode="dense",
    )
    assert constructed == []


def test_lazy_model_construction_when_reranking_enabled(db_session, monkeypatch):
    constructed = []

    class Tracking:
        def __init__(self, settings):
            constructed.append(settings)
            self._inner = FakeReranker()

        def rerank(self, query, candidates):
            return self._inner.rerank(query, candidates)

    monkeypatch.setattr("app.services.rerank.LocalCrossEncoderReranker", Tracking)
    document = _completed_document(
        db_session,
        "policy.pdf",
        [("Customers may request a refund within 30 days of purchase.", 1, _vector(1, 0))],
    )
    service = RetrievalService(
        db_session,
        settings=make_settings(
            retrieval_mode="hybrid",
            reranking_enabled=True,
            reranking_fallback=False,
        ),
    )
    assert constructed == []
    service.retrieve(
        _vector(1, 0),
        top_k=5,
        similarity_threshold=0.5,
        document_ids=[document.id],
        question="refund period",
        retrieval_mode="hybrid",
    )
    assert len(constructed) == 1
    service.retrieve(
        _vector(1, 0),
        top_k=5,
        similarity_threshold=0.5,
        document_ids=[document.id],
        question="refund period",
        retrieval_mode="hybrid",
    )
    assert len(constructed) == 1


def test_rrf_pool_expands_when_reranking_enabled(db_session, monkeypatch):
    captured: dict[str, int] = {}

    def fake_fuse(*args, **kwargs):
        captured["top_k"] = kwargs["top_k"]
        return []

    monkeypatch.setattr("app.services.fusion.rrf_fuse", fake_fuse)
    _completed_document(
        db_session,
        "policy.pdf",
        [("Refund within 30 days.", 1, _vector(1, 0))],
    )
    enabled = _rerank_service(db_session, FakeReranker(), rerank_candidate_k=20)
    enabled.retrieve(
        _vector(1, 0),
        top_k=5,
        similarity_threshold=0.5,
        question="refund",
        retrieval_mode="hybrid",
    )
    assert captured["top_k"] == 20


def test_rrf_remains_top_k_when_reranking_disabled(db_session, monkeypatch):
    captured: dict[str, int] = {}

    def fake_fuse(*args, **kwargs):
        captured["top_k"] = kwargs["top_k"]
        return []

    monkeypatch.setattr("app.services.fusion.rrf_fuse", fake_fuse)
    service = RetrievalService(
        db_session,
        settings=make_settings(retrieval_mode="hybrid", reranking_enabled=False),
    )
    service.retrieve(
        _vector(1, 0),
        top_k=5,
        similarity_threshold=0.5,
        question="refund",
        retrieval_mode="hybrid",
    )
    assert captured["top_k"] == 5


def test_candidate_order_before_rerank_is_rrf_order(db_session):
    ids = [uuid4() for _ in range(3)]
    fused = [
        _chunk(content="first", chunk_id=ids[0], score=0.5),
        _chunk(content="second", chunk_id=ids[1], score=0.4),
        _chunk(content="third", chunk_id=ids[2], score=0.3),
    ]
    reranker = FakeReranker(scores=[0.1, 0.2, 0.3])
    service = _rerank_service(db_session, reranker, rag_top_k=3)
    service._dense = lambda *args, **kwargs: []  # type: ignore[method-assign]
    service._lexical = lambda *args, **kwargs: []  # type: ignore[method-assign]

    def fake_fuse(*args, **kwargs):
        return fused

    import app.services.fusion as fusion_mod

    original = fusion_mod.rrf_fuse
    fusion_mod.rrf_fuse = fake_fuse
    try:
        results = service.retrieve(
            _vector(1, 0),
            top_k=3,
            similarity_threshold=0.0,
            question="q",
            retrieval_mode="hybrid",
        )
    finally:
        fusion_mod.rrf_fuse = original
    assert reranker.calls[0][1] == ids
    assert [chunk.chunk_id for chunk in results] == list(reversed(ids))


def test_descending_rerank_cosine_and_chunk_id_tie_breaks(db_session):
    low_id = UUID("00000000-0000-0000-0000-000000000001")
    high_id = UUID("00000000-0000-0000-0000-000000000002")
    fused = [
        _chunk(content="a", chunk_id=high_id, score=0.4),
        _chunk(content="b", chunk_id=low_id, score=0.9),
        _chunk(content="c", chunk_id=uuid4(), score=0.2),
    ]
    # Equal rerank scores for first two → cosine then chunk_id.
    reranker = FakeReranker(scores=[1.0, 1.0, 0.1])
    service = _rerank_service(db_session, reranker, rag_top_k=5)

    def fake_fuse(*args, **kwargs):
        return fused

    import app.services.fusion as fusion_mod

    original = fusion_mod.rrf_fuse
    fusion_mod.rrf_fuse = fake_fuse
    try:
        results = service.retrieve(
            _vector(1, 0),
            top_k=5,
            similarity_threshold=0.0,
            question="q",
            retrieval_mode="hybrid",
        )
    finally:
        fusion_mod.rrf_fuse = original
    assert results[0].chunk_id == low_id
    assert results[1].chunk_id == high_id
    assert results[0].similarity_score == 0.9


def test_final_top_k_truncation_after_rerank(db_session):
    fused = [_chunk(content=f"c{i}", score=0.5 - i * 0.01) for i in range(8)]
    reranker = FakeReranker(scores=list(range(8, 0, -1)))
    service = _rerank_service(db_session, reranker)

    def fake_fuse(*args, **kwargs):
        return fused

    import app.services.fusion as fusion_mod

    original = fusion_mod.rrf_fuse
    fusion_mod.rrf_fuse = fake_fuse
    try:
        results = service.retrieve(
            _vector(1, 0),
            top_k=5,
            similarity_threshold=0.0,
            question="q",
            retrieval_mode="hybrid",
        )
    finally:
        fusion_mod.rrf_fuse = original
    assert len(results) == 5
    assert service.last_rerank_candidate_count == 8
    assert all(chunk.retrieval_mode == "hybrid+rerank" for chunk in results)


def test_document_ids_empty_prevents_reranking(db_session):
    reranker = FakeReranker()
    service = _rerank_service(db_session, reranker)
    results = service.retrieve(
        _vector(1, 0),
        top_k=5,
        similarity_threshold=0.7,
        document_ids=[],
        question="What is POL-HR-2041?",
        retrieval_mode="hybrid",
    )
    assert results == []
    assert reranker.calls == []


def test_metadata_filters_remain_enforced_with_rerank(db_session):
    policy = _completed_document(
        db_session,
        "policy.pdf",
        [("Sharedtoken refund language in policy.", 1, _vector(1, 0))],
        category="policy",
    )
    _completed_document(
        db_session,
        "finance.pdf",
        [("Sharedtoken refund language in finance.", 1, _vector(1, 0))],
        category="finance",
    )
    reranker = FakeReranker()
    results = _rerank_service(db_session, reranker).retrieve(
        _vector(1, 0),
        top_k=5,
        similarity_threshold=0.0,
        filters=RetrievalFilters(category="policy"),
        question="Sharedtoken refund",
        retrieval_mode="hybrid",
    )
    assert results
    assert all(chunk.filename == "policy.pdf" for chunk in results)
    assert all(chunk.document_id == policy.id for chunk in results)
    assert reranker.calls


def test_lexical_only_below_cosine_threshold_can_be_reranked(db_session):
    document = _completed_document(
        db_session,
        "handbook.pdf",
        [("The employee code of conduct identifier is POL-HR-2041.", 2, _vector(0, 1))],
    )
    reranker = FakeReranker(scores=[0.99])
    results = _rerank_service(db_session, reranker).retrieve(
        _vector(1, 0),
        top_k=5,
        similarity_threshold=0.7,
        document_ids=[document.id],
        question="What is POL-HR-2041?",
        retrieval_mode="hybrid",
    )
    assert len(results) == 1
    assert results[0].similarity_score < 0.7
    assert results[0].rerank_score == 0.99
    assert results[0].lexical_rank == 1


def test_chat_fallback_uses_rrf_ordering(db_session, caplog):
    document = _completed_document(
        db_session,
        "policy.pdf",
        [("Customers may request a refund within 30 days of purchase.", 1, _vector(1, 0))],
    )
    reranker = FakeReranker(error=RerankError("model failed"))
    service = _rerank_service(db_session, reranker, reranking_fallback=True)
    results = service.retrieve(
        _vector(1, 0),
        top_k=5,
        similarity_threshold=0.5,
        document_ids=[document.id],
        question="refund period",
        retrieval_mode="hybrid",
    )
    assert results
    assert results[0].rerank_fallback is True
    assert results[0].retrieval_mode == "hybrid"
    assert service.last_rerank_fallback is True
    payload = debug_payload("refund period", results)
    assert payload["rerank_fallback"] is True
    assert "RERANK failed; using RRF ordering" in caplog.text


def test_evaluation_does_not_fallback(db_session):
    document = _completed_document(
        db_session,
        "policy.pdf",
        [("Customers may request a refund within 30 days of purchase.", 1, _vector(1, 0))],
    )
    reranker = FakeReranker(error=RerankError("model failed"))
    service = _rerank_service(db_session, reranker, reranking_fallback=False)
    with pytest.raises(RerankError, match="model failed"):
        service.retrieve(
            _vector(1, 0),
            top_k=5,
            similarity_threshold=0.5,
            document_ids=[document.id],
            question="refund period",
            retrieval_mode="hybrid",
        )


def test_public_api_does_not_expose_rerank_score():
    chunk = _chunk()
    chunk = replace(chunk, rerank_score=9.9, pre_rerank_rank=3, rrf_score=0.02)
    sources = sources_from_chunks([chunk])
    assert sources[0].similarity_score == chunk.similarity_score
    assert not hasattr(sources[0], "rerank_score")
    dumped = ChatSource(
        document_id=sources[0].document_id,
        filename=sources[0].filename,
        page_number=sources[0].page_number,
        chunk_index=sources[0].chunk_index,
        similarity_score=sources[0].similarity_score,
    ).model_dump()
    assert set(dumped) == {
        "document_id",
        "filename",
        "page_number",
        "chunk_index",
        "similarity_score",
    }
    request = ChatRequest.model_validate({"question": "What is the refund period?"})
    assert not hasattr(request, "reranking_enabled")


def test_citations_still_use_cosine_after_rerank(db_session):
    document = _completed_document(
        db_session,
        "policy.pdf",
        [("Customers may request a refund within 30 days of purchase.", 1, _vector(1, 0))],
    )
    results = _rerank_service(db_session, FakeReranker(scores=[4.2])).retrieve(
        _vector(1, 0),
        top_k=5,
        similarity_threshold=0.5,
        document_ids=[document.id],
        question="refund period",
        retrieval_mode="hybrid",
    )
    sources = sources_from_chunks(results)
    assert sources[0].similarity_score == results[0].similarity_score
    assert sources[0].similarity_score != 4.2


def test_exactly_one_gemini_embedding_with_rerank():
    provider = MagicMock()
    provider.create_embedding.return_value = [0.2] * 768
    retrieval = MagicMock()
    retrieval.retrieve.return_value = []
    settings = make_settings(retrieval_mode="hybrid", reranking_enabled=True)
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


def test_streaming_waits_for_rerank_before_first_sse_token(db_session):
    if not postgres_available():
        pytest.skip("PostgreSQL is not available for API tests.")
    document = _completed_document(
        db_session,
        "company-policy.pdf",
        [("Customers may request a refund within 30 days of purchase.", 1, _vector(1, 0))],
    )
    order: list[str] = []

    class RecordingReranker:
        def rerank(self, query, candidates):
            order.append("rerank")
            return [
                replace(chunk, rerank_score=1.0, pre_rerank_rank=index)
                for index, chunk in enumerate(candidates, start=1)
            ]

    provider = MagicMock()
    provider.create_embedding.return_value = _vector(1, 0)

    def stream_text(prompt):
        order.append("stream")
        return iter(["The", " refund"])

    provider.stream_text.side_effect = stream_text
    settings = make_settings(
        retrieval_mode="hybrid",
        reranking_enabled=True,
        reranking_fallback=False,
        rag_similarity_threshold=0.2,
    )
    rag = RagService(
        session=db_session,
        settings=settings,
        embedding_service=EmbeddingService(provider, settings),
        retrieval=RetrievalService(db_session, settings=settings, reranker=RecordingReranker()),
        provider=provider,
    )
    service = ConversationService(session=db_session, settings=settings, rag=rag, autocommit=False)

    def override_service() -> ConversationService:
        return service

    def override_db():
        yield db_session

    app.dependency_overrides[get_conversation_service] = override_service
    app.dependency_overrides[get_db] = override_db
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/chat/stream",
                json={
                    "question": "What is the refund period?",
                    "filters": {"document_ids": [str(document.id)]},
                },
            )
    finally:
        app.dependency_overrides.clear()
    events = parse_sse(response.text)
    names = [name for name, _payload in events]
    assert names[0] == "start"
    assert "token" in names
    assert order == ["rerank", "stream"]
    sources = next(payload for name, payload in events if name == "sources")["sources"]
    assert sources[0]["filename"] == "company-policy.pdf"
    assert "rerank_score" not in sources[0]
    assert document.id


def test_timings_include_rerank_and_total(db_session):
    document = _completed_document(
        db_session,
        "policy.pdf",
        [("Customers may request a refund within 30 days of purchase.", 1, _vector(1, 0))],
    )
    service = _rerank_service(db_session, FakeReranker())
    service.retrieve(
        _vector(1, 0),
        top_k=5,
        similarity_threshold=0.5,
        document_ids=[document.id],
        question="refund period",
        retrieval_mode="hybrid",
    )
    assert "dense" in service.last_timings_ms
    assert "lexical" in service.last_timings_ms
    assert "rrf" in service.last_timings_ms
    assert "rerank" in service.last_timings_ms
    assert "total" in service.last_timings_ms
    assert service.last_timings_ms["total"] >= service.last_timings_ms["rerank"]
