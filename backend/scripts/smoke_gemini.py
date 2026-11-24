"""Development smoke test for the live Gemini API.

Automated pytest tests mock Gemini. Run this script only when you want to
verify a real API key, model, and embedding dimension.

  docker compose exec backend python -m scripts.smoke_gemini
"""

from __future__ import annotations

import sys

from app.core.config import get_settings
from app.core.logging import setup_logging
from app.services.ai.errors import AIConfigurationError
from app.services.ai.gemini_provider import GeminiProvider
from app.services.ai.provider import EmbeddingTask

GENERATION_PROMPT = "Reply with exactly: Gemini connection successful."
EMBEDDING_TEXT = "RAG converts documents into searchable vector representations."


def main() -> int:
    setup_logging()
    settings = get_settings()

    print("Gemini smoke test")
    print(f"  llm_model={settings.llm_model}")
    print(f"  embedding_model={settings.embedding_model}")
    print(f"  embedding_dimension={settings.embedding_dimension}")

    try:
        provider = GeminiProvider(settings)
    except AIConfigurationError as exc:
        print(f"FAILED: {exc}")
        print("Set GEMINI_API_KEY in .env and restart the backend container.")
        return 1

    print("\nA. Text generation")
    text = provider.generate_text(GENERATION_PROMPT)
    if not text:
        print("FAILED: generation returned an empty response.")
        return 1
    print(f"  ok  characters={len(text)}")
    print(f"  preview={text[:160]!r}")

    print("\nB. Embedding generation")
    embedding = provider.create_embedding(EMBEDDING_TEXT, EmbeddingTask.DOCUMENT)
    numeric = all(isinstance(value, (int, float)) for value in embedding)
    print(f"  length={len(embedding)}")
    print(f"  numeric={numeric}")
    if not embedding or not numeric:
        print("FAILED: embedding is missing or not numeric.")
        return 1
    if len(embedding) != settings.embedding_dimension:
        print(
            "FAILED: embedding length "
            f"{len(embedding)} != EMBEDDING_DIMENSION {settings.embedding_dimension}."
        )
        return 1
    print("  ok  dimension matches configuration")

    print("\nSmoke test passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
