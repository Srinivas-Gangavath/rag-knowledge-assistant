"""Thin wrapper around AIProvider for document embeddings."""

from app.core.config import Settings
from app.core.logging import get_logger
from app.services.ai.errors import EmbeddingDimensionError
from app.services.ai.provider import AIProvider, EmbeddingTask

logger = get_logger(__name__)


class EmbeddingService:
    def __init__(self, provider: AIProvider, settings: Settings) -> None:
        self._provider = provider
        self._settings = settings

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        embeddings: list[list[float]] = []
        for text in texts:
            vector = self._provider.create_embedding(text, EmbeddingTask.DOCUMENT)
            if len(vector) != self._settings.embedding_dimension:
                logger.error(
                    "Embedding dimension validation failed (expected=%s, actual=%s)",
                    self._settings.embedding_dimension,
                    len(vector),
                )
                raise EmbeddingDimensionError(
                    f"Embedding length {len(vector)} does not match configured "
                    f"EMBEDDING_DIMENSION {self._settings.embedding_dimension}."
                )
            embeddings.append(vector)
        logger.info("Document embeddings completed (count=%s)", len(embeddings))
        return embeddings

    def embed_query(self, text: str) -> list[float]:
        vector = self._provider.create_embedding(text, EmbeddingTask.QUERY)
        if len(vector) != self._settings.embedding_dimension:
            logger.error(
                "Embedding dimension validation failed (expected=%s, actual=%s)",
                self._settings.embedding_dimension,
                len(vector),
            )
            raise EmbeddingDimensionError(
                f"Embedding length {len(vector)} does not match configured "
                f"EMBEDDING_DIMENSION {self._settings.embedding_dimension}."
            )
        logger.info("Query embedding completed (dimension=%s)", len(vector))
        return vector
