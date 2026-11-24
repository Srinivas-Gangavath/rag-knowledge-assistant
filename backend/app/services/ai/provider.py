"""AI provider abstraction.

The rest of the application depends on this interface, not on Gemini SDK types.
A future provider can implement the same methods without changing RAG logic.
"""

from abc import ABC, abstractmethod
from collections.abc import Iterator
from enum import Enum


class EmbeddingTask(str, Enum):
    """Why an embedding is being generated.

    Document chunks and user questions must not share the same task type.
    Gemini uses this to produce retrieval-oriented vectors.
    """

    DOCUMENT = "RETRIEVAL_DOCUMENT"
    QUERY = "RETRIEVAL_QUERY"


class AIProvider(ABC):
    """Minimal AI capabilities required by this V1."""

    @abstractmethod
    def generate_text(self, prompt: str) -> str:
        """Return generated text for a plain prompt."""

    @abstractmethod
    def stream_text(self, prompt: str) -> Iterator[str]:
        """Yield generated text chunks for a plain prompt without buffering the full answer."""

    @abstractmethod
    def create_embedding(self, text: str, task: EmbeddingTask) -> list[float]:
        """Return one embedding whose length equals EMBEDDING_DIMENSION."""
