"""Helpers for tests that must actually commit, then inspect a new session."""

from uuid import UUID

from sqlalchemy import delete

from app.db.database import SessionLocal
from app.db.models import Document


def delete_document(document_id: UUID) -> None:
    session = SessionLocal()
    try:
        session.execute(delete(Document).where(Document.id == document_id))
        session.commit()
    finally:
        session.close()
