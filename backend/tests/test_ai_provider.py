from unittest.mock import MagicMock

import httpx
import pytest
from google.genai.errors import ClientError, ServerError

from app.core.config import get_settings
from app.db.models import DocumentChunk
from app.services.ai.errors import (
    AIAuthenticationError,
    AIConfigurationError,
    AIEmptyResponseError,
    AIModelUnavailableError,
    AINetworkError,
    AIProviderError,
    AIQuotaExhaustedError,
    AIRateLimitError,
    AIResponseError,
    EmbeddingDimensionError,
)
from app.services.ai.gemini_provider import GeminiProvider
from app.services.ai.provider import EmbeddingTask
from tests.conftest import make_settings


def _provider(client: MagicMock, **setting_overrides) -> GeminiProvider:
    return GeminiProvider(settings=make_settings(**setting_overrides), client=client)


def test_generate_text_success():
    client = MagicMock()
    client.models.generate_content.return_value = MagicMock(text="Gemini connection successful.")
    provider = _provider(client)

    result = provider.generate_text("Reply with exactly: Gemini connection successful.")

    assert result == "Gemini connection successful."
    client.models.generate_content.assert_called_once()
    kwargs = client.models.generate_content.call_args.kwargs
    assert kwargs["model"] == "gemini-3.7-flash"
    assert "contents" in kwargs
    client.models.generate_content_stream.assert_not_called()


def test_stream_text_success():
    client = MagicMock()
    client.models.generate_content_stream.return_value = iter(
        [
            MagicMock(text="The"),
            MagicMock(text=None),
            MagicMock(text=" refund"),
            MagicMock(text=""),
            MagicMock(text=" period"),
        ]
    )
    provider = _provider(client)

    chunks = list(provider.stream_text("What is the refund period?"))

    assert chunks == ["The", " refund", " period"]
    kwargs = client.models.generate_content_stream.call_args.kwargs
    assert kwargs["model"] == "gemini-3.7-flash"
    assert "contents" in kwargs
    client.models.generate_content.assert_not_called()


def test_stream_text_empty_raises():
    client = MagicMock()
    client.models.generate_content_stream.return_value = iter([MagicMock(text=""), MagicMock(text=None)])
    provider = _provider(client)

    with pytest.raises(AIEmptyResponseError):
        list(provider.stream_text("Hello"))


def test_stream_text_quota_error_is_mapped():
    client = MagicMock()
    client.models.generate_content_stream.side_effect = ClientError(
        429,
        {
            "error": {
                "message": (
                    "Quota exceeded for metric: generate_content_free_tier_requests, "
                    "quotaId: GenerateRequestsPerDayPerProjectPerModel-FreeTier"
                ),
                "status": "RESOURCE_EXHAUSTED",
            }
        },
    )
    provider = _provider(client)

    with pytest.raises(AIQuotaExhaustedError):
        list(provider.stream_text("Hello"))


def test_create_embedding_success():
    vector = [0.1] * 768
    embedding = MagicMock(values=vector)
    client = MagicMock()
    client.models.embed_content.return_value = MagicMock(embeddings=[embedding])
    provider = _provider(client)

    result = provider.create_embedding(
        "RAG converts documents into searchable vector representations.",
        EmbeddingTask.DOCUMENT,
    )

    assert result == vector
    assert len(result) == 768
    assert all(isinstance(value, float) for value in result)
    kwargs = client.models.embed_content.call_args.kwargs
    assert kwargs["model"] == "gemini-embedding-2"
    assert kwargs["config"].task_type == EmbeddingTask.DOCUMENT.value
    assert kwargs["config"].output_dimensionality == 768


def test_create_embedding_uses_query_task_type():
    embedding = MagicMock(values=[0.2] * 768)
    client = MagicMock()
    client.models.embed_content.return_value = MagicMock(embeddings=[embedding])
    provider = _provider(client)

    provider.create_embedding("What is RAG?", EmbeddingTask.QUERY)

    assert client.models.embed_content.call_args.kwargs["config"].task_type == (
        EmbeddingTask.QUERY.value
    )


def test_embedding_dimension_mismatch_raises():
    embedding = MagicMock(values=[0.1] * 32)
    client = MagicMock()
    client.models.embed_content.return_value = MagicMock(embeddings=[embedding])
    provider = _provider(client)

    with pytest.raises(EmbeddingDimensionError):
        provider.create_embedding("text", EmbeddingTask.DOCUMENT)


def test_empty_embedding_response_raises():
    client = MagicMock()
    client.models.embed_content.return_value = MagicMock(embeddings=[])
    provider = _provider(client)

    with pytest.raises(AIResponseError):
        provider.create_embedding("text", EmbeddingTask.DOCUMENT)


def test_empty_generation_response_raises():
    client = MagicMock()
    client.models.generate_content.return_value = MagicMock(text="   ")
    provider = _provider(client)

    with pytest.raises(AIEmptyResponseError):
        provider.generate_text("Hello")


def test_missing_api_key_raises_configuration_error():
    with pytest.raises(AIConfigurationError):
        GeminiProvider(settings=make_settings(gemini_api_key=""), client=MagicMock())


def test_authentication_error_is_mapped():
    client = MagicMock()
    client.models.generate_content.side_effect = ClientError(
        401,
        {"error": {"message": "invalid api key", "status": "UNAUTHENTICATED"}},
    )
    provider = _provider(client)

    with pytest.raises(AIAuthenticationError):
        provider.generate_text("Hello")


def test_rate_limit_error_is_mapped():
    client = MagicMock()
    client.models.embed_content.side_effect = ClientError(
        429,
        {"error": {"message": "rate limited", "status": "RESOURCE_EXHAUSTED"}},
    )
    provider = _provider(client)

    with pytest.raises(AIRateLimitError):
        provider.create_embedding("text", EmbeddingTask.QUERY)


def test_daily_quota_error_is_mapped_without_retryable_rate_limit():
    client = MagicMock()
    client.models.generate_content.side_effect = ClientError(
        429,
        {
            "error": {
                "message": (
                    "Quota exceeded for metric: generate_content_free_tier_requests, "
                    "quotaId: GenerateRequestsPerDayPerProjectPerModel-FreeTier"
                ),
                "status": "RESOURCE_EXHAUSTED",
            }
        },
    )
    provider = _provider(client)

    with pytest.raises(AIQuotaExhaustedError):
        provider.generate_text("Hello")


def test_unavailable_model_error_is_mapped():
    client = MagicMock()
    client.models.generate_content.side_effect = ClientError(
        404,
        {"error": {"message": "model not found", "status": "NOT_FOUND"}},
    )
    provider = _provider(client)

    with pytest.raises(AIModelUnavailableError):
        provider.generate_text("Hello")


def test_server_error_is_mapped():
    client = MagicMock()
    client.models.generate_content.side_effect = ServerError(
        503,
        {"error": {"message": "unavailable", "status": "UNAVAILABLE"}},
    )
    provider = _provider(client)

    with pytest.raises(AINetworkError):
        provider.generate_text("Hello")


def test_network_error_is_mapped():
    client = MagicMock()
    client.models.generate_content.side_effect = TimeoutError("timed out")
    provider = _provider(client)

    with pytest.raises(AINetworkError):
        provider.generate_text("Hello")


def test_unexpected_error_is_mapped_to_provider_error():
    client = MagicMock()
    client.models.generate_content.side_effect = RuntimeError("boom")
    provider = _provider(client)

    with pytest.raises(AIProviderError):
        provider.generate_text("Hello")


def test_httpx_timeout_is_mapped():
    client = MagicMock()
    client.models.generate_content.side_effect = httpx.ReadTimeout("timed out")
    provider = _provider(client)

    with pytest.raises(AINetworkError):
        provider.generate_text("Hello")


def test_client_uses_bounded_timeout_and_retries(monkeypatch: pytest.MonkeyPatch):
    captured: dict = {}

    def fake_client(**kwargs):
        captured.update(kwargs)
        return MagicMock()

    monkeypatch.setattr("app.services.ai.gemini_provider.genai.Client", fake_client)
    GeminiProvider(
        settings=make_settings(gemini_timeout_ms=15000, gemini_retry_attempts=2),
    )

    options = captured["http_options"]
    assert options.timeout == 15000
    assert options.retry_options.attempts == 2
    assert options.retry_options.max_delay == 2.0


def test_model_vector_dimension_matches_configuration():
    settings = get_settings()
    vector_type = DocumentChunk.__table__.c.embedding.type

    assert settings.embedding_dimension == 768
    assert vector_type.dim == settings.embedding_dimension
