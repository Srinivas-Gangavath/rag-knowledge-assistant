"""Conversation persistence and how history interacts with the existing RAG path."""

from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.v1.conversations import get_conversation_service
from app.db.database import get_db
from app.db.models import Document, DocumentChunk, DocumentStatus, Message, MessageRole
from app.main import app
from app.repositories.conversation_repository import MessageRepository
from app.services.conversation_service import ConversationService
from app.services.embedding_service import EmbeddingService
from app.services.rag import NO_CONTEXT_ANSWER, RagAnswer, RagService
from app.services.rag_prompt import HISTORY_HEADER, SYSTEM_INSTRUCTIONS
from tests.conftest import make_settings, postgres_available


def _vector(hot_index: int = 0) -> list[float]:
    values = [0.0] * 768
    values[hot_index] = 1.0
    return values


@pytest.fixture
def conversation_client(db_session) -> TestClient:
    if not postgres_available():
        pytest.skip("PostgreSQL is not available for API tests.")

    provider = MagicMock()
    provider.create_embedding.return_value = _vector(0)
    provider.generate_text.return_value = (
        "Customers may request a refund within 30 days of purchase."
    )
    settings = make_settings(
        rag_top_k=5,
        rag_similarity_threshold=0.2,
        conversation_history_limit=10,
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
            content="Customers may request a refund within 30 days of purchase. "
            "International purchases may also be refunded within 30 days of delivery.",
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


def test_create_and_list_conversations(conversation_client):
    client, _provider, _db_session, _service = conversation_client
    created = client.post("/api/v1/conversations")
    assert created.status_code == 201
    body = created.json()
    assert body["title"] is None
    assert body["messages"] == []
    assert body["id"]

    listed = client.get("/api/v1/conversations")
    assert listed.status_code == 200
    conversations = listed.json()["conversations"]
    assert any(item["id"] == body["id"] for item in conversations)


def test_conversations_are_listed_by_updated_at_desc(conversation_client):
    client, _provider, _db_session, service = conversation_client
    first = service.create_conversation()
    second = service.create_conversation()
    first.title = "older"
    service._touch(first)

    listed = client.get("/api/v1/conversations").json()["conversations"]
    listed_ids = [item["id"] for item in listed]
    assert listed_ids.index(str(first.id)) < listed_ids.index(str(second.id))


def test_get_conversation_history(conversation_client):
    client, _provider, db_session, _service = conversation_client
    _seed_refund_chunk(db_session)
    chat = client.post("/api/v1/chat", json={"question": "What is the refund period?"})
    conversation_id = chat.json()["conversation_id"]

    detail = client.get(f"/api/v1/conversations/{conversation_id}")
    assert detail.status_code == 200
    messages = detail.json()["messages"]
    assert len(messages) == 2
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "What is the refund period?"
    assert messages[1]["role"] == "assistant"
    assert "30 days" in messages[1]["content"]
    assert messages[1]["sources"][0]["filename"] == "company-policy.pdf"


def test_send_message_to_existing_conversation_persists_both_turns(conversation_client):
    client, provider, db_session, _service = conversation_client
    _seed_refund_chunk(db_session)
    first = client.post("/api/v1/chat", json={"question": "What is the refund period?"})
    conversation_id = first.json()["conversation_id"]
    provider.generate_text.return_value = "Yes, international purchases also have a 30-day refund."

    second = client.post(
        "/api/v1/chat",
        json={
            "question": "Does that also apply to international purchases?",
            "conversation_id": conversation_id,
        },
    )
    assert second.status_code == 200
    assert second.json()["conversation_id"] == conversation_id

    messages = client.get(f"/api/v1/conversations/{conversation_id}").json()["messages"]
    assert len(messages) == 4
    assert messages[2]["content"] == "Does that also apply to international purchases?"
    assert messages[3]["role"] == "assistant"


def test_follow_up_retrieves_with_current_question_and_puts_history_in_prompt(
    conversation_client,
):
    client, provider, db_session, _service = conversation_client
    _seed_refund_chunk(db_session)
    first = client.post("/api/v1/chat", json={"question": "What is the refund period?"})
    conversation_id = first.json()["conversation_id"]
    provider.create_embedding.reset_mock()
    provider.generate_text.reset_mock()
    provider.generate_text.return_value = "International purchases are also covered."

    follow_up = "Does that also apply to international purchases?"
    response = client.post(
        "/api/v1/chat",
        json={"question": follow_up, "conversation_id": conversation_id},
    )
    assert response.status_code == 200

    embedded_query = provider.create_embedding.call_args.args[0]
    assert embedded_query == follow_up
    prompt = provider.generate_text.call_args.args[0]
    assert HISTORY_HEADER in prompt
    assert "What is the refund period?" in prompt
    assert follow_up in prompt
    assert SYSTEM_INSTRUCTIONS in prompt
    assert prompt.index(SYSTEM_INSTRUCTIONS) < prompt.index(HISTORY_HEADER)


def test_no_context_persists_and_does_not_use_history_to_answer(conversation_client):
    client, provider, _db_session, _service = conversation_client
    created = client.post("/api/v1/conversations").json()
    conversation_id = created["id"]
    response = client.post(
        "/api/v1/chat",
        json={
            "question": "What is the office address?",
            "conversation_id": conversation_id,
        },
    )
    assert response.status_code == 200
    assert response.json()["answer"] == NO_CONTEXT_ANSWER
    provider.generate_text.assert_not_called()

    messages = client.get(f"/api/v1/conversations/{conversation_id}").json()["messages"]
    assert len(messages) == 2
    assert messages[0]["role"] == "user"
    assert messages[1]["content"] == NO_CONTEXT_ANSWER
    assert messages[1]["sources"] == []


def test_delete_conversation_cascades_messages(conversation_client):
    client, _provider, db_session, _service = conversation_client
    _seed_refund_chunk(db_session)
    chat = client.post("/api/v1/chat", json={"question": "What is the refund period?"})
    conversation_id = chat.json()["conversation_id"]

    deleted = client.delete(f"/api/v1/conversations/{conversation_id}")
    assert deleted.status_code == 204
    missing = client.get(f"/api/v1/conversations/{conversation_id}")
    assert missing.status_code == 404
    listed = client.get("/api/v1/conversations").json()["conversations"]
    assert all(item["id"] != conversation_id for item in listed)
    assert MessageRepository(db_session).list_by_conversation(UUID(conversation_id)) == []


def test_get_unknown_conversation_returns_404(conversation_client):
    client, _provider, _db_session, _service = conversation_client
    response = client.get(f"/api/v1/conversations/{uuid4()}")
    assert response.status_code == 404


def test_delete_unknown_conversation_returns_404(conversation_client):
    client, _provider, _db_session, _service = conversation_client
    response = client.delete(f"/api/v1/conversations/{uuid4()}")
    assert response.status_code == 404


def test_history_limit_is_respected_in_prompt_construction(db_session):
    settings = make_settings(conversation_history_limit=2)
    rag = MagicMock()
    rag.validate_question.side_effect = lambda question: question.strip()
    rag.answer.return_value = RagAnswer(answer="Limited history answer.", sources=[])
    service = ConversationService(
        session=db_session,
        settings=settings,
        rag=rag,
        autocommit=False,
    )
    conversation = service.create_conversation()
    contents = ["turn-0", "turn-1", "turn-2", "turn-3"]
    for index, content in enumerate(contents):
        service._messages.add(
            Message(
                conversation_id=conversation.id,
                role=MessageRole.USER if index % 2 == 0 else MessageRole.ASSISTANT,
                content=content,
            )
        )

    service.ask("current question", conversation_id=conversation.id)

    history = rag.answer.call_args.kwargs["history"]
    assert [turn.content for turn in history] == ["turn-2", "turn-3"]
    assert rag.answer.call_args.args[0] == "current question"


def test_zero_history_limit_omits_conversation_from_prompt(db_session):
    settings = make_settings(conversation_history_limit=0)
    rag = MagicMock()
    rag.validate_question.side_effect = lambda question: question.strip()
    rag.answer.return_value = RagAnswer(answer="No history.", sources=[])
    service = ConversationService(
        session=db_session,
        settings=settings,
        rag=rag,
        autocommit=False,
    )
    conversation = service.create_conversation()
    service._messages.add(
        Message(
            conversation_id=conversation.id,
            role=MessageRole.USER,
            content="older question",
        )
    )

    service.ask("current question", conversation_id=conversation.id)

    assert rag.answer.call_args.kwargs["history"] == []
    stored = service.list_messages(conversation.id)
    assert stored[0].content == "older question"
    assert stored[-2].content == "current question"
    assert stored[-1].content == "No history."
