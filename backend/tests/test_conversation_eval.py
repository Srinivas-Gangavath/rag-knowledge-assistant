"""Deterministic conversation-history evaluation. Does not call Gemini."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.services.context_builder import ContextBuilder
from app.services.embedding_service import EmbeddingService
from app.services.rag import NO_CONTEXT_ANSWER, RagService
from app.services.rag_prompt import HISTORY_HEADER, PromptTurn, SYSTEM_INSTRUCTIONS
from app.services.retrieval import RetrievedChunk
from tests.conftest import make_settings
from uuid import uuid4
from json import loads

DATASET_PATH = (
    Path(__file__).resolve().parents[1] / "evaluation" / "datasets" / "conversation_eval.json"
)


def _dataset() -> dict:
    return loads(DATASET_PATH.read_text(encoding="utf-8"))


def _chunk(content: str) -> RetrievedChunk:
    document_id = uuid4()
    return RetrievedChunk(
        chunk_id=uuid4(),
        document_id=document_id,
        content=content,
        page_number=1,
        chunk_index=0,
        filename="company-policy.pdf",
        similarity_score=0.91,
        metadata={"filename": "company-policy.pdf", "page_number": 1, "chunk_index": 0},
    )


def _history(case: dict) -> list[PromptTurn]:
    return [PromptTurn(role=item["role"], content=item["content"]) for item in case["history"]]


def _service(provider: MagicMock, retrieval: MagicMock) -> RagService:
    settings = make_settings()
    return RagService(
        session=MagicMock(),
        settings=settings,
        embedding_service=EmbeddingService(provider, settings),
        retrieval=retrieval,
        provider=provider,
    )


@pytest.mark.parametrize("case", _dataset()["cases"], ids=lambda case: case["id"])
def test_conversation_eval_case(case: dict):
    provider = MagicMock()
    provider.create_embedding.return_value = [0.2] * 768
    provider.generate_text.return_value = "Grounded answer from retrieved documents."
    retrieval = MagicMock()
    document_context = case["document_context"].strip()
    retrieval.retrieve.return_value = [_chunk(document_context)] if document_context else []
    service = _service(provider, retrieval)

    result = service.answer(case["question"], history=_history(case))

    if case.get("retrieval_must_use_question"):
        assert provider.create_embedding.call_args.args[0] == case["question"]

    if case["expect_no_context"]:
        assert result.answer == NO_CONTEXT_ANSWER
        assert result.sources == []
        provider.generate_text.assert_not_called()
        return

    provider.generate_text.assert_called_once()
    prompt = provider.generate_text.call_args.args[0]
    assert SYSTEM_INSTRUCTIONS in prompt
    assert HISTORY_HEADER in prompt
    assert prompt.index(SYSTEM_INSTRUCTIONS) < prompt.index(HISTORY_HEADER)
    if case.get("history_is_untrusted") or case.get("documents_must_override_history"):
        assert "untrusted conversational data" in prompt.lower()
        assert "retrieved documents win" in prompt
    for snippet in case.get("prompt_must_contain", []):
        assert snippet in prompt
    if document_context:
        assert document_context in prompt
        assert prompt.index(HISTORY_HEADER) < prompt.index(document_context)


def test_conversation_eval_dataset_covers_required_scenarios():
    ids = {case["id"] for case in _dataset()["cases"]}
    assert ids >= {"C1", "C2", "C3", "C4", "C5", "C6", "C7"}
    assert _dataset()["version"] == "1.3.0"


def test_empty_history_keeps_single_turn_prompt_shape():
    context = ContextBuilder().build([_chunk("Refunds are allowed within 30 days.")])
    from app.services.rag_prompt import RagPromptBuilder

    prompt = RagPromptBuilder().build("What is the refund period?", context)
    assert HISTORY_HEADER not in prompt
    assert "User question:" in prompt
    assert "Refunds are allowed within 30 days." in prompt
