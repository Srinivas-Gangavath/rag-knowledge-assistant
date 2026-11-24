"""Database access for User records."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import User


class UserRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, user: User) -> User:
        user.email = user.email.strip().lower()
        self._session.add(user)
        self._session.flush()
        return user

    def get_by_id(self, user_id: UUID) -> User | None:
        return self._session.get(User, user_id)

    def get_by_email(self, email: str) -> User | None:
        normalized = email.strip().lower()
        statement = select(User).where(User.email == normalized)
        return self._session.scalars(statement).first()

    def list_all(self) -> list[User]:
        statement = select(User).order_by(User.created_at.asc())
        return list(self._session.scalars(statement))
