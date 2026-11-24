"""Build the EmbeddingService used by evaluation.

Gemini evaluation must reuse production get_ai_provider() and EmbeddingService.
The local hashed provider is offline-only and is never used by chat or ingestion.
"""

from app.core.config import Settings
from app.services.ai import get_ai_provider
from app.services.embedding_service import EmbeddingService
from evaluation.local_embedder import LocalHashEmbeddingProvider

LOCAL_EMBEDDER_NAME = "local"
GEMINI_EMBEDDER_NAME = "gemini"
LOCAL_EMBEDDING_MODEL = "local-hash-ngram"


def embedding_service_for(embedder: str, settings: Settings) -> EmbeddingService:
    if embedder == GEMINI_EMBEDDER_NAME:
        return EmbeddingService(get_ai_provider(), settings)
    if embedder == LOCAL_EMBEDDER_NAME:
        return EmbeddingService(
            LocalHashEmbeddingProvider(settings.embedding_dimension),
            settings,
        )
    raise ValueError(f"Unknown embedder: {embedder}")


def embedding_model_label(embedder: str, settings: Settings) -> str:
    if embedder == GEMINI_EMBEDDER_NAME:
        return settings.embedding_model
    return LOCAL_EMBEDDING_MODEL


def embedder_display_name(embedder: str) -> str:
    if embedder == GEMINI_EMBEDDER_NAME:
        return "PRODUCTION EMBEDDING BASELINE"
    return "OFFLINE / LOCAL EMBEDDER"
