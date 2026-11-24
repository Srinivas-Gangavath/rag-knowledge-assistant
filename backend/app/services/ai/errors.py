"""Application-level AI errors.

These are raised by GeminiProvider and handled by FastAPI. Raw SDK exceptions
and API keys must never reach the frontend or the logs.
"""


class AIProviderError(Exception):
    """Base error for AI provider failures."""


class AIConfigurationError(AIProviderError):
    """The provider is missing required configuration."""


class AIAuthenticationError(AIProviderError):
    """The Gemini API rejected the configured credentials."""


class AIRateLimitError(AIProviderError):
    """The Gemini API rate limit was exceeded."""


class AIQuotaExhaustedError(AIRateLimitError):
    """Daily or billing quota is exhausted. Retrying will not help until it resets."""


class AINetworkError(AIProviderError):
    """A network error occurred while calling Gemini."""


class AIModelUnavailableError(AIProviderError):
    """The configured model is not available."""


class AIResponseError(AIProviderError):
    """Gemini returned a malformed or unexpected response."""


class AIEmptyResponseError(AIResponseError):
    """Gemini returned no generated text."""


class EmbeddingDimensionError(AIProviderError):
    """The embedding length did not match EMBEDDING_DIMENSION."""


AI_PUBLIC_ERROR_DETAIL = (
    "The AI service is temporarily unavailable. Please try again later."
)
