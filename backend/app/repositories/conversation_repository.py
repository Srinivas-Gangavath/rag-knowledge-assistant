"""Database access for conversations and messages."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.workspace_context import WorkspaceContextProvider
from app.db.models import Conversation, Message


class ConversationRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, conversation: Conversation) -> Conversation:
        if getattr(conversation, "workspace_id", None) is None:
            conversation.workspace_id = WorkspaceContextProvider.get_default_workspace_id(self._session)
        self._session.add(conversation)
        self._session.flush()
        return conversation

    def get_by_id(self, conversation_id: UUID, workspace_id: UUID | None = None) -> Conversation | None:
        if workspace_id is not None:
            statement = select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.workspace_id == workspace_id,
            )
            return self._session.scalars(statement).first()
        return self._session.get(Conversation, conversation_id)

    def list_all(
        self,
        workspace_id: UUID | None = None,
        user_id: UUID | None = None,
    ) -> list[Conversation]:
        statement = select(Conversation)
        if workspace_id is not None:
            statement = statement.where(Conversation.workspace_id == workspace_id)
        if user_id is not None:
            statement = statement.where(Conversation.user_id == user_id)
        statement = statement.order_by(
            Conversation.updated_at.desc(),
            Conversation.id.desc(),
        )
        return list(self._session.scalars(statement))

    def delete(self, conversation_id: UUID, workspace_id: UUID | None = None) -> bool:
        conversation = self.get_by_id(conversation_id, workspace_id=workspace_id)
        if conversation is None:
            return False
        self._session.delete(conversation)
        self._session.flush()
        return True


class MessageRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, message: Message) -> Message:
        self._session.add(message)
        self._session.flush()
        return message

    def list_by_conversation(self, conversation_id: UUID) -> list[Message]:
        statement = (
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.asc(), Message.id.asc())
        )
        return list(self._session.scalars(statement))

    def list_recent(self, conversation_id: UUID, limit: int) -> list[Message]:
        if limit <= 0:
            return []
        statement = (
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(limit)
        )
        rows = list(self._session.scalars(statement))
        rows.reverse()
        return rows
