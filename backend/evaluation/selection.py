"""Deterministic generation-evaluation question selection."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class QuestionSelection:
    dataset_ids: tuple[str, ...]
    skipped_ids: tuple[str, ...]
    selected: tuple[dict, ...]
    start: int
    limit: int | None

    @property
    def selected_ids(self) -> tuple[str, ...]:
        return tuple(item["id"] for item in self.selected)

    @property
    def generation_required(self) -> int:
        return sum(1 for item in self.selected if not item.get("expect_no_context"))

    @property
    def no_context_count(self) -> int:
        return sum(1 for item in self.selected if item.get("expect_no_context"))


def select_questions(
    questions: list[dict],
    *,
    start: int = 0,
    limit: int | None = None,
    completed_ids: set[str] | frozenset[str] = frozenset(),
) -> QuestionSelection:
    if start < 0:
        raise ValueError("start must be 0 or greater.")
    if limit is not None and limit <= 0:
        raise ValueError("limit must be greater than 0.")
    dataset_ids = tuple(item["id"] for item in questions)
    ordered = questions[start:]
    skipped = tuple(item["id"] for item in ordered if item["id"] in completed_ids)
    remaining = [item for item in ordered if item["id"] not in completed_ids]
    selected = remaining[:limit] if limit is not None else remaining
    return QuestionSelection(
        dataset_ids=dataset_ids,
        skipped_ids=skipped,
        selected=tuple(selected),
        start=start,
        limit=limit,
    )


def format_selection(selection: QuestionSelection, *, dataset_total: int) -> str:
    selected_ids = selection.selected_ids
    if selected_ids:
        selected_text = ", ".join(selected_ids)
    else:
        selected_text = "none"
    skipped_text = ", ".join(selection.skipped_ids) if selection.skipped_ids else "none"
    return "\n".join(
        [
            f"Dataset questions: {dataset_total}",
            f"Already completed: {len(selection.skipped_ids)}",
            f"Selected this run: {len(selected_ids)} ({selected_text})",
            f"Skipped (already completed): {skipped_text}",
            f"Generation-required questions: {selection.generation_required}",
            f"No-context questions skipped from LLM generation: {selection.no_context_count}",
        ]
    )
