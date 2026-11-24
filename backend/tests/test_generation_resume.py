import json
from unittest.mock import MagicMock
from uuid import uuid4

from app.services.ai.errors import AIQuotaExhaustedError
from app.services.embedding_service import EmbeddingService
from app.services.retrieval import RetrievedChunk
from evaluation.evaluator import load_dataset
from evaluation.generation import DIAGNOSIS_GENERATION_SUCCESS, DIAGNOSIS_NO_CONTEXT_CORRECT
from evaluation.generation_evaluator import GenerationEvaluator
from evaluation.local_embedder import LocalHashEmbeddingProvider
from evaluation.progress import (
    STATUS_COMPLETE,
    STATUS_FAILED,
    STATUS_PARTIAL,
    apply_run_status,
    completed_question_ids,
    is_complete_generation_record,
    merge_question_records,
    run_status,
)
from evaluation.report import payload_from_records
from evaluation.run import parse_args
from evaluation.selection import select_questions
from tests.conftest import make_settings


def _record(question_id: str, **overrides) -> dict:
    values = {
        "id": question_id,
        "question": f"question {question_id}",
        "type": "direct_factual",
        "expect_no_context": False,
        "expected_answer": "30 days",
        "generated_answer": "The refund period is 30 days.",
        "generation_correct": True,
        "grounded": True,
        "diagnosis": DIAGNOSIS_GENERATION_SUCCESS,
        "llm_called": True,
        "retrieval": {"hit_at_1": True, "hit_at_3": True, "hit_at_5": True, "recall_at_5": 1.0, "retrieved": [], "retrieved_count": 1},
    }
    values.update(overrides)
    return values


def test_question_selection_is_deterministic():
    dataset = load_dataset()
    first = select_questions(dataset["questions"], start=0, limit=10)
    second = select_questions(dataset["questions"], start=0, limit=10)
    assert first.selected_ids == second.selected_ids
    assert first.selected_ids == tuple(f"Q{index}" for index in range(1, 11))
    assert first.dataset_ids[0] == "Q1"
    assert first.dataset_ids[-1] == "Q29"


def test_resume_skips_completed_question_ids():
    dataset = load_dataset()
    selection = select_questions(
        dataset["questions"],
        start=0,
        limit=10,
        completed_ids={"Q1", "Q2", "Q3"},
    )
    assert "Q1" not in selection.selected_ids
    assert selection.selected_ids[0] == "Q4"
    assert selection.skipped_ids == ("Q1", "Q2", "Q3")
    assert len(selection.selected_ids) == 10


def test_question_ids_are_stable_dataset_identifiers():
    dataset = load_dataset()
    ids = [item["id"] for item in dataset["questions"]]
    assert ids == [f"Q{index}" for index in range(1, 30)]
    assert len(set(ids)) == 29


def test_merge_prevents_duplicate_question_ids():
    dataset_ids = ["Q1", "Q2"]
    first = [_record("Q1", generated_answer="first")]
    second = [_record("Q1", generated_answer="second"), _record("Q2")]
    merged = merge_question_records(dataset_ids, first, second)
    assert [item["id"] for item in merged] == ["Q1", "Q2"]
    assert merged[0]["generated_answer"] == "first"


def test_partial_and_complete_report_status():
    dataset_ids = ["Q1", "Q2"]
    partial_records = [_record("Q1")]
    assert run_status(dataset_ids, partial_records) == STATUS_PARTIAL
    complete_records = [_record("Q1"), _record("Q2")]
    assert run_status(dataset_ids, complete_records) == STATUS_COMPLETE
    assert run_status(dataset_ids, [], stop_reason="quota") == STATUS_FAILED
    payload = apply_run_status({"questions": partial_records}, dataset_ids)
    assert payload["status"] == STATUS_PARTIAL
    assert payload["metrics_are_final"] is False
    assert payload["completed_questions"] == 1
    assert payload["remaining_questions"] == 1


def test_final_metrics_are_not_marked_complete_for_partial_dataset():
    payload = payload_from_records(
        [_record("Q1")],
        chunk_size=700,
        chunk_overlap=100,
        top_k=5,
        similarity_threshold=0.7,
        embedder="gemini",
        embedding_model="gemini-embedding-2",
        embedding_dimension=768,
        llm_provider="Gemini",
        llm_model="gemini-3.7-flash",
        dataset_version="1.1.2",
        dataset_ids=["Q1", "Q2"],
        candidate_pool_k=5,
        stop_reason="Gemini daily generation quota exhausted.",
    )
    assert payload["status"] == STATUS_PARTIAL
    assert payload["metrics_are_final"] is False
    assert payload["incomplete"] is True
    assert is_complete_generation_record(payload["questions"][0]) is True


def test_complete_status_requires_every_dataset_id():
    records = [_record("Q1"), _record("Q2", expect_no_context=True, diagnosis=DIAGNOSIS_NO_CONTEXT_CORRECT, llm_called=False)]
    payload = apply_run_status({"questions": records}, ["Q1", "Q2"])
    assert payload["status"] == STATUS_COMPLETE
    assert payload["metrics_are_final"] is True
    assert payload["remaining_questions"] == 0


def test_cli_generation_subset_and_resume_args():
    args = parse_args(["--generation", "--start", "0", "--limit", "10", "--resume", "eval.json"])
    assert args.generation is True
    assert args.start == 0
    assert args.limit == 10
    assert args.resume.name == "eval.json"


def test_completed_ids_are_read_from_report():
    payload = {"questions": [_record("Q1"), {"id": "Q2", "generated_answer": None}]}
    assert completed_question_ids(payload) == {"Q1"}


def _chunk() -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=uuid4(),
        document_id=uuid4(),
        content="Customers may request a refund within 30 days of purchase.",
        page_number=1,
        chunk_index=0,
        filename="company-policy.pdf",
        similarity_score=0.91,
        metadata={},
    )


def test_quota_exhaustion_stops_without_retry_and_persists(db_session, tmp_path, monkeypatch):
    provider = MagicMock()
    settings = make_settings(storage_path=str(tmp_path))
    embeddings = EmbeddingService(LocalHashEmbeddingProvider(768), settings)
    evaluator = GenerationEvaluator(
        db_session,
        embeddings,
        settings,
        str(tmp_path),
        provider=provider,
    )
    sleeps: list[float] = []
    monkeypatch.setattr("evaluation.generation_evaluator.time.sleep", sleeps.append)
    evaluator.rag.retrieve_chunks = MagicMock(return_value=[_chunk()])
    evaluator.rag.generate_answer = MagicMock(
        side_effect=[
            "Customers can request a refund within thirty days.",
            AIQuotaExhaustedError("Gemini daily quota exhausted."),
        ]
    )
    persisted = []
    dataset = load_dataset()
    questions = [item for item in dataset["questions"] if item["id"] in {"Q1", "Q2"}]
    metrics = evaluator.evaluate(
        {"questions": questions},
        {"company-policy.pdf": uuid4()},
        top_k=5,
        similarity_threshold=0.7,
        on_result=persisted.append,
    )
    assert evaluator.rag.generate_answer.call_count == 2
    assert sleeps == []
    assert len(persisted) == 1
    assert persisted[0].question_id == "Q1"
    assert metrics.incomplete is True
    assert "daily" in (metrics.incomplete_reason or "").lower()
    assert metrics.question_results[0].score.prompt_contains_expected_answer is False


def test_resume_does_not_call_llm_for_completed_questions(db_session, tmp_path):
    provider = MagicMock()
    provider.generate_text.return_value = "PIN-DOCS-4411"
    settings = make_settings(storage_path=str(tmp_path))
    embeddings = EmbeddingService(LocalHashEmbeddingProvider(768), settings)
    evaluator = GenerationEvaluator(
        db_session,
        embeddings,
        settings,
        str(tmp_path),
        provider=provider,
    )
    evaluator.rag.retrieve_chunks = MagicMock(return_value=[_chunk()])
    dataset = load_dataset()
    selection = select_questions(
        dataset["questions"],
        completed_ids={"Q1", "Q2"},
        start=0,
        limit=1,
    )
    assert selection.selected_ids == ("Q3",)
    metrics = evaluator.evaluate(
        {"questions": list(selection.selected)},
        {"company-policy.pdf": uuid4()},
        top_k=5,
        similarity_threshold=0.7,
    )
    assert metrics.question_results[0].question_id == "Q3"
    provider.generate_text.assert_called_once()
    prompt = provider.generate_text.call_args.args[0]
    q3 = selection.selected[0]
    assert q3["expected_answer"] not in prompt or q3["expected_answer"] in metrics.question_results[0].context


def test_incremental_persist_writes_before_quota_failure(tmp_path):
    dataset_ids = ["Q1", "Q2"]
    path = tmp_path / "generation.json"
    first = payload_from_records(
        [_record("Q1")],
        chunk_size=700,
        chunk_overlap=100,
        top_k=5,
        similarity_threshold=0.7,
        embedder="gemini",
        embedding_model="gemini-embedding-2",
        embedding_dimension=768,
        llm_provider="Gemini",
        llm_model="gemini-3.7-flash",
        dataset_version="1.1.2",
        dataset_ids=dataset_ids,
        candidate_pool_k=5,
        stop_reason="Gemini daily generation quota exhausted.",
    )
    path.write_text(json.dumps(first), encoding="utf-8")
    loaded = json.loads(path.read_text(encoding="utf-8"))
    assert loaded["status"] == STATUS_PARTIAL
    assert completed_question_ids(loaded) == {"Q1"}
    resumed = select_questions(
        [{"id": "Q1"}, {"id": "Q2", "expect_no_context": False}],
        completed_ids=completed_question_ids(loaded),
    )
    assert resumed.selected_ids == ("Q2",)
    merged = merge_question_records(dataset_ids, loaded["questions"], [_record("Q2")])
    complete = apply_run_status({"questions": merged}, dataset_ids)
    assert complete["status"] == STATUS_COMPLETE
    assert [item["id"] for item in complete["questions"]] == ["Q1", "Q2"]
