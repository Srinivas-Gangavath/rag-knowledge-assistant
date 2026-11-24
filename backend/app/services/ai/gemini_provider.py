"""Gemini implementation of AIProvider.

All google-genai SDK usage stays in this module. Callers receive plain strings
and lists of floats, never raw SDK response objects.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING, NoReturn

import httpx
from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
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
from app.services.ai.provider import AIProvider, EmbeddingTask

if TYPE_CHECKING:
    from google.genai import Client

logger = get_logger(__name__)


class GeminiProvider(AIProvider):
    def __init__(
        self,
        settings: Settings | None = None,
        client: Client | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._validate_settings()
        self._client = client or genai.Client(
            api_key=self._settings.gemini_api_key,
            http_options=self._http_options(),
        )
        logger.info(
            "Gemini provider initialized (llm_model=%s, embedding_model=%s, embedding_dimension=%s)",
            self._settings.llm_model,
            self._settings.embedding_model,
            self._settings.embedding_dimension,
        )

    def _http_options(self) -> types.HttpOptions:
        """Cap SDK retries so a 503 cannot hang the request for minutes."""
        return types.HttpOptions(
            timeout=self._settings.gemini_timeout_ms,
            retry_options=types.HttpRetryOptions(
                attempts=self._settings.gemini_retry_attempts,
                initial_delay=0.5,
                max_delay=2.0,
                exp_base=2.0,
                jitter=0.1,
            ),
        )

    def _validate_settings(self) -> None:
        if not self._settings.gemini_api_key:
            raise AIConfigurationError("GEMINI_API_KEY is not configured.")
        if not self._settings.llm_model:
            raise AIConfigurationError("LLM_MODEL is not configured.")
        if not self._settings.embedding_model:
            raise AIConfigurationError("EMBEDDING_MODEL is not configured.")

    def generate_text(self, prompt: str) -> str:
        if not prompt or not prompt.strip():
            raise AIResponseError("A non-empty prompt is required.")

        logger.info("Gemini generation requested")
        try:
            response = self._client.models.generate_content(
                model=self._settings.llm_model,
                contents=prompt,
            )
        except Exception as exc:
            self._handle_gemini_error(exc, action="generation")

        try:
            from app.services.tracing import SpanName, current_tracer
            tracer = current_tracer.get()
            if tracer and tracer.spans:
                usage = getattr(response, "usage_metadata", None)
                in_tokens = getattr(usage, "prompt_token_count", None) if usage else None
                out_tokens = getattr(usage, "candidates_token_count", None) if usage else None
                tot_tokens = getattr(usage, "total_token_count", None) if usage else None
                has_usage = in_tokens is not None or out_tokens is not None
                finish_reason = None
                candidates = getattr(response, "candidates", None)
                if candidates and len(candidates) > 0:
                    finish_reason = str(getattr(candidates[0], "finish_reason", "") or "")

                llm_spans = [s for s in tracer.spans if s.span_name == SpanName.LLM_GENERATION.value]
                if llm_spans:
                    llm_spans[-1].update_metadata({
                        "token_usage_available": has_usage,
                        "input_token_count": in_tokens,
                        "output_token_count": out_tokens,
                        "total_token_count": tot_tokens,
                        "finish_reason": finish_reason or "STOP",
                    })
        except Exception:
            pass

        text = self._extract_text(response)
        logger.info("Gemini generation completed (characters=%s)", len(text))
        return text

    def stream_text(self, prompt: str) -> Iterator[str]:
        if not prompt or not prompt.strip():
            raise AIResponseError("A non-empty prompt is required.")

        logger.info("Gemini streaming generation requested")
        stream = None
        produced = False
        try:
            stream = self._client.models.generate_content_stream(
                model=self._settings.llm_model,
                contents=prompt,
            )
            for chunk in stream:
                text = getattr(chunk, "text", None)
                if not isinstance(text, str) or text == "":
                    continue
                produced = True
                yield text
        except Exception as exc:
            self._handle_gemini_error(exc, action="streaming generation")
        finally:
            close = getattr(stream, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass

        if not produced:
            raise AIEmptyResponseError("Gemini returned an empty generation response.")
        logger.info("Gemini streaming generation completed")

    def create_embedding(self, text: str, task: EmbeddingTask) -> list[float]:
        if not text or not text.strip():
            raise AIResponseError("A non-empty text value is required to create an embedding.")

        logger.info("Gemini embedding requested (task=%s)", task.value)
        try:
            response = self._client.models.embed_content(
                model=self._settings.embedding_model,
                contents=text,
                config=types.EmbedContentConfig(
                    task_type=task.value,
                    output_dimensionality=self._settings.embedding_dimension,
                ),
            )
        except Exception as exc:
            self._handle_gemini_error(exc, action="embedding")

        values = self._extract_embedding_values(response)
        self._validate_embedding_dimension(values)
        logger.info(
            "Gemini embedding completed (task=%s, dimension=%s)",
            task.value,
            len(values),
        )
        return values

    def _extract_text(self, response: object) -> str:
        text = getattr(response, "text", None)
        if isinstance(text, str) and text.strip():
            return text.strip()
        raise AIEmptyResponseError("Gemini returned an empty generation response.")

    def _extract_embedding_values(self, response: object) -> list[float]:
        embeddings = getattr(response, "embeddings", None)
        if not embeddings:
            raise AIResponseError("Gemini returned no embeddings.")

        first = embeddings[0]
        values = getattr(first, "values", None)
        if values is None:
            raise AIResponseError("Gemini returned an embedding without values.")

        try:
            vector = [float(item) for item in values]
        except (TypeError, ValueError) as exc:
            raise AIResponseError("Gemini returned a non-numeric embedding vector.") from exc

        if not vector:
            raise AIResponseError("Gemini returned an empty embedding vector.")
        return vector

    def _validate_embedding_dimension(self, values: list[float]) -> None:
        expected = self._settings.embedding_dimension
        actual = len(values)
        if actual != expected:
            logger.error(
                "Embedding dimension validation failed (expected=%s, actual=%s)",
                expected,
                actual,
            )
            raise EmbeddingDimensionError(
                f"Embedding length {actual} does not match configured "
                f"EMBEDDING_DIMENSION {expected}."
            )

    def _handle_gemini_error(self, exc: Exception, action: str) -> NoReturn:
        logger.error("Gemini %s request failed (%s)", action, type(exc).__name__)

        if isinstance(exc, AIProviderError):
            raise exc

        if isinstance(exc, (TimeoutError, ConnectionError, OSError, httpx.TimeoutException, httpx.RequestError)):
            raise AINetworkError("A network error occurred while calling Gemini.") from exc

        if isinstance(exc, genai_errors.APIError):
            code = getattr(exc, "code", None)
            if code in {401, 403}:
                raise AIAuthenticationError("Gemini authentication failed.") from exc
            if code == 429:
                if _is_daily_quota_error(exc):
                    raise AIQuotaExhaustedError("Gemini daily quota exhausted.") from exc
                raise AIRateLimitError("Gemini rate limit exceeded.") from exc
            if code == 404:
                raise AIModelUnavailableError("The configured Gemini model is unavailable.") from exc
            if isinstance(exc, genai_errors.ServerError):
                raise AINetworkError("Gemini is temporarily unavailable.") from exc
            raise AIProviderError("Gemini request failed.") from exc

        raise AIProviderError("Gemini request failed.") from exc


def _is_daily_quota_error(exc: Exception) -> bool:
    """True when Gemini reports a daily/billing quota, not a short per-minute limit."""
    normalized = str(exc).lower().replace("_", "").replace("-", "").replace(" ", "")
    return "perday" in normalized or "dailyquota" in normalized
