"""Incremental generation-evaluation progress: persist, resume, merge, status."""

from __future__ import annotations

import json
from pathlib import Path

from evaluation.generation import VALID_DIAGNOSES

STATUS_COMPLETE = "COMPLETE"
STATUS_PARTIAL = "PARTIAL"
STATUS_FAILED = "FAILED"


def is_complete_generation_record(record: dict) -> bool:
    return bool(
        record.get("id")
        and record.get("generated_answer") is not None
        and record.get("diagnosis") in VALID_DIAGNOSES
    )


def completed_question_ids(payload: dict | None) -> set[str]:
    if not payload:
        return set()
    return {
        str(record["id"])
        for record in payload.get("questions", [])
        if is_complete_generation_record(record)
    }


def load_generation_report(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def merge_question_records(dataset_ids: list[str] | tuple[str, ...], *groups: list[dict]) -> list[dict]:
    by_id: dict[str, dict] = {}
    for group in groups:
        for record in group:
            question_id = record.get("id")
            if not question_id:
                continue
            existing = by_id.get(question_id)
            if existing and is_complete_generation_record(existing):
                continue
            by_id[question_id] = record
    return [by_id[question_id] for question_id in dataset_ids if question_id in by_id]


def run_status(
    dataset_ids: list[str] | tuple[str, ...],
    records: list[dict],
    *,
    stop_reason: str | None = None,
) -> str:
    completed = completed_question_ids({"questions": records})
    if set(dataset_ids) <= completed:
        return STATUS_COMPLETE
    if completed:
        return STATUS_PARTIAL
    return STATUS_FAILED if stop_reason else STATUS_PARTIAL


def apply_run_status(
    payload: dict,
    dataset_ids: list[str] | tuple[str, ...],
    *,
    stop_reason: str | None = None,
) -> dict:
    records = payload.get("questions", [])
    status = run_status(dataset_ids, records, stop_reason=stop_reason)
    completed = completed_question_ids(payload)
    remaining = [question_id for question_id in dataset_ids if question_id not in completed]
    payload["status"] = status
    payload["completed_questions"] = len(completed)
    payload["remaining_questions"] = len(remaining)
    payload["dataset_questions"] = len(dataset_ids)
    payload["metrics_are_final"] = status == STATUS_COMPLETE
    payload["incomplete"] = status != STATUS_COMPLETE
    payload["incomplete_reason"] = None if status == STATUS_COMPLETE else stop_reason
    payload["stop_reason"] = stop_reason
    return payload


def _mean(flags: list[object]) -> float | None:
    values = [1.0 if flag else 0.0 for flag in flags if flag is not None]
    if not values:
        return None
    return sum(values) / len(values)


def summary_from_records(records: list[dict]) -> dict:
    grounded = [item for item in records if not item.get("expect_no_context")]
    no_context = [item for item in records if item.get("expect_no_context")]
    hallucinated = 0
    for item in records:
        if item.get("expect_no_context") and not item.get("generation_correct"):
            hallucinated += 1
        elif not item.get("expect_no_context") and not item.get("grounded"):
            hallucinated += 1
    injection = [item for item in records if item.get("type") == "prompt_injection"]
    prompt_injection_passed = None
    if injection:
        prompt_injection_passed = all(
            item.get("generation_correct")
            and item.get("grounded")
            and not item.get("followed_document_injection")
            for item in injection
        )
    reciprocal_ranks = [
        item.get("retrieval", {}).get("reciprocal_rank")
        for item in grounded
        if item.get("retrieval", {}).get("reciprocal_rank") is not None
    ]
    mrr = sum(reciprocal_ranks) / len(reciprocal_ranks) if reciprocal_ranks else None
    return {
        "questions_evaluated": len(records),
        "grounded_questions": len(grounded),
        "hit_at_1": _mean([item.get("retrieval", {}).get("hit_at_1") for item in grounded]),
        "hit_at_3": _mean([item.get("retrieval", {}).get("hit_at_3") for item in grounded]),
        "hit_at_5": _mean([item.get("retrieval", {}).get("hit_at_5") for item in grounded]),
        "recall_at_5": _mean([item.get("retrieval", {}).get("recall_at_5") for item in grounded]),
        "mrr": mrr,
        "mean_reciprocal_rank": mrr,
        "generation_correct": sum(1 for item in grounded if item.get("generation_correct")),
        "generation_correct_total": len(grounded),
        "generation_grounded": sum(1 for item in grounded if item.get("grounded")),
        "generation_grounded_total": len(grounded),
        "no_context_correct_refusals": sum(1 for item in no_context if item.get("generation_correct")),
        "no_context_total": len(no_context),
        "hallucinated_or_unsupported": hallucinated,
        "prompt_injection_passed": prompt_injection_passed,
    }


def error_breakdown_from_records(records: list[dict]) -> dict:
    diagnoses = [item.get("diagnosis") for item in records]
    return {
        "retrieval_failures": diagnoses.count("RETRIEVAL_FAILURE"),
        "context_failures": diagnoses.count("CONTEXT_CONSTRUCTION_FAILURE"),
        "generation_failures": diagnoses.count("GENERATION_FAILURE"),
        "correct_refusals": diagnoses.count("NO_CONTEXT_CORRECT"),
        "generation_successes": diagnoses.count("GENERATION_SUCCESS"),
        "unknown": diagnoses.count("UNKNOWN"),
    }
