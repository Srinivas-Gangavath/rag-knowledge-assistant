from unittest.mock import MagicMock

import pytest

from app.services.ai.errors import AINetworkError, EmbeddingDimensionError
from app.services.ai.provider import EmbeddingTask
from app.services.embedding_service import EmbeddingService
from tests.conftest import make_settings


def test_embed_documents_uses_document_task_and_returns_vectors():
    provider = MagicMock()
    provider.create_embedding.side_effect = lambda text, task: [0.5] * 768
    service = EmbeddingService(provider, make_settings())

    vectors = service.embed_documents(["first chunk", "second chunk"])

    assert len(vectors) == 2
    assert vectors[0] == [0.5] * 768
    assert provider.create_embedding.call_count == 2
    for call in provider.create_embedding.call_args_list:
        assert call.args[1] is EmbeddingTask.DOCUMENT


def test_embed_documents_rejects_wrong_dimension():
    provider = MagicMock()
    provider.create_embedding.return_value = [0.1] * 32
    service = EmbeddingService(provider, make_settings())

    with pytest.raises(EmbeddingDimensionError):
        service.embed_documents(["chunk"])


def test_embed_documents_propagates_provider_failure():
    provider = MagicMock()
    provider.create_embedding.side_effect = AINetworkError("Gemini is temporarily unavailable.")
    service = EmbeddingService(provider, make_settings())

    with pytest.raises(AINetworkError):
        service.embed_documents(["chunk"])


def test_embed_query_uses_query_task_and_validates_dimension():
    provider = MagicMock()
    provider.create_embedding.side_effect = lambda text, task: [0.4] * 768
    service = EmbeddingService(provider, make_settings())

    vector = service.embed_query("What is the refund period?")

    assert vector == [0.4] * 768
    provider.create_embedding.assert_called_once()
    assert provider.create_embedding.call_args.args[1] is EmbeddingTask.QUERY


def test_embed_query_rejects_wrong_dimension():
    provider = MagicMock()
    provider.create_embedding.return_value = [0.1] * 16
    service = EmbeddingService(provider, make_settings())

    with pytest.raises(EmbeddingDimensionError):
        service.embed_query("What is the refund period?")
