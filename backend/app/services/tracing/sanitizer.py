"""Privacy-safe metadata sanitizer for Query Traces and Spans.

Ensures no raw user questions, prompts, chunk text, LLM answers,
authorization headers, access tokens, or sensitive credentials are ever persisted.
"""

from __future__ import annotations

from typing import Any

BLOCKED_KEYS = {
    "query",
    "raw_query",
    "question",
    "raw_question",
    "user_question",
    "prompt",
    "raw_prompt",
    "user_prompt",
    "content",
    "chunk_content",
    "chunk_text",
    "text",
    "response",
    "raw_response",
    "response_text",
    "completion",
    "answer",
    "raw_answer",
    "context",
    "context_text",
    "document_text",
    "authorization",
    "access_token",
    "refresh_token",
    "password",
    "secret",
    "api_key",
    "cookie",
    "cookies",
    "set-cookie",
    "bearer",
    "credentials",
}

SAFE_EXPLICIT_KEYS = {
    "query_hash",
    "token_usage_available",
    "input_token_count",
    "output_token_count",
    "total_token_count",
    "time_to_first_token_ms",
    "time_to_first_token",
    "top_k",
    "api_key_configured",
    "character_count",
    "history_turn_count",
    "candidate_count",
    "dense_count",
    "lexical_count",
    "fused_count",
    "selected_count",
    "citation_count",
    "source_count",
    "has_filters",
    "reranking_enabled",
    "provider",
    "model",
    "operation_type",
    "dimension",
    "item_count",
    "latency_ms",
    "retry_count",
    "conversation_id",
    "message_id",
    "actor_user_id",
    "workspace_id",
    "organization_id",
    "finish_reason",
    "safety_status",
    "error_message_safe",
    "error_type",
}


def sanitize_metadata(data: Any, max_depth: int = 6) -> Any:
    """Recursively sanitize a metadata dictionary/list to ensure privacy safety."""
    if max_depth <= 0:
        return "<max_depth_exceeded>"

    if isinstance(data, dict):
        cleaned: dict[str, Any] = {}
        for key, value in data.items():
            key_str = str(key).strip().lower()
            if key_str in BLOCKED_KEYS:
                continue
            if key_str not in SAFE_EXPLICIT_KEYS:
                if any(
                    blocked in key_str
                    for blocked in (
                        "query",
                        "question",
                        "prompt",
                        "context",
                        "content",
                        "response",
                        "completion",
                        "answer",
                        "token",
                        "secret",
                        "password",
                        "key",
                        "auth",
                        "cookie",
                        "bearer",
                        "credential",
                    )
                ):
                    continue
            cleaned[str(key)] = sanitize_metadata(value, max_depth=max_depth - 1)
        return cleaned

    if isinstance(data, (list, tuple, set)):
        return [sanitize_metadata(item, max_depth=max_depth - 1) for item in data]

    if isinstance(data, (int, float, bool)) or data is None:
        return data

    if isinstance(data, str):
        # Prevent huge text dumps or accidentally stringified payloads
        if len(data) > 500:
            return data[:500] + "...<truncated>"
        return data

    # For custom objects or exceptions
    if hasattr(data, "__dict__"):
        return sanitize_metadata(vars(data), max_depth=max_depth - 1)

    return str(data)
