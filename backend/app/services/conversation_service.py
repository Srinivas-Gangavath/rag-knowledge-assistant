"""Persist conversations and run the existing RAG path for each user turn with platform observability."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from time import perf_counter
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.core.permissions import Permission
from app.core.request_context import RequestContext, extract_request_context
from app.core.workspace_context import WorkspaceContext, WorkspaceContextProvider
from app.db.models import AuditEventType, AuditOutcome, Conversation, Message, MessageRole, Workspace
from app.repositories.conversation_repository import ConversationRepository, MessageRepository
from app.services.ai.errors import AI_PUBLIC_ERROR_DETAIL, AIEmptyResponseError, AIProviderError
from app.services.audit_service import AuditLogService
from app.services.chat_errors import ConversationNotFoundError
from app.services.rag import NO_CONTEXT_ANSWER, RagService, RagSource, sources_from_chunks
from app.services.rag_prompt import PromptTurn
from app.services.retrieval_filters import RetrievalFilters
from app.services.sse import format_sse
from app.services.tracing import (
    QueryTracer,
    SpanName,
    SpanType,
    TraceStatus,
    current_tracer,
    map_exception_to_category,
)

logger = get_logger(__name__)

TITLE_MAX_LENGTH = 80


@dataclass(frozen=True)
class ConversationChatResult:
    conversation_id: UUID
    user_message_id: UUID
    message_id: UUID
    answer: str
    sources: list[RagSource]


@dataclass
class PreparedTurn:
    conversation_id: UUID
    user_message_id: UUID
    history: list[PromptTurn]
    cleaned_question: str
    chunks: list
    prompt: str | None
    tracer: QueryTracer | None = None


def title_from_question(question: str) -> str:
    collapsed = " ".join(question.split())
    if len(collapsed) <= TITLE_MAX_LENGTH:
        return collapsed
    return collapsed[: TITLE_MAX_LENGTH - 3] + "..."


def sources_to_json(sources: list[RagSource]) -> list[dict]:
    return [
        {
            "document_id": str(source.document_id),
            "filename": source.filename,
            "page_number": source.page_number,
            "chunk_index": source.chunk_index,
            "similarity_score": source.similarity_score,
        }
        for source in sources
    ]


class ConversationService:
    def __init__(
        self,
        session: Session,
        settings: Settings | None = None,
        rag: RagService | None = None,
        autocommit: bool = True,
        workspace_id: UUID | None = None,
        user_id: UUID | None = None,
        is_admin: bool = False,
        workspace_context: WorkspaceContext | None = None,
        request_context: RequestContext | None = None,
        tracer: QueryTracer | None = None,
    ) -> None:
        self._session = session
        self._settings = settings or get_settings()
        self._conversations = ConversationRepository(session)
        self._messages = MessageRepository(session)
        self._rag = rag or RagService(session=session, settings=self._settings)
        self._autocommit = autocommit
        self._workspace_id = (
            workspace_id
            if workspace_id is not None
            else WorkspaceContextProvider.get_default_workspace_id(session)
        )
        self._user_id = user_id
        self._is_admin = is_admin
        self._workspace_context = workspace_context
        self._request_context = request_context or extract_request_context(None)
        self._tracer = tracer

    def _get_org_id(self) -> UUID:
        if self._workspace_context is not None:
            return self._workspace_context.organization_id
        ws = self._session.get(Workspace, self._workspace_id) if self._workspace_id else None
        if ws is not None:
            return ws.organization_id
        return WorkspaceContextProvider.get_default_workspace(self._session).organization_id

    def require_permission(self, permission: Permission) -> None:
        if self._workspace_context is not None and not self._workspace_context.can(permission):
            try:
                AuditLogService.record_event(
                    self._session,
                    organization_id=self._get_org_id(),
                    workspace_id=self._workspace_id,
                    actor_user_id=self._user_id,
                    event_type=(
                        AuditEventType.KNOWLEDGE_QUERY_DENIED
                        if permission == Permission.KNOWLEDGE_QUERY
                        else AuditEventType.PERMISSION_DENIED
                    ),
                    action="permission_check",
                    outcome=AuditOutcome.DENIED,
                    metadata={"permission": permission.value},
                    autocommit=True,
                )
            except Exception:
                pass
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission denied: {permission.value} capability required",
            )

    def create_conversation(self, title: str | None = None) -> Conversation:
        conversation = Conversation(
            workspace_id=self._workspace_id,
            user_id=self._user_id,
            title=title,
        )
        self._conversations.add(conversation)
        self._commit()
        return conversation

    def list_conversations(self) -> list[Conversation]:
        if self._is_admin or self._user_id is None:
            return self._conversations.list_all(workspace_id=self._workspace_id)
        return self._conversations.list_all(
            workspace_id=self._workspace_id,
            user_id=self._user_id,
        )

    def get_conversation(self, conversation_id: UUID) -> Conversation:
        conversation = self._conversations.get_by_id(conversation_id, workspace_id=self._workspace_id)
        if conversation is None:
            raise ConversationNotFoundError()
        if (
            not self._is_admin
            and conversation.user_id is not None
            and self._user_id is not None
            and conversation.user_id != self._user_id
        ):
            raise ConversationNotFoundError()
        return conversation

    def list_messages(self, conversation_id: UUID) -> list[Message]:
        self.get_conversation(conversation_id)
        return self._messages.list_by_conversation(conversation_id)

    def delete_conversation(self, conversation_id: UUID) -> None:
        self.get_conversation(conversation_id)
        if not self._conversations.delete(conversation_id, workspace_id=self._workspace_id):
            raise ConversationNotFoundError()
        self._commit()

    def _begin_turn(
        self,
        question: str,
        conversation_id: UUID | None = None,
    ) -> tuple[Conversation, Message, list[PromptTurn], str, QueryTracer]:
        tracer = self._tracer
        if tracer is None:
            tracer = QueryTracer(
                request_id=self._request_context.request_id,
                trace_id=self._request_context.trace_id,
                organization_id=self._get_org_id(),
                workspace_id=self._workspace_id,
                actor_user_id=self._user_id,
                conversation_id=conversation_id,
                operation_type="CHAT",
            )
            self._tracer = tracer
        current_tracer.set(tracer)

        # Authentication span
        if self._user_id is not None:
            with tracer.span(
                SpanName.AUTHENTICATION,
                SpanType.SECURITY,
                metadata={"actor_user_id": str(self._user_id)},
            ):
                pass

        # Workspace context span
        with tracer.span(
            SpanName.WORKSPACE_CONTEXT,
            SpanType.SECURITY,
            metadata={
                "organization_id": str(self._get_org_id()),
                "workspace_id": str(self._workspace_id) if self._workspace_id else None,
            },
        ):
            pass

        # Query normalization span
        with tracer.span(SpanName.QUERY_NORMALIZATION, SpanType.INTERNAL) as q_span:
            cleaned = self._rag.validate_question(question)
            q_hash = hashlib.sha256(cleaned.encode("utf-8")).hexdigest()
            q_span.update_metadata({
                "query_hash": q_hash,
                "character_count": len(cleaned),
            })

        # Conversation load span
        with tracer.span(SpanName.CONVERSATION_LOAD, SpanType.DATABASE) as load_span:
            if conversation_id is None:
                conversation = self._conversations.add(
                    Conversation(workspace_id=self._workspace_id, user_id=self._user_id)
                )
            else:
                conversation = self.get_conversation(conversation_id)

            tracer.conversation_id = conversation.id

            prior = self._messages.list_recent(
                conversation.id,
                self._settings.conversation_history_limit,
            )
            history = [
                PromptTurn(role=message.role.value, content=message.content)
                for message in prior
            ]
            load_span.update_metadata({
                "conversation_id": str(conversation.id),
                "history_turn_count": len(history),
            })

            user_message = self._messages.add(
                Message(
                    conversation_id=conversation.id,
                    role=MessageRole.USER,
                    content=cleaned,
                )
            )
            if conversation.title is None:
                conversation.title = title_from_question(cleaned)
            self._touch(conversation)

        return conversation, user_message, history, cleaned, tracer

    def prepare_turn(
        self,
        question: str,
        conversation_id: UUID | None = None,
        *,
        filters: RetrievalFilters | None = None,
    ) -> PreparedTurn:
        conversation, user_message, history, cleaned, tracer = self._begin_turn(
            question,
            conversation_id=conversation_id,
        )
        ws_role = self._workspace_context.workspace_role if self._workspace_context else None
        try:
            chunks = self._rag.retrieve_chunks(
                cleaned,
                filters=filters,
                workspace_id=self._workspace_id,
                user_id=self._user_id,
                workspace_role=ws_role,
                is_admin=self._is_admin,
            )
            prompt = None
            if chunks:
                prompt = self._rag.build_prompt(cleaned, chunks, history=history)
            else:
                logger.info("RETRIEVAL returned no relevant chunks; skipping generation")
        except Exception as exc:
            cat = map_exception_to_category(exc)
            tracer.set_status(TraceStatus.ERROR, error_type=cat.value, error_code=type(exc).__name__)
            tracer.persist(self._session)
            raise

        tracer.set_retrieval_summary(
            mode="hybrid",
            result_count=len(chunks),
            grounded=bool(chunks),
        )

        prepared = PreparedTurn(
            conversation_id=conversation.id,
            user_message_id=user_message.id,
            history=history,
            cleaned_question=cleaned,
            chunks=chunks,
            prompt=prompt,
            tracer=tracer,
        )
        # Record safe audit event (query hash, no user text, no chunk content)
        try:
            with tracer.span(SpanName.AUDIT_RECORD, SpanType.AUDIT):
                query_hash = hashlib.sha256(cleaned.encode("utf-8")).hexdigest()
                AuditLogService.record_event(
                    self._session,
                    organization_id=self._get_org_id(),
                    workspace_id=self._workspace_id,
                    actor_user_id=self._user_id,
                    event_type=AuditEventType.KNOWLEDGE_QUERY,
                    action="knowledge_query_stream",
                    outcome=AuditOutcome.SUCCESS,
                    resource_type="conversation",
                    resource_id=str(conversation.id),
                    request_id=tracer.request_id,
                    metadata={
                        "query_hash": query_hash,
                        "retrieval_mode": "hybrid",
                        "result_count": len(chunks),
                        "grounded": bool(chunks),
                        "conversation_id": str(conversation.id),
                    },
                )
        except Exception as exc:
            logger.error("Failed to record knowledge query stream audit event: %s", exc, exc_info=True)

        self._commit()
        return prepared

    def ask(
        self,
        question: str,
        conversation_id: UUID | None = None,
        *,
        filters: RetrievalFilters | None = None,
    ) -> ConversationChatResult:
        conversation, user_message, history, cleaned, tracer = self._begin_turn(
            question,
            conversation_id=conversation_id,
        )
        ws_role = self._workspace_context.workspace_role if self._workspace_context else None
        try:
            result = self._rag.answer(
                cleaned,
                history=history,
                filters=filters,
                workspace_id=self._workspace_id,
                user_id=self._user_id,
                workspace_role=ws_role,
                is_admin=self._is_admin,
            )
        except Exception as exc:
            cat = map_exception_to_category(exc)
            tracer.set_status(TraceStatus.ERROR, error_type=cat.value, error_code=type(exc).__name__)
            tracer.persist(self._session)
            raise

        # Citation span
        with tracer.span(
            SpanName.CITATION_BUILD,
            SpanType.INTERNAL,
            metadata={"citation_count": len(result.sources)},
        ):
            pass

        # Message persistence span
        with tracer.span(SpanName.MESSAGE_PERSISTENCE, SpanType.DATABASE) as persist_span:
            assistant_message_id = self._finalize_assistant(
                conversation.id,
                user_message.id,
                result.answer,
                result.sources,
            )
            persist_span.update_metadata({
                "message_id": str(assistant_message_id),
                "conversation_id": str(conversation.id),
            })

        # Record safe audit event (query hash, no user text, no chunk content)
        is_grounded = bool(result.sources) and result.answer != NO_CONTEXT_ANSWER
        try:
            with tracer.span(SpanName.AUDIT_RECORD, SpanType.AUDIT):
                query_hash = hashlib.sha256(cleaned.encode("utf-8")).hexdigest()
                AuditLogService.record_event(
                    self._session,
                    organization_id=self._get_org_id(),
                    workspace_id=self._workspace_id,
                    actor_user_id=self._user_id,
                    event_type=AuditEventType.KNOWLEDGE_QUERY,
                    action="knowledge_query",
                    outcome=AuditOutcome.SUCCESS,
                    resource_type="conversation",
                    resource_id=str(conversation.id),
                    request_id=tracer.request_id,
                    metadata={
                        "query_hash": query_hash,
                        "retrieval_mode": "hybrid",
                        "result_count": len(result.sources),
                        "grounded": is_grounded,
                        "conversation_id": str(conversation.id),
                    },
                )
                self._commit()
        except Exception as exc:
            logger.error("Failed to record knowledge query audit event: %s", exc, exc_info=True)

        tracer.set_retrieval_summary(
            mode="hybrid",
            result_count=len(result.sources),
            grounded=is_grounded,
        )
        tracer.persist(self._session)

        return ConversationChatResult(
            conversation_id=conversation.id,
            user_message_id=user_message.id,
            message_id=assistant_message_id,
            answer=result.answer,
            sources=result.sources,
        )

    def iter_chat_events(self, prepared: PreparedTurn) -> Iterator[str]:
        tracer = prepared.tracer
        stream_start_perf = perf_counter()
        first_token_perf: float | None = None
        chunk_count = 0
        terminal_status_set = False

        try:
            yield format_sse(
                "start",
                {
                    "conversation_id": str(prepared.conversation_id),
                    "user_message_id": str(prepared.user_message_id),
                },
            )
            if not prepared.chunks or not prepared.prompt:
                yield format_sse("token", {"text": NO_CONTEXT_ANSWER})
                if tracer:
                    with tracer.span(SpanName.MESSAGE_PERSISTENCE, SpanType.DATABASE):
                        assistant_message_id = self._finalize_assistant(
                            prepared.conversation_id,
                            prepared.user_message_id,
                            NO_CONTEXT_ANSWER,
                            [],
                        )
                else:
                    assistant_message_id = self._finalize_assistant(
                        prepared.conversation_id,
                        prepared.user_message_id,
                        NO_CONTEXT_ANSWER,
                        [],
                    )
                yield format_sse("sources", {"sources": []})
                yield format_sse(
                    "done",
                    {
                        "conversation_id": str(prepared.conversation_id),
                        "message_id": str(assistant_message_id),
                        "user_message_id": str(prepared.user_message_id),
                    },
                )
                terminal_status_set = True
                if tracer:
                    stream_dur = (perf_counter() - stream_start_perf) * 1000
                    tracer.record_llm_telemetry(
                        provider="none",
                        model="none",
                        latency_ms=stream_dur,
                        time_to_first_token_ms=0.0,
                    )
                return

            parts: list[str] = []
            for token in self._rag.stream_tokens(prepared.prompt):
                if first_token_perf is None:
                    first_token_perf = perf_counter()
                chunk_count += 1
                parts.append(token)
                yield format_sse("token", {"text": token})

            answer = "".join(parts)
            if not answer.strip():
                raise AIEmptyResponseError("Gemini returned an empty generation response.")

            sources = sources_from_chunks(prepared.chunks)
            if tracer:
                with tracer.span(SpanName.CITATION_BUILD, SpanType.INTERNAL, metadata={"citation_count": len(sources)}):
                    pass
                with tracer.span(SpanName.MESSAGE_PERSISTENCE, SpanType.DATABASE):
                    assistant_message_id = self._finalize_assistant(
                        prepared.conversation_id,
                        prepared.user_message_id,
                        answer,
                        sources,
                    )
            else:
                assistant_message_id = self._finalize_assistant(
                    prepared.conversation_id,
                    prepared.user_message_id,
                    answer,
                    sources,
                )

            yield format_sse("sources", {"sources": sources_to_json(sources)})
            yield format_sse(
                "done",
                {
                    "conversation_id": str(prepared.conversation_id),
                    "message_id": str(assistant_message_id),
                    "user_message_id": str(prepared.user_message_id),
                },
            )
            terminal_status_set = True
            logger.info("STREAM completed (characters=%s)", len(answer))
        except AIProviderError as exc:
            terminal_status_set = True
            if tracer:
                cat = map_exception_to_category(exc)
                tracer.set_status(TraceStatus.ERROR, error_type=cat.value, error_code=type(exc).__name__)
            logger.error("STREAM generation failed (%s)", type(exc).__name__)
            yield format_sse("error", {"detail": AI_PUBLIC_ERROR_DETAIL})
        except GeneratorExit:
            if tracer and not terminal_status_set:
                status = TraceStatus.PARTIAL if chunk_count > 0 else TraceStatus.CANCELLED
                tracer.set_status(status)
                terminal_status_set = True
            raise
        except Exception as exc:
            terminal_status_set = True
            if tracer:
                cat = map_exception_to_category(exc)
                tracer.set_status(TraceStatus.ERROR, error_type=cat.value, error_code=type(exc).__name__)
            raise
        finally:
            if tracer:
                stream_dur = (perf_counter() - stream_start_perf) * 1000
                ttft = ((first_token_perf - stream_start_perf) * 1000) if first_token_perf else None
                if not terminal_status_set:
                    status = TraceStatus.PARTIAL if chunk_count > 0 else TraceStatus.CANCELLED
                    tracer.set_status(status)
                tracer.record_llm_telemetry(
                    provider="gemini",
                    model=self._settings.llm_model,
                    latency_ms=stream_dur,
                    time_to_first_token_ms=ttft,
                )
                tracer.persist(self._session)

    def _finalize_assistant(
        self,
        conversation_id: UUID,
        user_message_id: UUID,
        answer: str,
        sources: list[RagSource],
    ) -> UUID:
        conversation = self.get_conversation(conversation_id)
        assistant_message = self._messages.add(
            Message(
                conversation_id=conversation_id,
                role=MessageRole.ASSISTANT,
                content=answer,
                sources=sources_to_json(sources),
            )
        )
        assistant_message_id = assistant_message.id
        self._touch(conversation)
        self._commit()
        logger.info(
            "CONVERSATION turn stored (conversation_id=%s user_message_id=%s message_id=%s)",
            conversation_id,
            user_message_id,
            assistant_message_id,
        )
        return assistant_message_id

    def _touch(self, conversation: Conversation) -> None:
        conversation.updated_at = datetime.now(timezone.utc)
        self._session.flush()

    def _commit(self) -> None:
        if self._autocommit:
            self._session.commit()
