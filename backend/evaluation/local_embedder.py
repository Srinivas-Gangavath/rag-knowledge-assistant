"""Deterministic hashed n-gram embeddings for offline retrieval evaluation.

This provider is evaluation-only. Production chat and ingestion continue to use
Gemini through AIProvider. generate_text is intentionally unsupported.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Iterator

from app.services.ai.errors import AIConfigurationError
from app.services.ai.provider import AIProvider, EmbeddingTask

_TOKEN_RE = re.compile(r"[a-z0-9]+")


class LocalHashEmbeddingProvider(AIProvider):
    def __init__(self, dimension: int = 768) -> None:
        if dimension <= 0:
            raise ValueError("dimension must be greater than 0.")
        self._dimension = dimension

    def generate_text(self, prompt: str) -> str:
        del prompt
        raise AIConfigurationError(
            "LocalHashEmbeddingProvider does not generate text. "
            "Retrieval evaluation does not call the LLM."
        )

    def stream_text(self, prompt: str) -> Iterator[str]:
        del prompt
        raise AIConfigurationError(
            "LocalHashEmbeddingProvider does not stream text. "
            "Retrieval evaluation does not call the LLM."
        )
        if False:
            yield ""

    def create_embedding(self, text: str, task: EmbeddingTask) -> list[float]:
        del task
        values = [0.0] * self._dimension
        for feature in _features(text):
            digest = hashlib.sha256(feature.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self._dimension
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            values[index] += sign
            index_b = int.from_bytes(digest[8:12], "big") % self._dimension
            sign_b = 1.0 if digest[12] % 2 == 0 else -1.0
            values[index_b] += sign_b
        norm = math.sqrt(sum(value * value for value in values)) or 1.0
        return [value / norm for value in values]


def _features(text: str) -> list[str]:
    tokens = _TOKEN_RE.findall(text.lower())
    features = list(tokens)
    features.extend(f"{left}_{right}" for left, right in zip(tokens, tokens[1:]))
    for token in tokens:
        if len(token) >= 3:
            features.extend(f"c3:{token[index:index + 3]}" for index in range(len(token) - 2))
    return features
