from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.v1.conversations import get_conversation_service
from app.db.database import get_db
from app.db.models import Document, DocumentChunk, DocumentStatus, MessageRole
from app.main import app
from app.services.ai.errors import AINetworkError, AIQuotaExhaustedError
from app.services.ai.errors import AI_PUBLIC_ERROR_DETAIL
from app.services.conversation_service import ConversationService
from app.services.embedding_service import EmbeddingService
from app.services.rag import NO_CONTEXT_ANSWER, RagService
from app.services.rag_prompt import HISTORY_HEADER, SYSTEM_INSTRUCTIONS
from tests.conftest import make_settings, postgres_available
from tests.helpers.sse import parse_sse


def _vector(hot_index: int = 0) -> list[float]:
    values = [0.0] * 768
    values[hot_index] = 1.0
    return values


@pytest.fixture
def stream_client(db_session) -> TestClient:
    if not postgres_available():
        pytest.skip("PostgreSQL is not available for API tests.")

    provider = MagicMock()
    provider.create_embedding.return_value = _vector(0)
    provider.generate_text.return_value = "unused non-streaming answer"
    provider.stream_text.return_value = iter(["The", " refund", " period", " is 30 days."])
    settings = make_settings(
        rag_top_k=5,
        rag_similarity_threshold=0.2,
        conversation_history_limit=10,
        max_question_length=80,
    )
    rag = RagService(
        session=db_session,
        settings=settings,
        embedding_service=EmbeddingService(provider, settings),
        provider=provider,
    )
    service = ConversationService(
        session=db_session,
        settings=settings,
        rag=rag,
        autocommit=False,
    )

    def override_service() -> ConversationService:
        return service

    def override_db():
        yield db_session

    app.dependency_overrides[get_conversation_service] = override_service
    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as client:
        yield client, provider, db_session, service
    app.dependency_overrides.clear()


def _seed_refund_chunk(db_session) -> Document:
    document = Document(
        id=uuid4(),
        filename="original.pdf",
        original_filename="company-policy.pdf",
        file_path="/storage/documents/test/original.pdf",
        file_type="application/pdf",
        file_size=120,
        status=DocumentStatus.COMPLETED,
        page_count=1,
    )
    db_session.add(document)
    db_session.flush()
    db_session.add(
        DocumentChunk(
            document_id=document.id,
            chunk_index=0,
            content="Customers may request a refund within 30 days of purchase.",
            page_number=1,
            embedding=_vector(0),
            chunk_metadata={
                "document_id": str(document.id),
                "filename": "company-policy.pdf",
                "page_number": 1,
                "chunk_index": 0,
            },
        )
    )
    db_session.flush()
    return document


def _read_stream(client: TestClient, payload: dict) -> tuple[int, str, str]:
    with client.stream("POST", "/api/v1/chat/stream", json=payload) as response:
        body = "".join(response.iter_text())
        return response.status_code, response.headers.get("content-type", ""), body


def test_stream_endpoint_returns_sse_events_in_order(stream_client):
    client, provider, db_session, _service = stream_client
    document = _seed_refund_chunk(db_session)

    status, content_type, body = _read_stream(
        client,
        {"question": "What is the refund period?"},
    )

    assert status == 200
    assert content_type.startswith("text/event-stream")
    events = parse_sse(body)
    names = [name for name, _payload in events]
    assert names[0] == "start"
    assert names[1:5] == ["token", "token", "token", "token"]
    assert names[-2] == "sources"
    assert names[-1] == "done"

    tokens = "".join(payload["text"] for name, payload in events if name == "token")
    assert tokens == "The refund period is 30 days."
    sources = next(payload for name, payload in events if name == "sources")["sources"]
    assert sources[0]["filename"] == "company-policy.pdf"
    assert sources[0]["document_id"] == str(document.id)
    done = events[-1][1]
    assert done["conversation_id"]
    assert done["message_id"]
    assert done["user_message_id"]
    provider.generate_text.assert_not_called()
    provider.stream_text.assert_called_once()


def test_stream_no_context_skips_gemini_and_completes(stream_client):
    client, provider, _db_session, service = stream_client

    status, content_type, body = _read_stream(
        client,
        {"question": "What is the office address?"},
    )

    assert status == 200
    assert content_type.startswith("text/event-stream")
    events = parse_sse(body)
    names = [name for name, _payload in events]
    assert names == ["start", "token", "sources", "done"]
    assert events[1][1]["text"] == NO_CONTEXT_ANSWER
    assert events[2][1]["sources"] == []
    provider.stream_text.assert_not_called()
    provider.generate_text.assert_not_called()

    conversation_id = events[0][1]["conversation_id"]
    messages = service.list_messages(UUID(conversation_id))
    assert [item.role for item in messages] == [MessageRole.USER, MessageRole.ASSISTANT]
    assert messages[1].content == NO_CONTEXT_ANSWER
    assert messages[1].sources == []


def test_stream_persists_one_assistant_message_with_sources(stream_client):
    client, _provider, db_session, service = stream_client
    _seed_refund_chunk(db_session)

    _status, _content_type, body = _read_stream(
        client,
        {"question": "What is the refund period?"},
    )
    events = parse_sse(body)
    conversation_id = events[0][1]["conversation_id"]
    messages = service.list_messages(UUID(conversation_id))
    assert len(messages) == 2
    assert messages[0].role is MessageRole.USER
    assert messages[0].content == "What is the refund period?"
    assert messages[1].role is MessageRole.ASSISTANT
    assert messages[1].content == "The refund period is 30 days."
    assert messages[1].sources[0]["filename"] == "company-policy.pdf"


def test_stream_follow_up_retrieves_current_question_and_includes_history(stream_client):
    client, provider, db_session, _service = stream_client
    _seed_refund_chunk(db_session)
    first = client.post("/api/v1/chat", json={"question": "What is the refund period?"})
    conversation_id = first.json()["conversation_id"]
    provider.create_embedding.reset_mock()
    provider.stream_text.reset_mock()
    provider.stream_text.return_value = iter(["Yes, international purchases are covered."])

    follow_up = "Does that also apply to international purchases?"
    _status, _content_type, body = _read_stream(
        client,
        {"question": follow_up, "conversation_id": conversation_id},
    )
    events = parse_sse(body)
    assert [name for name, _payload in events][-1] == "done"
    assert provider.create_embedding.call_args.args[0] == follow_up
    prompt = provider.stream_text.call_args.args[0]
    assert HISTORY_HEADER in prompt
    assert "What is the refund period?" in prompt
    assert follow_up in prompt
    assert SYSTEM_INSTRUCTIONS in prompt
    provider.generate_text.assert_called_once()


def test_stream_failed_generation_does_not_persist_assistant(stream_client):
    client, provider, db_session, service = stream_client
    _seed_refund_chunk(db_session)
    provider.stream_text.side_effect = AINetworkError("Gemini is temporarily unavailable.")

    status, _content_type, body = _read_stream(
        client,
        {"question": "What is the refund period?"},
    )
    assert status == 200
    events = parse_sse(body)
    names = [name for name, _payload in events]
    assert names[0] == "start"
    assert names[-1] == "error"
    assert events[-1][1]["detail"] == AI_PUBLIC_ERROR_DETAIL
    conversation_id = events[0][1]["conversation_id"]
    messages = service.list_messages(UUID(conversation_id))
    assert len(messages) == 1
    assert messages[0].role is MessageRole.USER
    assert messages[0].content == "What is the refund period?"


def test_stream_quota_error_sends_error_event(stream_client):
    client, provider, db_session, _service = stream_client
    _seed_refund_chunk(db_session)
    provider.stream_text.side_effect = AIQuotaExhaustedError("Gemini daily quota exhausted.")

    _status, _content_type, body = _read_stream(
        client,
        {"question": "What is the refund period?"},
    )
    events = parse_sse(body)
    assert events[-1][0] == "error"
    assert events[-1][1]["detail"] == AI_PUBLIC_ERROR_DETAIL
    assert "quota" not in body.lower()
    assert "api_key" not in body.lower()


def test_stream_unknown_conversation_returns_json_404(stream_client):
    client, _provider, _db_session, _service = stream_client
    response = client.post(
        "/api/v1/chat/stream",
        json={"question": "What is the refund period?", "conversation_id": str(uuid4())},
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Conversation not found."


def test_stream_empty_question_returns_422(stream_client):
    client, _provider, _db_session, _service = stream_client
    response = client.post("/api/v1/chat/stream", json={"question": "   "})
    assert response.status_code == 422


def test_non_streaming_chat_still_works_alongside_stream(stream_client):
    client, provider, db_session, _service = stream_client
    _seed_refund_chunk(db_session)
    provider.generate_text.return_value = "Customers may request a refund within 30 days of purchase."

    response = client.post("/api/v1/chat", json={"question": "What is the refund period?"})
    assert response.status_code == 200
    assert "30 days" in response.json()["answer"]
    provider.stream_text.assert_not_called()


def test_prepare_turn_commits_user_message_before_streaming(db_session):
    settings = make_settings()
    rag = MagicMock()
    rag.validate_question.side_effect = lambda question: question.strip()
    rag.retrieve_chunks.return_value = []
    service = ConversationService(
        session=db_session,
        settings=settings,
        rag=rag,
        autocommit=False,
    )
    commit_calls = 0
    original_commit = service._commit

    def counting_commit() -> None:
        nonlocal commit_calls
        commit_calls += 1
        original_commit()

    service._commit = counting_commit  # type: ignore[method-assign]

    service.prepare_turn("What is the refund period?")

    assert commit_calls == 1


def test_stream_get_conversation_returns_user_and_assistant(stream_client):
    client, _provider, db_session, _service = stream_client
    _seed_refund_chunk(db_session)

    _status, _content_type, body = _read_stream(
        client,
        {"question": "What is the refund period?"},
    )
    conversation_id = parse_sse(body)[0][1]["conversation_id"]
    detail = client.get(f"/api/v1/conversations/{conversation_id}")
    assert detail.status_code == 200
    messages = detail.json()["messages"]
    assert len(messages) == 2
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "What is the refund period?"
    assert messages[1]["role"] == "assistant"
    assert "30 days" in messages[1]["content"]


def test_stream_survives_prepare_turn_commit(db_session):
    """Regression: production autocommit must not break SSE after prepare_turn()."""
    if not postgres_available():
        pytest.skip("PostgreSQL is not available for API tests.")

    provider = MagicMock()
    provider.create_embedding.return_value = _vector(0)
    provider.stream_text.return_value = iter(["The", " refund", " period", " is 30 days."])
    settings = make_settings(
        rag_top_k=5,
        rag_similarity_threshold=0.2,
        conversation_history_limit=10,
        max_question_length=80,
    )
    rag = RagService(
        session=db_session,
        settings=settings,
        embedding_service=EmbeddingService(provider, settings),
        provider=provider,
    )
    _seed_refund_chunk(db_session)
    service = ConversationService(
        session=db_session,
        settings=settings,
        rag=rag,
        autocommit=True,
    )

    prepared = service.prepare_turn("What is the refund period?")
    events = list(service.iter_chat_events(prepared))
    parsed = parse_sse("".join(events))

    assert parsed[0][0] == "start"
    assert parsed[-1][0] == "done"
    messages = service.list_messages(prepared.conversation_id)
    assert [item.role for item in messages] == [MessageRole.USER, MessageRole.ASSISTANT]


def test_stream_accepts_filters_and_can_skip_generation(stream_client):
    client, provider, db_session, _service = stream_client
    _seed_refund_chunk(db_session)
    status, content_type, body = _read_stream(
        client,
        {
            "question": "What is the refund period?",
            "filters": {"category": "finance"},
        },
    )
    assert status == 200
    assert content_type.startswith("text/event-stream")
    events = parse_sse(body)
    names = [name for name, _payload in events]
    assert names == ["start", "token", "sources", "done"]
    tokens = "".join(payload["text"] for name, payload in events if name == "token")
    assert tokens == NO_CONTEXT_ANSWER
    provider.stream_text.assert_not_called()

