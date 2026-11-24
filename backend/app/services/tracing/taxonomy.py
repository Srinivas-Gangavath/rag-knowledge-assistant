"""Platform Observability & Query Tracing Taxonomy.

Defines standardized span names, span types, execution statuses, and error categories
for fine-grained telemetry across the RAG lifecycle.
"""

from __future__ import annotations

import enum


class SpanName(enum.StrEnum):
    # Request & Security
    HTTP_REQUEST = "HTTP_REQUEST"
    AUTHENTICATION = "AUTHENTICATION"
    WORKSPACE_CONTEXT = "WORKSPACE_CONTEXT"

    # Turn & Preparation
    CONVERSATION_LOAD = "CONVERSATION_LOAD"
    QUERY_NORMALIZATION = "QUERY_NORMALIZATION"

    # Retrieval Pipeline
    EMBEDDING = "EMBEDDING"
    DENSE_RETRIEVAL = "DENSE_RETRIEVAL"
    LEXICAL_RETRIEVAL = "LEXICAL_RETRIEVAL"
    HYBRID_RRF = "HYBRID_RRF"
    RERANKING = "RERANKING"
    CONTEXT_BUILD = "CONTEXT_BUILD"

    # Generation & Delivery
    LLM_GENERATION = "LLM_GENERATION"
    STREAM_GENERATION = "STREAM_GENERATION"
    CITATION_BUILD = "CITATION_BUILD"
    MESSAGE_PERSISTENCE = "MESSAGE_PERSISTENCE"

    # Governance
    AUDIT_RECORD = "AUDIT_RECORD"


class SpanType(enum.StrEnum):
    HTTP = "HTTP"
    SECURITY = "SECURITY"
    INTERNAL = "INTERNAL"
    RETRIEVAL = "RETRIEVAL"
    AI_PROVIDER = "AI_PROVIDER"
    DATABASE = "DATABASE"
    AUDIT = "AUDIT"


class TraceStatus(enum.StrEnum):
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"
    PARTIAL = "PARTIAL"
    CANCELLED = "CANCELLED"


class ErrorCategory(enum.StrEnum):
    AUTH_ERROR = "AUTH_ERROR"
    TENANT_ACCESS_ERROR = "TENANT_ACCESS_ERROR"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    DATABASE_ERROR = "DATABASE_ERROR"
    EMBEDDING_PROVIDER_ERROR = "EMBEDDING_PROVIDER_ERROR"
    VECTOR_RETRIEVAL_ERROR = "VECTOR_RETRIEVAL_ERROR"
    LEXICAL_RETRIEVAL_ERROR = "LEXICAL_RETRIEVAL_ERROR"
    RERANKER_ERROR = "RERANKER_ERROR"
    LLM_PROVIDER_ERROR = "LLM_PROVIDER_ERROR"
    STREAM_ERROR = "STREAM_ERROR"
    TIMEOUT = "TIMEOUT"
    AUDIT_ERROR = "AUDIT_ERROR"
    UNKNOWN_ERROR = "UNKNOWN_ERROR"


def map_exception_to_category(exc: Exception) -> ErrorCategory:
    """Classify arbitrary exceptions into controlled, privacy-safe error categories."""
    exc_name = type(exc).__name__.lower()
    exc_str = str(exc).lower()

    if "auth" in exc_name or "unauthorized" in exc_name or "credential" in exc_name:
        return ErrorCategory.AUTH_ERROR
    if "permission" in exc_name or "forbidden" in exc_name or "tenant" in exc_name or "workspace" in exc_name:
        return ErrorCategory.TENANT_ACCESS_ERROR
    if "validation" in exc_name or "valueerror" in exc_name or "typeerror" in exc_name or "toolong" in exc_name or "empty" in exc_name:
        return ErrorCategory.VALIDATION_ERROR
    if "timeout" in exc_name or "timeout" in exc_str:
        return ErrorCategory.TIMEOUT
    if "embedding" in exc_name or "embed" in exc_str:
        return ErrorCategory.EMBEDDING_PROVIDER_ERROR
    if "rerank" in exc_name or "rerank" in exc_str:
        return ErrorCategory.RERANKER_ERROR
    if "stream" in exc_name or "stream" in exc_str:
        return ErrorCategory.STREAM_ERROR
    if "ai" in exc_name or "gemini" in exc_name or "quota" in exc_name or "ratelimit" in exc_name:
        return ErrorCategory.LLM_PROVIDER_ERROR
    if "sql" in exc_name or "db" in exc_name or "integrity" in exc_name or "operationalerror" in exc_name:
        return ErrorCategory.DATABASE_ERROR
    if "audit" in exc_name:
        return ErrorCategory.AUDIT_ERROR

    return ErrorCategory.UNKNOWN_ERROR
