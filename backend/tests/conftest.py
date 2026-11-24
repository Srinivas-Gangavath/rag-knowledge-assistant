"""Shared pytest fixtures.

Automated tests do not call the live Gemini API. Database tests use the
Compose PostgreSQL instance when it is available, and skip otherwise.
"""

import os
from collections.abc import Generator

os.environ["APP_ENV"] = "test"
os.environ.setdefault(
    "DATABASE_URL",
    "postgresql+psycopg://test:test@localhost:5432/test",
)
os.environ.setdefault("FRONTEND_ORIGIN", "http://localhost:5173")
os.environ.setdefault("LOG_LEVEL", "WARNING")
os.environ.setdefault("LLM_MODEL", "gemini-3.7-flash")
os.environ.setdefault("EMBEDDING_MODEL", "gemini-embedding-2")
os.environ.setdefault("EMBEDDING_DIMENSION", "768")
# Provide a safe, sufficiently-long test secret so JWT validation passes.
# This value is never used for real token signing in CI.
os.environ.setdefault(
    "JWT_SECRET_KEY",
    "test-only-jwt-secret-key-not-for-production-use-00000000",
)

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.database import engine
from app.main import app

get_settings.cache_clear()


def make_settings(**overrides) -> Settings:
    values = {
        "database_url": "postgresql+psycopg://test:test@localhost:5432/test",
        "gemini_api_key": "test-gemini-key",
        "llm_model": "gemini-3.7-flash",
        "embedding_model": "gemini-embedding-2",
        "embedding_dimension": 768,
        "app_env": "test",
        "chunking_strategy": "fixed_word_window",
        "chunk_size": 700,
        "chunk_overlap": 100,
        "max_upload_size_mb": 10,
        "rag_top_k": 5,
        "rag_similarity_threshold": 0.7,
        "max_question_length": 2000,
        "conversation_history_limit": 10,
        # 56-char string satisfies the ≥32-char JWT secret requirement in tests.
        "jwt_secret_key": "test-only-jwt-secret-key-not-for-production-use-00000000",
    }
    values.update(overrides)
    return Settings(**values)


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    with TestClient(app) as test_client:
        yield test_client


def postgres_available() -> bool:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    if not postgres_available():
        pytest.skip("PostgreSQL is not available for database tests.")

    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
