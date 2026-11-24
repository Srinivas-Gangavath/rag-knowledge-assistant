"""Optional LLM-as-a-judge for generation evaluation.

This is evaluation-only. It is never used by pytest or production chat.
The judge does not replace deterministic scores.

The production answer LLM never sees expected_answer or gold sources.
The judge may see expected_answer after the fact, only to score correctness.
Groundedness must be judged from retrieved context, not from gold labels.
"""

from __future__ import annotations

import json
import re

from app.services.ai.provider import AIProvider

JUDGE_MODEL_SOURCE = "production AIProvider.generate_text"

JUDGE_INSTRUCTIONS = """You are scoring a retrieval-augmented assistant.

Use only the retrieved context and the expected answer supplied below.
Do not use outside knowledge.

Return JSON only with this shape:
{"correct": true, "grounded": true, "notes": "short reason"}

Correctness: the generated answer conveys the same facts as the expected answer.
Paraphrase is allowed (thirty days == 30 days). Extra facts that change the meaning
make it incorrect. A refusal is correct only when expected_answer is empty/null.

Groundedness: every factual claim in the generated answer must be supported by
the retrieved context. An answer is not grounded just because it matches the
expected answer. If retrieved context is empty, only a refusal is grounded.
"""


def build_judge_prompt(
    *,
    question: str,
    context: str,
    generated_answer: str,
    expected_answer: str | None,
    expect_no_context: bool,
) -> str:
    expected = expected_answer if expected_answer else "(no answer exists in the corpus; refusal expected)"
    context_block = context if context.strip() else "(no retrieved context)"
    return "\n\n".join(
        [
            JUDGE_INSTRUCTIONS,
            "User question:",
            question,
            "Retrieved context (this is what the production model saw):",
            context_block,
            "Expected answer (evaluation only; the production model did not see this):",
            expected,
            f"expect_no_context: {expect_no_context}",
            "Generated answer:",
            generated_answer,
        ]
    )


def parse_judge_response(text: str) -> tuple[bool | None, bool | None, str | None]:
    if not text or not text.strip():
        return None, None, None
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        return None, None, text.strip()
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None, None, text.strip()
    correct = payload.get("correct")
    grounded = payload.get("grounded")
    notes = payload.get("notes")
    return (
        correct if isinstance(correct, bool) else None,
        grounded if isinstance(grounded, bool) else None,
        notes if isinstance(notes, str) else None,
    )


def judge_generation(
    provider: AIProvider,
    *,
    question: str,
    context: str,
    generated_answer: str,
    expected_answer: str | None,
    expect_no_context: bool,
) -> tuple[bool | None, bool | None, str | None]:
    prompt = build_judge_prompt(
        question=question,
        context=context,
        generated_answer=generated_answer,
        expected_answer=expected_answer,
        expect_no_context=expect_no_context,
    )
    raw = provider.generate_text(prompt)
    return parse_judge_response(raw)
