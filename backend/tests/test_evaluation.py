import json
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.db.models import Document, DocumentChunk, DocumentStatus
from app.services.ai.errors import AIConfigurationError, EmbeddingDimensionError
from app.services.ai.provider import EmbeddingTask
from app.services.chunker import Chunker
from app.services.embedding_service import EmbeddingService
from app.services.pdf_parser import PageText
from app.services.retrieval import RetrievalService
from evaluation.corpus import operations_manual_long_page
from evaluation.embedders import embedding_model_label, embedding_service_for
from evaluation.evaluator import (
    LEXICAL_DATASET,
    RetrievalEvaluator,
    apply_threshold_and_limit,
    load_dataset,
)
from evaluation.local_embedder import LocalHashEmbeddingProvider
from evaluation.metrics import (
    ExpectedSource,
    QuestionResult,
    candidate_pool_k,
    hit_at_k,
    recall_at_k,
    reciprocal_rank,
    scored_hit_at_k,
    summarize,
)
from evaluation.report import (
    format_chunk_comparison,
    format_metadata_filter_comparison,
    format_report,
    format_retrieval_comparison,
    format_retrieval_mode_comparison,
    format_span_inspection,
    format_strategy_comparison,
    metrics_to_dict,
    retrieval_mode_outcomes,
    write_json_report,
)
from tests.conftest import make_settings


def test_dataset_has_required_question_types_and_is_not_in_app_code():
    dataset = load_dataset()
    types = {item["type"] for item in dataset["questions"]}
    assert 20 <= len(dataset["questions"]) <= 30
    assert {
        "direct_factual",
        "paraphrased",
        "multi_chunk",
        "multi_relevant",
        "similar_distractor",
        "identifier",
        "no_context",
        "prompt_injection",
    }.issubset(types)
    assert any(item["expect_no_context"] for item in dataset["questions"])
    assert any(len(item["expected_sources"]) > 1 for item in dataset["questions"])
    assert any(item.get("expected_span") for item in dataset["questions"])
    from app.services import rag as rag_module

    rag_source = Path(rag_module.__file__).read_text(encoding="utf-8")
    assert "rag_eval.json" not in rag_source
    assert "evaluation.datasets" not in rag_source


def test_lexical_dataset_uses_corpus_identifiers_and_does_not_replace_frozen_set():
    frozen = load_dataset()
    lexical = load_dataset(LEXICAL_DATASET)
    from evaluation.corpus import (
        COMPANY_POLICY_PAGES,
        EMPLOYEE_HANDBOOK_PAGES,
        INJECTION_PROBE_PAGES,
        PRICING_GUIDE_PAGES,
        operations_manual_long_page,
    )

    assert len(frozen["questions"]) == 29
    assert [item["id"] for item in lexical["questions"]] == [f"L{i}" for i in range(1, 11)]
    corpus = "\n".join(
        [
            *COMPANY_POLICY_PAGES,
            *EMPLOYEE_HANDBOOK_PAGES,
            *PRICING_GUIDE_PAGES,
            operations_manual_long_page(),
            *INJECTION_PROBE_PAGES,
        ]
    )
    for item in lexical["questions"]:
        for source in item["expected_sources"]:
            assert source["document"] in {
                "company-policy.pdf",
                "employee-handbook.pdf",
                "pricing-guide.pdf",
                "operations-manual.pdf",
                "injection-probe.pdf",
            }
        span = item.get("expected_span")
        if span:
            assert span in corpus
        if "POL-HR-2041" in item["question"]:
            assert "POL-HR-2041" in corpus
        if "SKU-PRO-99" in item["question"]:
            assert "SKU-PRO-99" in corpus


def test_hit_and_recall_metrics():
    expected = [
        ExpectedSource("company-policy.pdf", 4),
        ExpectedSource("company-policy.pdf", 5),
    ]
    retrieved = [
        {"filename": "company-policy.pdf", "page_number": 4, "rank": 1},
        {"filename": "company-policy.pdf", "page_number": 5, "rank": 2},
        {"filename": "pricing-guide.pdf", "page_number": 2, "rank": 3},
    ]
    assert hit_at_k(expected, retrieved, 1) is True
    assert hit_at_k(expected, retrieved, 3) is True
    assert recall_at_k(expected, retrieved, 1) == 0.5
    assert recall_at_k(expected, retrieved, 5) == 1.0

    miss = [{"filename": "pricing-guide.pdf", "page_number": 2, "rank": 1}]
    assert hit_at_k(expected, miss, 5) is False


def test_hit_at_5_is_omitted_when_candidate_pool_is_3():
    expected = [ExpectedSource("company-policy.pdf", 4)]
    retrieved = [
        {"filename": "company-policy.pdf", "page_number": 4, "rank": 1},
        {"filename": "company-policy.pdf", "page_number": 5, "rank": 2},
        {"filename": "pricing-guide.pdf", "page_number": 2, "rank": 3},
    ]
    assert candidate_pool_k(3) == 5
    assert scored_hit_at_k(expected, retrieved, 1, pool_k=3) is True
    assert scored_hit_at_k(expected, retrieved, 3, pool_k=3) is True
    assert scored_hit_at_k(expected, retrieved, 5, pool_k=3) is None


def test_apply_threshold_and_limit_matches_production_order():
    ranked = [
        {"filename": "a.pdf", "page_number": 1, "score": 0.9, "rank": 1},
        {"filename": "b.pdf", "page_number": 2, "score": 0.6, "rank": 2},
        {"filename": "c.pdf", "page_number": 3, "score": 0.4, "rank": 3},
    ]
    sliced = apply_threshold_and_limit(ranked, top_k=1, similarity_threshold=0.5)
    assert [item["filename"] for item in sliced] == ["a.pdf"]


def test_no_context_summary():
    results = [
        QuestionResult(
            question_id="Q1",
            question="What is the refund period?",
            question_type="direct_factual",
            expect_no_context=False,
            expected_sources=[ExpectedSource("company-policy.pdf", 1)],
            retrieved=[{"filename": "company-policy.pdf", "page_number": 1, "rank": 1, "score": 0.9}],
            hit_at_1=True,
            hit_at_3=True,
            hit_at_5=True,
            recall_at_5=1.0,
            no_context_correct=None,
            top1_similarity=0.9,
            expected_answer="30 days",
            generated_answer=None,
        ),
        QuestionResult(
            question_id="Q2",
            question="Who is the CEO?",
            question_type="no_context",
            expect_no_context=True,
            expected_sources=[],
            retrieved=[],
            hit_at_1=None,
            hit_at_3=None,
            hit_at_5=None,
            recall_at_5=None,
            no_context_correct=True,
            top1_similarity=0.0,
        ),
        QuestionResult(
            question_id="Q3",
            question="What is annual revenue?",
            question_type="no_context",
            expect_no_context=True,
            expected_sources=[],
            retrieved=[{"filename": "pricing-guide.pdf", "page_number": 1, "rank": 1, "score": 0.4}],
            hit_at_1=None,
            hit_at_3=None,
            hit_at_5=None,
            recall_at_5=None,
            no_context_correct=False,
            top1_similarity=0.4,
        ),
    ]
    metrics = summarize(results, requested_top_k=5, pool_k=5)
    assert metrics.questions_evaluated == 3
    assert metrics.hit_at_1 == 1.0
    assert metrics.no_context_correct == 1
    assert metrics.no_context_total == 2
    assert metrics.no_context_false_retrieval == 1
    report = format_report(
        metrics,
        chunk_size=700,
        chunk_overlap=100,
        top_k=5,
        similarity_threshold=0.7,
        embedder="local",
        embedding_model="local-hash-ngram",
    )
    assert "Hit@1: 100%" in report
    assert "OFFLINE / LOCAL EMBEDDER" in report
    assert "Correctly rejected: 1/2" in report


def test_json_report_is_machine_readable_and_omits_secrets(tmp_path: Path):
    metrics = summarize(
        [
            QuestionResult(
                question_id="Q1",
                question="What is the refund period?",
                question_type="direct_factual",
                expect_no_context=False,
                expected_sources=[ExpectedSource("company-policy.pdf", 1)],
                retrieved=[{"filename": "company-policy.pdf", "page_number": 1, "rank": 1, "score": 0.9}],
                hit_at_1=True,
                hit_at_3=True,
                hit_at_5=None,
                recall_at_5=None,
                no_context_correct=None,
                top1_similarity=0.9,
                expected_answer="30 days",
                generated_answer=None,
                candidate_pool_k=3,
            )
        ],
        requested_top_k=3,
        pool_k=3,
    )
    payload = metrics_to_dict(
        metrics,
        chunk_size=700,
        chunk_overlap=100,
        top_k=3,
        similarity_threshold=0.7,
        embedder="gemini",
        embedding_model="gemini-embedding-2",
        dataset_version="1.1.1",
        timestamp="2026-01-01T00:00:00Z",
    )
    serialized = json.dumps(payload)
    assert payload["timestamp"] == "2026-01-01T00:00:00Z"
    assert payload["embedding_model"] == "gemini-embedding-2"
    assert payload["questions"][0]["expected_answer"] == "30 days"
    assert payload["questions"][0]["generated_answer"] is None
    assert payload["questions"][0]["hit_at_5"] is None
    assert "api_key" not in serialized.lower()
    assert "authorization" not in serialized.lower()
    destination = tmp_path / "retrieval_test.json"
    write_json_report(payload, destination)
    loaded = json.loads(destination.read_text(encoding="utf-8"))
    assert loaded["summary"]["hit_at_1"] == 1.0


def test_comparison_report_uses_provided_metrics():
    chunk_report = format_chunk_comparison(
        [
            {
                "chunk_size": 500,
                "chunk_overlap": 50,
                "hit_at_1": 0.5,
                "hit_at_3": 0.8,
                "hit_at_5": 0.9,
                "recall_at_5": 0.7,
                "span_hit_at_5": 0.6,
            },
        ]
    )
    retrieval_report = format_retrieval_comparison(
        [
            {
                "top_k": 3,
                "similarity_threshold": 0.7,
                "hit_at_1": 0.5,
                "hit_at_3": 0.7,
                "hit_at_5": None,
                "recall_at_5": None,
                "no_context_correct": 4,
                "no_context_total": 5,
                "average_similarity": 0.4,
            }
        ]
    )
    assert "500 / 50" in chunk_report
    assert "n/a" in retrieval_report
    assert "4/5" in retrieval_report


def test_strategy_comparison_report_keeps_size_constant():
    report = format_strategy_comparison(
        [
            {
                "chunking_strategy": "fixed_word_window",
                "hit_at_1": 0.96,
                "hit_at_3": 1.0,
                "hit_at_5": 1.0,
                "span_hit_at_5": 0.67,
                "recall_at_5": 1.0,
                "total_chunk_count": 20,
                "average_words_per_chunk": 140.5,
            },
            {
                "chunking_strategy": "recursive",
                "hit_at_1": 0.96,
                "hit_at_3": 1.0,
                "hit_at_5": 1.0,
                "span_hit_at_5": 0.67,
                "recall_at_5": 1.0,
                "total_chunk_count": 21,
                "average_words_per_chunk": 130.0,
            },
        ]
    )
    assert "fixed_word_window" in report
    assert "recursive" in report
    assert "Only the chunking strategy changes" in report
    inspection = format_span_inspection(
        [
            {
                "chunking_strategy": "fixed_word_window",
                "chunk_size": 700,
                "chunk_overlap": 100,
                "span_questions": [
                    {
                        "id": "Q28",
                        "question": "What is the spare-part lead time?",
                        "expected_span": "12 business days",
                        "span_hit_at_5": False,
                        "filename": "operations-manual.pdf",
                        "page_number": 1,
                        "chunk_index": 1,
                        "score": 0.700284,
                        "content": "Depot managers confirm spare-part orders.",
                        "span_in_top_chunk": False,
                    }
                ],
            }
        ]
    )
    assert "Q28" in inspection
    assert "12 business days" in inspection


def test_compare_chunking_strategies_cannot_combine_with_other_compare_flags():
    from evaluation.run import parse_args, main

    args = parse_args(["--compare-chunking-strategies"])
    assert args.compare_chunking_strategies is True
    assert main(["--compare-chunks", "--compare-chunking-strategies"]) == 2
    assert main(["--compare-retrieval-modes", "--compare-metadata-filters"]) == 2
    args = parse_args(["--compare-retrieval-modes"])
    assert args.compare_retrieval_modes is True
    assert parse_args(["--retrieval-mode", "hybrid"]).retrieval_mode == "hybrid"
    args = parse_args(["--compare-reranking"])
    assert args.compare_reranking is True
    assert main(["--compare-reranking", "--compare-retrieval-modes"]) == 2
    assert parse_args(["--enable-rerank"]).enable_rerank is True


def test_format_retrieval_mode_comparison_and_outcomes():
    from evaluation.metrics import ExpectedSource, QuestionResult, RetrievalMetrics

    def metrics(hit_dense: bool, hit_lex: bool) -> RetrievalMetrics:
        return RetrievalMetrics(
            questions_evaluated=1,
            grounded_questions=1,
            no_context_questions=0,
            hit_at_1=1.0 if hit_dense else 0.0,
            hit_at_3=1.0 if hit_dense else 0.0,
            hit_at_5=1.0 if hit_dense else 0.0,
            recall_at_5=1.0 if hit_dense else 0.0,
            average_similarity=0.8,
            no_context_correct=0,
            no_context_total=0,
            no_context_false_retrieval=0,
            requested_top_k=5,
            candidate_pool_k=5,
            question_results=[
                QuestionResult(
                    question_id="L1",
                    question="What is POL-HR-2041?",
                    question_type="identifier",
                    expect_no_context=False,
                    expected_sources=[ExpectedSource("employee-handbook.pdf", 2)],
                    retrieved=[],
                    hit_at_1=hit_dense,
                    hit_at_3=hit_dense,
                    hit_at_5=hit_lex if hit_lex != hit_dense else hit_dense,
                    recall_at_5=1.0 if hit_dense or hit_lex else 0.0,
                    no_context_correct=None,
                    top1_similarity=0.5,
                )
            ],
        )

    dense = metrics(False, False)
    dense.question_results[0].hit_at_5 = False
    lexical = metrics(False, True)
    lexical.question_results[0].hit_at_5 = True
    hybrid = metrics(False, True)
    hybrid.question_results[0].hit_at_5 = True
    outcomes = retrieval_mode_outcomes(dense, lexical, hybrid)
    assert outcomes["lexical_only_wins"] == 1
    assert outcomes["hybrid_wins"] == 1
    text = format_retrieval_mode_comparison(
        [
            {
                "retrieval_mode": "dense",
                "hit_at_1": 0.96,
                "hit_at_3": 1.0,
                "hit_at_5": 1.0,
                "recall_at_5": 1.0,
                "span_hit_at_5": 0.67,
                "average_retrieved_count": 5.0,
                "average_retrieval_ms": 12.0,
            }
        ],
        outcomes,
    )
    assert "dense" in text
    assert "lexical-only wins" in text


def test_local_embedder_is_deterministic_and_does_not_generate():
    provider = LocalHashEmbeddingProvider(768)
    first = provider.create_embedding("refund period 30 days", EmbeddingTask.QUERY)
    second = provider.create_embedding("refund period 30 days", EmbeddingTask.QUERY)
    other = provider.create_embedding("enterprise annual price", EmbeddingTask.DOCUMENT)
    assert first == second
    assert len(first) == 768
    assert first != other
    assert sum(value * value for value in first) == pytest.approx(1.0, rel=1e-5)
    with pytest.raises(AIConfigurationError):
        provider.generate_text("unused")


def test_gemini_embedder_uses_production_embedding_service(monkeypatch):
    provider = MagicMock()
    provider.create_embedding.return_value = [0.1] * 768
    monkeypatch.setattr("evaluation.embedders.get_ai_provider", lambda: provider)
    settings = make_settings()
    service = embedding_service_for("gemini", settings)
    assert isinstance(service, EmbeddingService)
    vector = service.embed_query("What is the refund period?")
    assert len(vector) == settings.embedding_dimension
    provider.create_embedding.assert_called_once()
    assert provider.create_embedding.call_args.args[1] is EmbeddingTask.QUERY
    assert embedding_model_label("gemini", settings) == "gemini-embedding-2"


def test_gemini_embedder_validates_dimension(monkeypatch):
    provider = MagicMock()
    provider.create_embedding.return_value = [0.1] * 8
    monkeypatch.setattr("evaluation.embedders.get_ai_provider", lambda: provider)
    service = embedding_service_for("gemini", make_settings())
    with pytest.raises(EmbeddingDimensionError):
        service.embed_query("What is the refund period?")


def test_long_eval_page_splits_under_smaller_windows():
    text = operations_manual_long_page()
    assert len(text.split()) >= 900
    assert "OPS-ROT-3300" in text
    assert "12 business days" in text
    pages = [PageText(page_number=1, text=text)]
    small = Chunker(500, 50).chunk(pages)
    large = Chunker(1000, 150).chunk(pages)
    assert len(small) > len(large)
    assert all(chunk.content for chunk in small)


def _eval_harness(db_session, tmp_path: Path, chunk_size: int = 700, chunk_overlap: int = 100):
    settings = make_settings(storage_path=str(tmp_path), chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    embeddings = EmbeddingService(LocalHashEmbeddingProvider(768), settings)
    return RetrievalEvaluator(
        db_session,
        embeddings,
        settings,
        str(tmp_path),
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
    )


def test_retrieval_evaluation_runs_without_gemini(db_session, tmp_path: Path):
    evaluator = _eval_harness(db_session, tmp_path)
    document_ids = evaluator.ingest_corpus()
    dataset = load_dataset()
    metrics = evaluator.evaluate(
        dataset,
        document_ids,
        top_k=5,
        similarity_threshold=0.0,
    )

    assert metrics.questions_evaluated == len(dataset["questions"])
    assert metrics.grounded_questions == 24
    assert metrics.no_context_questions == 5
    assert metrics.candidate_pool_k == 5
    assert metrics.hit_at_1 is not None
    assert 0.0 <= metrics.hit_at_1 <= 1.0
    assert metrics.hit_at_5 is not None
    identifiers = [item for item in metrics.question_results if item.question_id == "Q16"]
    assert identifiers[0].hit_at_5 is True
    refund = [item for item in metrics.question_results if item.question_id == "Q1"][0]
    assert refund.expected_answer
    assert refund.generated_answer is None
    assert "rank" in refund.retrieved[0]


def test_evaluate_lexical_and_hybrid_modes_on_identifier_question(db_session, tmp_path: Path):
    evaluator = _eval_harness(db_session, tmp_path)
    document_ids = evaluator.ingest_corpus()
    dataset = load_dataset(LEXICAL_DATASET)
    subset = {"questions": [item for item in dataset["questions"] if item["id"] == "L1"]}
    lexical = evaluator.evaluate(
        subset,
        document_ids,
        top_k=5,
        similarity_threshold=0.0,
        retrieval_mode="lexical",
    )
    hybrid = evaluator.evaluate(
        subset,
        document_ids,
        top_k=5,
        similarity_threshold=0.0,
        retrieval_mode="hybrid",
    )
    assert lexical.questions_evaluated == 1
    assert hybrid.questions_evaluated == 1
    assert lexical.question_results[0].retrieved_count >= 1
    assert hybrid.question_results[0].retrieved_count >= 1


def test_evaluate_with_top_k_3_still_scores_hit_at_5_from_pool_of_5(db_session, tmp_path: Path):
    evaluator = _eval_harness(db_session, tmp_path)
    document_ids = evaluator.ingest_corpus()
    calls: list[int] = []
    original = evaluator._retrieval.retrieve

    def wrapped(*args, **kwargs):
        calls.append(kwargs["top_k"])
        return original(*args, **kwargs)

    evaluator._retrieval.retrieve = wrapped
    metrics = evaluator.evaluate(
        load_dataset(),
        document_ids,
        top_k=3,
        similarity_threshold=0.0,
    )
    assert calls
    assert all(value == 5 for value in calls)
    assert metrics.requested_top_k == 3
    assert metrics.candidate_pool_k == 5
    assert metrics.hit_at_5 is not None


def test_no_context_questions_are_empty_at_production_threshold(db_session, tmp_path: Path):
    evaluator = _eval_harness(db_session, tmp_path)
    document_ids = evaluator.ingest_corpus()
    metrics = evaluator.evaluate(
        load_dataset(),
        document_ids,
        top_k=5,
        similarity_threshold=0.7,
    )
    no_context = [item for item in metrics.question_results if item.expect_no_context]
    assert len(no_context) == 5
    assert metrics.no_context_total == 5


def test_evaluation_corpus_is_isolated_from_other_documents(db_session, tmp_path: Path):
    decoy = Document(
        id=uuid4(),
        filename="original.pdf",
        original_filename="unrelated-production.pdf",
        file_path="/storage/documents/test/original.pdf",
        file_type="application/pdf",
        file_size=12,
        status=DocumentStatus.COMPLETED,
        page_count=1,
    )
    db_session.add(decoy)
    db_session.flush()
    values = [0.0] * 768
    values[0] = 1.0
    db_session.add(
        DocumentChunk(
            document_id=decoy.id,
            chunk_index=0,
            content="unrelated production chunk that must not be scored",
            page_number=1,
            embedding=values,
            chunk_metadata={"filename": "unrelated-production.pdf"},
        )
    )
    db_session.flush()

    evaluator = _eval_harness(db_session, tmp_path)
    document_ids = evaluator.ingest_corpus()
    metrics = evaluator.evaluate(
        load_dataset(),
        document_ids,
        top_k=5,
        similarity_threshold=0.0,
    )
    filenames = {
        row["filename"]
        for item in metrics.question_results
        for row in item.retrieved
    }
    assert "unrelated-production.pdf" not in filenames
    outside = RetrievalService(db_session).retrieve(
        values,
        top_k=5,
        similarity_threshold=0.0,
        document_ids=list(document_ids.values()),
    )
    assert all(item.document_id != decoy.id for item in outside)


def test_eval_corpus_receives_document_metadata(db_session, tmp_path: Path):
    from app.repositories.document_repository import DocumentRepository
    from evaluation.corpus import EVAL_DOCUMENTS

    evaluator = _eval_harness(db_session, tmp_path)
    document_ids = evaluator.ingest_corpus()
    repo = DocumentRepository(db_session)
    expected = {item["filename"]: item for item in EVAL_DOCUMENTS}
    for filename, document_id in document_ids.items():
        stored = repo.get_by_id(document_id)
        assert stored is not None
        assert stored.category == expected[filename]["category"]
        assert stored.source == expected[filename]["source"]
        assert stored.tags == expected[filename]["tags"]


def test_metadata_filter_evaluation_cases(db_session, tmp_path: Path):
    from evaluation.filter_cases import FILTER_CASES

    evaluator = _eval_harness(db_session, tmp_path)
    document_ids = evaluator.ingest_corpus()
    results = {
        item.question_id: item
        for item in evaluator.evaluate_filter_cases(
            document_ids,
            FILTER_CASES,
            top_k=5,
            similarity_threshold=0.0,
        )
    }
    policy_name = "company-policy.pdf"
    assert results["F1"].retrieved_count >= 1
    assert all(row["filename"] == policy_name for row in results["F2"].retrieved)
    assert results["F2"].retrieved_count >= 1
    assert all(row["filename"] != policy_name for row in results["F3"].retrieved)
    assert all(row["filename"] == policy_name for row in results["F4"].retrieved)
    assert results["F5"].retrieved_count == 0
    assert results["F5"].no_context_correct is True
    assert results["F6"].retrieved_count == 0
    assert results["F6"].no_context_correct is True
    assert all(
        row["filename"] == policy_name and row["page_number"] == 1
        for row in results["F7"].retrieved
    )
    assert results["F7"].retrieved_count >= 1
    assert all(row["filename"] == policy_name for row in results["F8"].retrieved)
    assert results["F8"].retrieved_count >= 1
    assert results["F9"].retrieved_count == 0
    assert results["F9"].no_context_correct is True


def test_empty_document_ids_still_isolates_evaluation(db_session, tmp_path: Path):
    evaluator = _eval_harness(db_session, tmp_path)
    evaluator.ingest_corpus()
    empty = RetrievalService(db_session).retrieve(
        [0.0] * 768,
        top_k=5,
        similarity_threshold=0.0,
        document_ids=[],
    )
    assert empty == []


def test_evaluate_rerank_does_not_fallback(db_session, tmp_path: Path):
    from app.services.rerank import RerankError

    class Boom:
        def rerank(self, query, candidates):
            raise RerankError("model failed")

    evaluator = _eval_harness(db_session, tmp_path)
    document_ids = evaluator.ingest_corpus()
    evaluator._reranker = Boom()
    dataset = load_dataset(LEXICAL_DATASET)
    subset = {"questions": [item for item in dataset["questions"] if item["id"] == "L1"]}
    with pytest.raises(RerankError, match="model failed"):
        evaluator.evaluate(
            subset,
            document_ids,
            top_k=5,
            similarity_threshold=0.0,
            retrieval_mode="hybrid",
            enable_rerank=True,
        )


def test_format_reranking_comparison_includes_rank_movement():
    from evaluation.report import format_reranking_comparison

    text = format_reranking_comparison(
        [
            {
                "retrieval_mode": "hybrid+rerank",
                "hit_at_1": 1.0,
                "hit_at_3": 1.0,
                "hit_at_5": 1.0,
                "recall_at_5": 1.0,
                "span_hit_at_5": 1.0,
                "average_retrieved_count": 5.0,
                "average_retrieval_ms": 40.0,
                "average_rerank_ms": 12.0,
            }
        ],
        question_highlights=[
            {
                "id": "Q15",
                "retrieval_mode": "hybrid+rerank",
                "hit_at_1": True,
                "gold_pre_rerank_rank": 3,
                "gold_post_rerank_rank": 1,
                "top1_rerank_score": 0.91,
            }
        ],
    )
    assert "hybrid+rerank" in text
    assert "Q15" in text
    assert "RRF rank" in text
    assert "12.0" in text


def test_reciprocal_rank_cases_1_to_5():
    expected_single = [ExpectedSource("company-policy.pdf", 4)]

    # Case 1: Expected relevant source, retrieved rank 1 -> RR = 1.0
    retrieved_case_1 = [
        {"filename": "company-policy.pdf", "page_number": 4, "rank": 1},
        {"filename": "pricing-guide.pdf", "page_number": 2, "rank": 2},
    ]
    assert reciprocal_rank(expected_single, retrieved_case_1) == 1.0

    # Case 2: Expected relevant source, retrieved rank 2 -> RR = 0.5
    retrieved_case_2 = [
        {"filename": "pricing-guide.pdf", "page_number": 2, "rank": 1},
        {"filename": "company-policy.pdf", "page_number": 4, "rank": 2},
    ]
    assert reciprocal_rank(expected_single, retrieved_case_2) == 0.5

    # Case 3: Expected relevant source, retrieved rank 3 -> RR ≈ 0.333333
    retrieved_case_3 = [
        {"filename": "pricing-guide.pdf", "page_number": 1, "rank": 1},
        {"filename": "pricing-guide.pdf", "page_number": 2, "rank": 2},
        {"filename": "company-policy.pdf", "page_number": 4, "rank": 3},
    ]
    assert reciprocal_rank(expected_single, retrieved_case_3) == pytest.approx(1.0 / 3.0)

    # Case 4: Expected source not retrieved -> RR = 0.0
    retrieved_case_4 = [
        {"filename": "pricing-guide.pdf", "page_number": 1, "rank": 1},
        {"filename": "pricing-guide.pdf", "page_number": 2, "rank": 2},
    ]
    assert reciprocal_rank(expected_single, retrieved_case_4) == 0.0

    # Case 5: Multiple relevant expected sources:
    # Retrieved: irrelevant, relevant-A, relevant-B -> use first relevant result -> RR = 0.5
    expected_multiple = [
        ExpectedSource("company-policy.pdf", 4),
        ExpectedSource("employee-handbook.pdf", 2),
    ]
    retrieved_case_5 = [
        {"filename": "pricing-guide.pdf", "page_number": 1, "rank": 1},
        {"filename": "company-policy.pdf", "page_number": 4, "rank": 2},
        {"filename": "employee-handbook.pdf", "page_number": 2, "rank": 3},
    ]
    assert reciprocal_rank(expected_multiple, retrieved_case_5) == 0.5

    # Empty edge cases
    assert reciprocal_rank([], retrieved_case_1) == 0.0
    assert reciprocal_rank(expected_single, []) == 0.0


def test_mrr_integration_in_summarize_and_reports():
    q1 = QuestionResult(
        question_id="Q1",
        question="What is the refund period?",
        question_type="direct_factual",
        expect_no_context=False,
        expected_sources=[ExpectedSource("company-policy.pdf", 1)],
        retrieved=[{"filename": "company-policy.pdf", "page_number": 1, "rank": 1, "score": 0.9}],
        hit_at_1=True,
        hit_at_3=True,
        hit_at_5=True,
        recall_at_5=1.0,
        no_context_correct=None,
        top1_similarity=0.9,
        reciprocal_rank=1.0,
    )
    q2 = QuestionResult(
        question_id="Q2",
        question="Where is the company HQ?",
        question_type="direct_factual",
        expect_no_context=False,
        expected_sources=[ExpectedSource("company-policy.pdf", 5)],
        retrieved=[
            {"filename": "pricing-guide.pdf", "page_number": 1, "rank": 1, "score": 0.8},
            {"filename": "company-policy.pdf", "page_number": 5, "rank": 2, "score": 0.75},
        ],
        hit_at_1=False,
        hit_at_3=True,
        hit_at_5=True,
        recall_at_5=1.0,
        no_context_correct=None,
        top1_similarity=0.8,
        reciprocal_rank=0.5,
    )
    q3 = QuestionResult(
        question_id="Q3",
        question="Who is the CEO?",
        question_type="no_context",
        expect_no_context=True,
        expected_sources=[],
        retrieved=[],
        hit_at_1=None,
        hit_at_3=None,
        hit_at_5=None,
        recall_at_5=None,
        no_context_correct=True,
        top1_similarity=0.0,
        reciprocal_rank=None,
    )
    # Grounded questions: q1 (RR=1.0) and q2 (RR=0.5). Mean = (1.0 + 0.5) / 2 = 0.75
    metrics = summarize([q1, q2, q3], requested_top_k=5, pool_k=5)
    assert metrics.mrr == pytest.approx(0.75)
    assert metrics.mean_reciprocal_rank == pytest.approx(0.75)

    # Test report formatting includes MRR
    report = format_report(
        metrics,
        chunk_size=700,
        chunk_overlap=100,
        top_k=5,
        similarity_threshold=0.7,
        embedder="local",
        embedding_model="local-hash-ngram",
    )
    assert "MRR: 0.75" in report

    # Test dictionary / JSON export includes MRR
    payload = metrics_to_dict(
        metrics,
        chunk_size=700,
        chunk_overlap=100,
        top_k=5,
        similarity_threshold=0.7,
        embedder="local",
        embedding_model="local-hash-ngram",
        dataset_version="1.1.1",
    )
    assert payload["summary"]["mrr"] == pytest.approx(0.75)
    assert payload["summary"]["mean_reciprocal_rank"] == pytest.approx(0.75)
    assert payload["questions"][0]["reciprocal_rank"] == 1.0
    assert payload["questions"][1]["reciprocal_rank"] == 0.5
    assert payload["questions"][2]["reciprocal_rank"] is None


def test_no_context_semantics_test_a_and_test_b(db_session, tmp_path: Path):
    """Test A & Test B: verify expected no-context classification semantics."""
    evaluator = _eval_harness(db_session, tmp_path)

    # Test A: Unanswerable question (expect_no_context=True) correctly classified
    # when 0 chunks pass retrieval threshold.
    unanswerable = {
        "id": "U1",
        "question": "What is the annual revenue?",
        "type": "no_context",
        "expected_sources": [],
        "expect_no_context": True,
    }
    result_unanswerable = evaluator._score_item(
        unanswerable,
        retrieved=[],  # 0 chunks retrieved
        contents=[],
        pool_k=5,
    )
    assert result_unanswerable.expect_no_context is True
    assert result_unanswerable.no_context_correct is True
    assert result_unanswerable.hit_at_1 is None
    assert result_unanswerable.hit_at_5 is None
    assert result_unanswerable.reciprocal_rank is None

    # Test B: Grounded question (expect_no_context=False) is never classified as no-context,
    # even when retrieval completely misses (0 chunks retrieved).
    grounded_miss = {
        "id": "G1",
        "question": "What is the refund period?",
        "type": "direct_factual",
        "expected_sources": [{"document": "company-policy.pdf", "page": 1}],
        "expect_no_context": False,
    }
    result_grounded = evaluator._score_item(
        grounded_miss,
        retrieved=[],  # 0 chunks retrieved (retrieval miss)
        contents=[],
        pool_k=5,
    )
    assert result_grounded.expect_no_context is False
    assert result_grounded.no_context_correct is None  # MUST be None, not True or False
    assert result_grounded.hit_at_1 is False
    assert result_grounded.reciprocal_rank == 0.0

    # Verify aggregation contract in summarize()
    summary = summarize([result_unanswerable, result_grounded], requested_top_k=5, pool_k=5)
    assert summary.questions_evaluated == 2
    assert summary.grounded_questions == 1
    assert summary.no_context_questions == 1
    assert summary.no_context_correct == 1
    assert summary.no_context_false_retrieval == 0
    # Grounded question with RR=0.0 is the only one in MRR calculation; unanswerable does not dilute it
    assert summary.mrr == 0.0


def test_offline_evaluator_threshold_calibration_limitation_test_c(db_session, tmp_path: Path):
    """Test C: explicitly represent offline hash embedder threshold calibration limitation.

    At threshold=0.0, the offline ranking mode returns 5 candidates for all questions (including
    no-context questions), resulting in no_context_correct=0/5.
    At a calibrated threshold for hash-similarity (e.g. 0.40), all 5 no-context questions
    retrieve 0 candidates and are 5/5 correctly rejected.
    """
    evaluator = _eval_harness(db_session, tmp_path)
    document_ids = evaluator.ingest_corpus()
    dataset = load_dataset()

    # 1. At threshold 0.0 (full ranking mode):
    metrics_0 = evaluator.evaluate(
        dataset,
        document_ids,
        top_k=5,
        similarity_threshold=0.0,
    )
    no_context_items_0 = [item for item in metrics_0.question_results if item.expect_no_context]
    assert len(no_context_items_0) == 5
    assert all(item.retrieved_count == 5 for item in no_context_items_0)
    assert metrics_0.no_context_correct == 0
    assert metrics_0.no_context_false_retrieval == 5

    # 2. At calibrated threshold 0.40:
    metrics_40 = evaluator.evaluate(
        dataset,
        document_ids,
        top_k=5,
        similarity_threshold=0.40,
    )
    no_context_items_40 = [item for item in metrics_40.question_results if item.expect_no_context]
    assert len(no_context_items_40) == 5
    assert all(item.retrieved_count == 0 for item in no_context_items_40)
    assert metrics_40.no_context_correct == 5
    assert metrics_40.no_context_false_retrieval == 0


def test_deterministic_offline_regression_gate(db_session, tmp_path: Path):
    """Enforce automated regression gate for core retrieval metrics against baseline snapshot."""
    from evaluation.run import check_baseline

    evaluator = _eval_harness(db_session, tmp_path)
    document_ids = evaluator.ingest_corpus()

    # Test main rag_eval.json dataset
    dataset = load_dataset()
    metrics = evaluator.evaluate(
        dataset,
        document_ids,
        top_k=5,
        similarity_threshold=0.0,
    )
    assert metrics.hit_at_1 >= 0.8333
    assert metrics.hit_at_3 >= 0.9166
    assert metrics.hit_at_5 >= 0.9166
    assert metrics.recall_at_5 >= 0.9166
    assert metrics.mrr >= 0.875

    passed, errors = check_baseline(metrics, dataset_path=Path("rag_eval.json"))
    assert passed, f"Baseline check failed: {errors}"

    # Test lexical dataset
    lexical_data = load_dataset(LEXICAL_DATASET)
    lexical_metrics = evaluator.evaluate(
        lexical_data,
        document_ids,
        top_k=5,
        similarity_threshold=0.0,
    )
    assert lexical_metrics.hit_at_1 >= 0.80
    assert lexical_metrics.hit_at_5 >= 0.90
    assert lexical_metrics.mrr >= 0.825

    passed_lex, errors_lex = check_baseline(lexical_metrics, dataset_path=Path("rag_eval_lexical.json"))
    assert passed_lex, f"Lexical baseline check failed: {errors_lex}"

    # Verify that check_baseline detects intentional regression
    degraded = QuestionResult(
        question_id="Q1",
        question="q",
        question_type="direct_factual",
        expect_no_context=False,
        expected_sources=[],
        retrieved=[],
        hit_at_1=False,
        hit_at_3=False,
        hit_at_5=False,
        recall_at_5=0.0,
        no_context_correct=None,
        top1_similarity=0.0,
        reciprocal_rank=0.0,
    )
    degraded_metrics = summarize([degraded], requested_top_k=5, pool_k=5)
    passed_deg, errors_deg = check_baseline(degraded_metrics, dataset_path=Path("rag_eval.json"))
    assert not passed_deg
    assert any("hit_at_1" in err for err in errors_deg)
    assert any("mrr" in err for err in errors_deg)

