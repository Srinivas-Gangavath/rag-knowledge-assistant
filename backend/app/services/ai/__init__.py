from app.services.ai.gemini_provider import GeminiProvider
from app.services.ai.provider import AIProvider, EmbeddingTask

__all__ = ["AIProvider", "EmbeddingTask", "GeminiProvider", "get_ai_provider"]


def get_ai_provider() -> AIProvider:
    """Return the configured AI provider.

    Construction is explicit so the FastAPI app can start without a Gemini key.
    """
    return GeminiProvider()
