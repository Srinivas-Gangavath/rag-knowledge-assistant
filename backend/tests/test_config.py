import pytest
from pydantic import ValidationError

from app.core.config import (
    DEFAULT_CHUNKING_STRATEGY,
    DEFAULT_EMBEDDING_DIMENSION,
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_LLM_MODEL,
    SUPPORTED_CHUNKING_STRATEGIES,
    SUPPORTED_EMBEDDING_DIMENSIONS,
)
from tests.conftest import make_settings


def test_gemini_settings_load_from_constructor():
    settings = make_settings(
        gemini_api_key="unit-test-key",
        llm_model="gemini-3.7-flash",
        embedding_model="gemini-embedding-2",
        embedding_dimension=768,
    )

    assert settings.gemini_api_key == "unit-test-key"
    assert settings.llm_model == "gemini-3.7-flash"
    assert settings.embedding_model == "gemini-embedding-2"
    assert settings.embedding_dimension == 768
    assert isinstance(settings.embedding_dimension, int)


def test_embedding_dimension_string_is_parsed_as_int():
    settings = make_settings(embedding_dimension="768")

    assert settings.embedding_dimension == 768
    assert isinstance(settings.embedding_dimension, int)


def test_default_models_match_v1_development_values():
    settings = make_settings(
        llm_model=DEFAULT_LLM_MODEL,
        embedding_model=DEFAULT_EMBEDDING_MODEL,
    )

    assert settings.llm_model == "gemini-3.7-flash"
    assert settings.embedding_model == "gemini-embedding-2"
    assert settings.embedding_dimension == DEFAULT_EMBEDDING_DIMENSION


def test_unsupported_embedding_dimension_is_rejected():
    with pytest.raises(ValidationError):
        make_settings(embedding_dimension=512)


def test_supported_embedding_dimensions_are_accepted():
    for dimension in SUPPORTED_EMBEDDING_DIMENSIONS:
        settings = make_settings(embedding_dimension=dimension)
        assert settings.embedding_dimension == dimension


def test_gemini_timeout_and_retry_settings():
    settings = make_settings(gemini_timeout_ms=15000, gemini_retry_attempts=2)
    assert settings.gemini_timeout_ms == 15000
    assert settings.gemini_retry_attempts == 2


def test_gemini_retry_attempts_must_be_bounded():
    with pytest.raises(ValidationError):
        make_settings(gemini_retry_attempts=0)
    with pytest.raises(ValidationError):
        make_settings(gemini_retry_attempts=6)


def test_conversation_history_limit_default_and_zero():
    settings = make_settings()
    assert settings.conversation_history_limit == 10
    assert make_settings(conversation_history_limit=0).conversation_history_limit == 0


def test_conversation_history_limit_rejects_negative():
    with pytest.raises(ValidationError):
        make_settings(conversation_history_limit=-1)


def test_chunking_strategy_defaults_to_fixed_word_window():
    settings = make_settings()
    assert settings.chunking_strategy == DEFAULT_CHUNKING_STRATEGY
    assert settings.chunking_strategy == "fixed_word_window"
    assert settings.chunk_size == 700
    assert settings.chunk_overlap == 100


def test_chunking_strategy_accepts_recursive():
    settings = make_settings(chunking_strategy="recursive")
    assert settings.chunking_strategy == "recursive"
    assert settings.chunking_strategy in SUPPORTED_CHUNKING_STRATEGIES


def test_chunking_strategy_rejects_semantic_and_unknown():
    with pytest.raises(ValidationError, match="semantic"):
        make_settings(chunking_strategy="semantic")
    with pytest.raises(ValidationError, match="must be one of"):
        make_settings(chunking_strategy="parent_child")


def test_retrieval_mode_defaults_to_dense_and_accepts_hybrid():
    settings = make_settings()
    assert settings.retrieval_mode == "dense"
    assert settings.hybrid_candidate_k == 20
    assert settings.hybrid_rrf_k == 60
    assert make_settings(retrieval_mode="hybrid").retrieval_mode == "hybrid"


def test_retrieval_mode_rejects_lexical_and_unknown():
    with pytest.raises(ValidationError, match="evaluation-only"):
        make_settings(retrieval_mode="lexical")
    with pytest.raises(ValidationError, match="must be one of"):
        make_settings(retrieval_mode="bm25")


def test_hybrid_k_values_must_be_positive():
    with pytest.raises(ValidationError, match="HYBRID_CANDIDATE_K"):
        make_settings(hybrid_candidate_k=0)
    with pytest.raises(ValidationError, match="HYBRID_RRF_K"):
        make_settings(hybrid_rrf_k=-1)


def test_reranking_defaults_are_disabled_and_validated():
    settings = make_settings()
    assert settings.reranking_enabled is False
    assert settings.reranker_model == "BAAI/bge-reranker-v2-m3"
    assert settings.rerank_candidate_k == 20
    assert settings.rerank_batch_size == 16
    assert settings.rerank_max_chars == 24000
    assert settings.reranking_fallback is True
    assert settings.retrieval_mode == "dense"


def test_rerank_candidate_k_must_be_at_least_rag_top_k():
    with pytest.raises(ValidationError, match="RERANK_CANDIDATE_K"):
        make_settings(rag_top_k=5, rerank_candidate_k=4)


def test_rerank_batch_size_and_max_chars_must_be_positive():
    with pytest.raises(ValidationError, match="RERANK_BATCH_SIZE"):
        make_settings(rerank_batch_size=0)
    with pytest.raises(ValidationError, match="RERANK_MAX_CHARS"):
        make_settings(rerank_max_chars=-1)


def test_reranker_model_cannot_be_blank_when_enabled():
    with pytest.raises(ValidationError, match="RERANKER_MODEL"):
        make_settings(reranking_enabled=True, reranker_model="   ")


def test_jwt_secret_key_empty_is_rejected():
    with pytest.raises(ValidationError, match="JWT_SECRET_KEY is not set"):
        make_settings(jwt_secret_key="")


def test_jwt_secret_key_short_is_rejected():
    with pytest.raises(ValidationError, match="JWT_SECRET_KEY is too short"):
        make_settings(jwt_secret_key="too-short-secret")


def test_jwt_secret_key_production_rejects_weak_values():
    with pytest.raises(ValidationError, match="insecure default or placeholder"):
        make_settings(
            app_env="production",
            jwt_secret_key="dev-insecure-jwt-secret-change-in-production",
        )
