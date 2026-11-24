from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.v1.conversations import get_conversation_service
from app.db.database import get_db
from app.db.models import Document, DocumentChunk, DocumentStatus
from app.main import app
from app.services.ai.errors import AINetworkError
from app.services.conversation_service import ConversationService
from app.services.embedding_service import EmbeddingService
from app.services.rag import NO_CONTEXT_ANSWER, RagService
from tests.conftest import make_settings, postgres_available


def _vector(hot_index: int = 0) -> list[float]:
    values = [0.0] * 768
    values[hot_index] = 1.0
    return values


@pytest.fixture
def chat_client(db_session, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    if not postgres_available():
        pytest.skip("PostgreSQL is not available for API tests.")

    provider = MagicMock()
    provider.create_embedding.return_value = _vector(0)
    provider.generate_text.return_value = (
        "Customers may request a refund within 30 days of purchase."
    )
    settings = make_settings(rag_top_k=5, rag_similarity_threshold=0.2, max_question_length=50)
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
        yield client, provider, db_session
    app.dependency_overrides.clear()


def _seed_completed_policy(db_session) -> Document:
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
            chunk_index=7,
            content="Customers may request a refund within 30 days of purchase.",
            page_number=3,
            embedding=_vector(0),
            chunk_metadata={
                "document_id": str(document.id),
                "filename": "company-policy.pdf",
                "page_number": 3,
                "chunk_index": 7,
            },
        )
    )
    db_session.flush()
    return document


def test_chat_valid_question_returns_answer_and_sources(chat_client):
    client, provider, db_session = chat_client
    document = _seed_completed_policy(db_session)

    response = client.post("/api/v1/chat", json={"question": "What is the refund period?"})

    assert response.status_code == 200
    body = response.json()
    assert "30 days" in body["answer"]
    assert len(body["sources"]) == 1
    source = body["sources"][0]
    assert source["document_id"] == str(document.id)
    assert source["filename"] == "company-policy.pdf"
    assert source["page_number"] == 3
    assert source["chunk_index"] == 7
    assert source["similarity_score"] >= 0.2
    assert body["conversation_id"]
    assert body["message_id"]
    assert body["user_message_id"]
    assert "embedding" not in body
    assert "file_path" not in body
    assert "file_path" not in source
    provider.generate_text.assert_called_once()


def test_chat_empty_and_whitespace_questions_are_rejected(chat_client):
    client, _provider, _db_session = chat_client
    empty = client.post("/api/v1/chat", json={"question": ""})
    whitespace = client.post("/api/v1/chat", json={"question": "   "})
    assert empty.status_code == 422
    assert whitespace.status_code == 422


def test_chat_malformed_request(chat_client):
    client, _provider, _db_session = chat_client
    response = client.post("/api/v1/chat", json={"prompt": "hello"})
    assert response.status_code == 422
    assert "detail" in response.json()


def test_chat_overly_long_question(chat_client):
    client, _provider, _db_session = chat_client
    response = client.post("/api/v1/chat", json={"question": "x" * 51})
    assert response.status_code == 422
    assert response.json()["detail"] == "The question exceeds the maximum allowed length."


def test_chat_no_relevant_context_does_not_call_gemini(chat_client):
    client, provider, _db_session = chat_client
    response = client.post("/api/v1/chat", json={"question": "What is the office address?"})
    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == NO_CONTEXT_ANSWER
    assert body["sources"] == []
    assert body["conversation_id"]
    assert body["message_id"]
    assert body["user_message_id"]
    provider.generate_text.assert_not_called()


def test_chat_query_embedding_failure_returns_safe_error(chat_client):
    client, provider, _db_session = chat_client
    provider.create_embedding.side_effect = AINetworkError("Gemini is temporarily unavailable.")

    response = client.post("/api/v1/chat", json={"question": "What is the refund period?"})

    assert response.status_code == 502
    assert response.json()["detail"] == (
        "The AI service is temporarily unavailable. Please try again later."
    )
    provider.generate_text.assert_not_called()
    assert "rank" not in response.json()
    assert "results" not in response.json()


def test_chat_provider_failure_returns_safe_error(chat_client):
    client, provider, db_session = chat_client
    _seed_completed_policy(db_session)
    provider.generate_text.side_effect = AINetworkError("Gemini is temporarily unavailable.")

    response = client.post("/api/v1/chat", json={"question": "What is the refund period?"})

    assert response.status_code == 502
    assert response.json()["detail"] == (
        "The AI service is temporarily unavailable. Please try again later."
    )
    assert "answer" not in response.json()
    assert "Traceback" not in str(response.json())
    assert "api_key" not in str(response.json()).lower()


def test_chat_unknown_conversation_id_returns_404(chat_client):
    client, _provider, _db_session = chat_client
    response = client.post(
        "/api/v1/chat",
        json={"question": "What is the refund period?", "conversation_id": str(uuid4())},
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Conversation not found."


def test_chat_invalid_conversation_id_is_rejected(chat_client):
    client, _provider, _db_session = chat_client
    response = client.post(
        "/api/v1/chat",
        json={"question": "What is the refund period?", "conversation_id": "not-a-uuid"},
    )
    assert response.status_code == 422


def test_chat_without_filters_and_empty_filters_behave_the_same(chat_client):
    client, provider, db_session = chat_client
    document = _seed_completed_policy(db_session)
    omitted = client.post("/api/v1/chat", json={"question": "What is the refund period?"})
    null_filters = client.post(
        "/api/v1/chat",
        json={"question": "What is the refund period?", "filters": None},
    )
    empty_filters = client.post(
        "/api/v1/chat",
        json={"question": "What is the refund period?", "filters": {}},
    )
    assert omitted.status_code == 200
    assert null_filters.status_code == 200
    assert empty_filters.status_code == 200
    assert omitted.json()["sources"][0]["document_id"] == str(document.id)
    assert null_filters.json()["sources"][0]["document_id"] == str(document.id)
    assert empty_filters.json()["sources"][0]["document_id"] == str(document.id)
    assert provider.generate_text.call_count == 3


def test_chat_unknown_filter_field_is_rejected(chat_client):
    client, _provider, _db_session = chat_client
    response = client.post(
        "/api/v1/chat",
        json={
            "question": "What is the refund period?",
            "filters": {"category": "policy", "unknown": "x"},
        },
    )
    assert response.status_code == 422


def test_chat_category_filter_can_yield_no_context(chat_client):
    client, provider, db_session = chat_client
    _seed_completed_policy(db_session)
    response = client.post(
        "/api/v1/chat",
        json={
            "question": "What is the refund period?",
            "filters": {"category": "finance"},
        },
    )
    assert response.status_code == 200
    assert response.json()["answer"] == NO_CONTEXT_ANSWER
    assert response.json()["sources"] == []
    provider.generate_text.assert_not_called()


def test_chat_category_filter_retrieves_matching_document(chat_client):
    client, provider, db_session = chat_client
    document = _seed_completed_policy(db_session)
    document.category = "policy"
    db_session.flush()
    response = client.post(
        "/api/v1/chat",
        json={
            "question": "What is the refund period?",
            "filters": {"category": "policy"},
        },
    )
    assert response.status_code == 200
    assert response.json()["sources"][0]["document_id"] == str(document.id)
    provider.generate_text.assert_called_once()
