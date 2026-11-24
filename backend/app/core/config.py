"""Centralized application configuration.

Values are loaded from environment variables. Secrets must never be hard-coded.
Gemini model names and embedding dimension are configured here — never hard-coded
in provider methods or business logic.
"""

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# gemini-embedding-2 recommended output sizes. Keep this list in one place.
SUPPORTED_EMBEDDING_DIMENSIONS = (768, 1536, 3072)
DEFAULT_EMBEDDING_DIMENSION = 768
DEFAULT_LLM_MODEL = "gemini-3.7-flash"
DEFAULT_EMBEDDING_MODEL = "gemini-embedding-2"
DEFAULT_CHUNKING_STRATEGY = "fixed_word_window"
SUPPORTED_CHUNKING_STRATEGIES = ("fixed_word_window", "recursive")
DEFAULT_RETRIEVAL_MODE = "dense"
SUPPORTED_RETRIEVAL_MODES = ("dense", "hybrid")
DEFAULT_HYBRID_CANDIDATE_K = 20
DEFAULT_HYBRID_RRF_K = 60
DEFAULT_RERANKER_MODEL = "BAAI/bge-reranker-v2-m3"
DEFAULT_RERANK_CANDIDATE_K = 20
DEFAULT_RERANK_BATCH_SIZE = 16
DEFAULT_RERANK_MAX_CHARS = 24000
DEFAULT_MAX_SOURCE_EVIDENCE_CHARS = 3000


def validate_embedding_dimension(value: int) -> int:
    """Shared rule used by Settings and tests. Do not copy this check elsewhere."""
    if value not in SUPPORTED_EMBEDDING_DIMENSIONS:
        raise ValueError(
            "EMBEDDING_DIMENSION must be one of "
            f"{SUPPORTED_EMBEDDING_DIMENSIONS}, got {value}."
        )
    return value


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: str = "development"
    log_level: str = "INFO"

    database_url: str

    frontend_origin: str = "http://localhost:5173"

    gemini_api_key: str = ""
    llm_model: str = DEFAULT_LLM_MODEL
    embedding_model: str = DEFAULT_EMBEDDING_MODEL
    embedding_dimension: int = DEFAULT_EMBEDDING_DIMENSION

    chunking_strategy: str = DEFAULT_CHUNKING_STRATEGY
    chunk_size: int = 700
    chunk_overlap: int = 100
    # Cosine similarity = 1 - pgvector cosine_distance (<=>). Typical range [-1, 1].
    rag_top_k: int = 5
    rag_similarity_threshold: float = 0.7
    retrieval_mode: str = DEFAULT_RETRIEVAL_MODE
    hybrid_candidate_k: int = DEFAULT_HYBRID_CANDIDATE_K
    hybrid_rrf_k: int = DEFAULT_HYBRID_RRF_K
    reranking_enabled: bool = False
    reranker_model: str = DEFAULT_RERANKER_MODEL
    rerank_candidate_k: int = DEFAULT_RERANK_CANDIDATE_K
    rerank_batch_size: int = DEFAULT_RERANK_BATCH_SIZE
    rerank_max_chars: int = DEFAULT_RERANK_MAX_CHARS
    reranking_fallback: bool = True
    max_question_length: int = 2000
    max_source_evidence_chars: int = DEFAULT_MAX_SOURCE_EVIDENCE_CHARS
    # Recent messages included in the generation prompt. Full history stays in PostgreSQL.
    conversation_history_limit: int = 10
    max_upload_size_mb: int = 10
    storage_path: str = "/storage/documents"
    # Bound google-genai HTTP calls. attempts includes the original request.
    gemini_timeout_ms: int = 20000
    gemini_retry_attempts: int = 2

    # Authentication & Session Settings
    # Must be overridden via JWT_SECRET_KEY environment variable.
    # Required minimum 32 characters. No insecure default is provided.
    jwt_secret_key: str = ""
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7
    auth_cookie_name: str = "refresh_token"
    auth_cookie_secure: bool = False
    auth_cookie_samesite: str = "lax"
    auth_cookie_path: str = "/api/v1/auth"
    bootstrap_admin_email: str = ""
    bootstrap_admin_password: str = ""
    bootstrap_admin_name: str = "Default Administrator"

    # Trace Retention & Observability Analytics Settings
    trace_retention_days: int = 30
    trace_slow_query_threshold_ms: float = 2000.0
    trace_slow_retrieval_threshold_ms: float = 800.0
    trace_slow_llm_threshold_ms: float = 1500.0

    # Phase 1.8 Operational Alerting & Anomaly Detection Settings
    trace_alert_p95_latency_ms: float = 4000.0
    trace_alert_error_rate_percent: float = 10.0
    trace_alert_llm_p95_ms: float = 3000.0
    trace_alert_retrieval_p95_ms: float = 1500.0
    trace_alert_ttft_p95_ms: float = 2000.0
    trace_alert_provider_error_percent: float = 15.0
    trace_alert_no_context_percent: float = 20.0
    alert_default_window_minutes: int = 15
    alert_default_cooldown_minutes: int = 60
    alert_default_min_sample_size: int = 5
    alert_anomaly_deviation_multiplier: float = 2.0

    @field_validator("embedding_dimension", mode="before")
    @classmethod
    def parse_embedding_dimension(cls, value: object) -> int:
        if isinstance(value, bool) or value is None or value == "":
            raise ValueError("EMBEDDING_DIMENSION must be an integer.")
        try:
            parsed = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("EMBEDDING_DIMENSION must be an integer.") from exc
        return validate_embedding_dimension(parsed)

    @field_validator(
        "chunk_size",
        "chunk_overlap",
        "max_upload_size_mb",
        "rag_top_k",
        "max_question_length",
        "conversation_history_limit",
        "gemini_timeout_ms",
        "gemini_retry_attempts",
        "hybrid_candidate_k",
        "hybrid_rrf_k",
        "rerank_candidate_k",
        "rerank_batch_size",
        "rerank_max_chars",
        mode="before",
    )
    @classmethod
    def parse_positive_int(cls, value: object) -> int:
        if isinstance(value, bool) or value is None or value == "":
            raise ValueError("Value must be an integer.")
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("Value must be an integer.") from exc

    @field_validator("rag_similarity_threshold", mode="before")
    @classmethod
    def parse_similarity_threshold(cls, value: object) -> float:
        if isinstance(value, bool) or value is None or value == "":
            raise ValueError("RAG_SIMILARITY_THRESHOLD must be a number.")
        try:
            return float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("RAG_SIMILARITY_THRESHOLD must be a number.") from exc

    @field_validator("chunking_strategy", mode="before")
    @classmethod
    def parse_chunking_strategy(cls, value: object) -> str:
        if value is None or value == "":
            return DEFAULT_CHUNKING_STRATEGY
        if not isinstance(value, str):
            raise ValueError("CHUNKING_STRATEGY must be a string.")
        normalized = value.strip().lower()
        if normalized == "semantic":
            raise ValueError(
                "CHUNKING_STRATEGY 'semantic' is not implemented. "
                "Use 'fixed_word_window' or 'recursive'."
            )
        if normalized not in SUPPORTED_CHUNKING_STRATEGIES:
            raise ValueError(
                "CHUNKING_STRATEGY must be one of "
                f"{SUPPORTED_CHUNKING_STRATEGIES}, got {value!r}."
            )
        return normalized

    @field_validator("retrieval_mode", mode="before")
    @classmethod
    def parse_retrieval_mode(cls, value: object) -> str:
        if value is None or value == "":
            return DEFAULT_RETRIEVAL_MODE
        if not isinstance(value, str):
            raise ValueError("RETRIEVAL_MODE must be a string.")
        normalized = value.strip().lower()
        if normalized == "lexical":
            raise ValueError(
                "RETRIEVAL_MODE 'lexical' is evaluation-only and is not a production "
                "chat setting. Use 'dense' or 'hybrid'."
            )
        if normalized not in SUPPORTED_RETRIEVAL_MODES:
            raise ValueError(
                "RETRIEVAL_MODE must be one of "
                f"{SUPPORTED_RETRIEVAL_MODES}, got {value!r}."
            )
        return normalized

    @field_validator("reranking_enabled", mode="before")
    @classmethod
    def parse_reranking_enabled(cls, value: object) -> bool:
        return _parse_bool(value, default=False, name="RERANKING_ENABLED")

    @field_validator("reranking_fallback", mode="before")
    @classmethod
    def parse_reranking_fallback(cls, value: object) -> bool:
        return _parse_bool(value, default=True, name="RERANKING_FALLBACK")

    @field_validator("jwt_secret_key", mode="before")
    @classmethod
    def validate_jwt_secret_key(cls, value: object) -> str:
        """Reject empty, whitespace-only, or dangerously short JWT secrets.

        The error message deliberately omits the value so it cannot be leaked
        via log aggregation or error tracking.
        """
        if not isinstance(value, str):
            raise ValueError("JWT_SECRET_KEY must be a non-empty string.")
        stripped = value.strip()
        if not stripped:
            raise ValueError(
                "JWT_SECRET_KEY is not set. "
                "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
            )
        if len(stripped) < 32:
            raise ValueError(
                f"JWT_SECRET_KEY is too short ({len(stripped)} chars). "
                "Minimum length is 32 characters."
            )
        return stripped

    @field_validator("auth_cookie_secure", mode="before")
    @classmethod
    def parse_auth_cookie_secure(cls, value: object) -> bool:
        return _parse_bool(value, default=False, name="AUTH_COOKIE_SECURE")

    @field_validator("reranker_model", mode="before")
    @classmethod
    def parse_reranker_model(cls, value: object) -> str:
        if value is None or value == "":
            return DEFAULT_RERANKER_MODEL
        if not isinstance(value, str):
            raise ValueError("RERANKER_MODEL must be a string.")
        return value.strip()

    @field_validator("chunk_size")
    @classmethod
    def chunk_size_must_be_positive(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("CHUNK_SIZE must be greater than 0.")
        return value

    @field_validator("chunk_overlap")
    @classmethod
    def chunk_overlap_must_be_non_negative(cls, value: int) -> int:
        if value < 0:
            raise ValueError("CHUNK_OVERLAP must be 0 or greater.")
        return value

    @field_validator("max_upload_size_mb")
    @classmethod
    def upload_limit_must_be_positive(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("MAX_UPLOAD_SIZE_MB must be greater than 0.")
        return value

    @field_validator("rag_top_k")
    @classmethod
    def rag_top_k_must_be_positive(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("RAG_TOP_K must be greater than 0.")
        return value

    @field_validator("hybrid_candidate_k")
    @classmethod
    def hybrid_candidate_k_must_be_positive(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("HYBRID_CANDIDATE_K must be greater than 0.")
        return value

    @field_validator("hybrid_rrf_k")
    @classmethod
    def hybrid_rrf_k_must_be_positive(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("HYBRID_RRF_K must be greater than 0.")
        return value

    @field_validator("rerank_candidate_k")
    @classmethod
    def rerank_candidate_k_must_be_positive(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("RERANK_CANDIDATE_K must be greater than 0.")
        return value

    @field_validator("rerank_batch_size")
    @classmethod
    def rerank_batch_size_must_be_positive(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("RERANK_BATCH_SIZE must be greater than 0.")
        return value

    @field_validator("rerank_max_chars")
    @classmethod
    def rerank_max_chars_must_be_positive(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("RERANK_MAX_CHARS must be greater than 0.")
        return value

    @field_validator("max_question_length")
    @classmethod
    def question_limit_must_be_positive(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("MAX_QUESTION_LENGTH must be greater than 0.")
        return value

    @field_validator("conversation_history_limit")
    @classmethod
    def conversation_history_limit_must_be_non_negative(cls, value: int) -> int:
        if value < 0:
            raise ValueError("CONVERSATION_HISTORY_LIMIT must be 0 or greater.")
        return value

    @field_validator("gemini_timeout_ms")
    @classmethod
    def gemini_timeout_must_be_positive(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("GEMINI_TIMEOUT_MS must be greater than 0.")
        return value

    @field_validator("gemini_retry_attempts")
    @classmethod
    def gemini_retry_attempts_must_be_bounded(cls, value: int) -> int:
        if value < 1 or value > 5:
            raise ValueError("GEMINI_RETRY_ATTEMPTS must be between 1 and 5 inclusive.")
        return value

    @field_validator("rag_similarity_threshold")
    @classmethod
    def similarity_threshold_must_be_in_unit_range(cls, value: float) -> float:
        if value < 0 or value > 1:
            raise ValueError(
                "RAG_SIMILARITY_THRESHOLD must be between 0 and 1 inclusive "
                "(cosine similarity = 1 - pgvector cosine distance)."
            )
        return value

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024

    @property
    def cors_origins(self) -> list[str]:
        """Comma-separated FRONTEND_ORIGIN values for current and future environments."""
        return [
            origin.strip()
            for origin in self.frontend_origin.split(",")
            if origin.strip()
        ]

    @property
    def is_test(self) -> bool:
        return self.app_env.lower() == "test"

    def model_post_init(self, _context: object) -> None:
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("CHUNK_OVERLAP must be smaller than CHUNK_SIZE.")
        if self.rerank_candidate_k < self.rag_top_k:
            raise ValueError("RERANK_CANDIDATE_K must be greater than or equal to RAG_TOP_K.")
        if self.reranking_enabled and not self.reranker_model:
            raise ValueError("RERANKER_MODEL cannot be empty when RERANKING_ENABLED is true.")
        # Reject weak, placeholder, or default secrets in production
        if self.app_env.lower() == "production":
            known_insecure = {
                "dev-insecure-jwt-secret-change-in-production",
                "change-me-use-a-long-random-string",
                "test-only-jwt-secret-key-not-for-production-use-00000000",
            }
            lowered = self.jwt_secret_key.lower()
            if lowered in known_insecure or "change-me" in lowered or "placeholder" in lowered:
                raise ValueError(
                    "JWT_SECRET_KEY is using an insecure default or placeholder value. "
                    "A secure, randomly generated secret is required in production."
                )
        # Warn operators if HTTPS cookie security is disabled in a non-development env.
        if self.app_env.lower() == "production" and not self.auth_cookie_secure:
            import warnings
            warnings.warn(
                "AUTH_COOKIE_SECURE is false in production. "
                "Set AUTH_COOKIE_SECURE=true for HTTPS deployments.",
                stacklevel=2,
            )


def _parse_bool(value: object, *, default: bool, name: str) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    raise ValueError(f"{name} must be a boolean.")


@lru_cache
def get_settings() -> Settings:
    return Settings()
