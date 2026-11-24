"""QueryTracer & Span management for fine-grained RAG platform observability."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from time import perf_counter
from typing import Any, Iterator
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.db.models import QueryTrace, QueryTraceSpan
from app.services.tracing.sanitizer import sanitize_metadata
from app.services.tracing.taxonomy import (
    ErrorCategory,
    SpanName,
    SpanType,
    TraceStatus,
    map_exception_to_category,
)

logger = get_logger(__name__)

# Context variable for thread/coroutine local tracer access
current_tracer: ContextVar[QueryTracer | None] = ContextVar("current_tracer", default=None)


@dataclass
class SpanRecord:
    id: UUID = field(default_factory=uuid4)
    span_name: str = ""
    span_type: str = SpanType.INTERNAL
    parent_span_id: UUID | None = None
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    duration_ms: float | None = None
    status: str = TraceStatus.SUCCESS
    error_type: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def set_metadata(self, key: str, value: Any) -> None:
        self.metadata[key] = value

    def update_metadata(self, data: dict[str, Any]) -> None:
        self.metadata.update(data)


class QueryTracer:
    """Manages lifecycle, spans, and telemetry for a single RAG request/operation."""

    def __init__(
        self,
        request_id: str,
        trace_id: str,
        organization_id: UUID,
        workspace_id: UUID | None = None,
        actor_user_id: UUID | None = None,
        conversation_id: UUID | None = None,
        operation_type: str = "CHAT",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.id = uuid4()
        self.request_id = request_id
        self.trace_id = trace_id
        self.organization_id = organization_id
        self.workspace_id = workspace_id
        self.actor_user_id = actor_user_id
        self.conversation_id = conversation_id
        self.operation_type = operation_type
        self.status = TraceStatus.SUCCESS
        self.started_at = datetime.now(timezone.utc)
        self._start_perf = perf_counter()
        self.completed_at: datetime | None = None
        self.total_latency_ms: float | None = None
        self.error_type: str | None = None
        self.error_code: str | None = None
        self.retrieval_mode: str | None = None
        self.grounded: bool | None = None
        self.result_count: int | None = None
        self.metadata: dict[str, Any] = metadata or {}
        self.spans: list[SpanRecord] = []
        self._active_span_stack: list[SpanRecord] = []

    def current_span_id(self) -> UUID | None:
        if self._active_span_stack:
            return self._active_span_stack[-1].id
        return None

    @contextmanager
    def span(
        self,
        span_name: SpanName | str,
        span_type: SpanType | str = SpanType.INTERNAL,
        parent_span_id: UUID | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Iterator[SpanRecord]:
        """Context manager to measure and record a trace span."""
        name_str = span_name.value if isinstance(span_name, SpanName) else str(span_name)
        type_str = span_type.value if isinstance(span_type, SpanType) else str(span_type)
        parent_id = parent_span_id or self.current_span_id()

        record = SpanRecord(
            span_name=name_str,
            span_type=type_str,
            parent_span_id=parent_id,
            started_at=datetime.now(timezone.utc),
            metadata=sanitize_metadata(metadata or {}),
        )
        self.spans.append(record)
        self._active_span_stack.append(record)
        span_perf = perf_counter()

        try:
            yield record
            if record.status is None or record.status == "":
                record.status = TraceStatus.SUCCESS
        except Exception as exc:
            record.status = TraceStatus.ERROR
            cat = map_exception_to_category(exc)
            record.error_type = cat.value
            record.set_metadata("error_message_safe", type(exc).__name__)
            self.set_status(TraceStatus.ERROR, error_type=cat.value, error_code=type(exc).__name__)
            raise
        finally:
            record.duration_ms = max(0.0, (perf_counter() - span_perf) * 1000)
            record.completed_at = datetime.now(timezone.utc)
            record.metadata = sanitize_metadata(record.metadata)
            if self._active_span_stack and self._active_span_stack[-1] is record:
                self._active_span_stack.pop()

    def set_status(
        self,
        status: TraceStatus | str,
        error_type: ErrorCategory | str | None = None,
        error_code: str | None = None,
    ) -> None:
        self.status = status.value if isinstance(status, TraceStatus) else str(status)
        if error_type:
            self.error_type = error_type.value if isinstance(error_type, ErrorCategory) else str(error_type)
        if error_code:
            self.error_code = str(error_code)

    def set_retrieval_summary(
        self,
        mode: str | None,
        result_count: int | None,
        grounded: bool | None,
    ) -> None:
        self.retrieval_mode = mode
        self.result_count = result_count
        self.grounded = grounded

    def record_embedding_telemetry(
        self,
        provider: str,
        model: str,
        operation_type: str,
        item_count: int,
        dimension: int,
        latency_ms: float,
        error: Exception | None = None,
        retry_count: int = 0,
        query_hash: str | None = None,
    ) -> None:
        meta = {
            "provider": provider,
            "model": model,
            "operation_type": operation_type,
            "item_count": item_count,
            "dimension": dimension,
            "latency_ms": round(latency_ms, 2),
            "retry_count": retry_count,
        }
        if query_hash:
            meta["query_hash"] = query_hash

        status = TraceStatus.SUCCESS if error is None else TraceStatus.ERROR
        err_cat = map_exception_to_category(error).value if error else None

        record = SpanRecord(
            span_name=SpanName.EMBEDDING.value,
            span_type=SpanType.AI_PROVIDER.value,
            parent_span_id=self.current_span_id(),
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
            duration_ms=round(latency_ms, 2),
            status=status,
            error_type=err_cat,
            metadata=sanitize_metadata(meta),
        )
        self.spans.append(record)

    def record_llm_telemetry(
        self,
        provider: str,
        model: str,
        latency_ms: float,
        input_token_count: int | None = None,
        output_token_count: int | None = None,
        total_token_count: int | None = None,
        finish_reason: str | None = None,
        safety_status: str | None = None,
        time_to_first_token_ms: float | None = None,
        retry_count: int = 0,
        error: Exception | None = None,
    ) -> None:
        # Validate that token counts cannot be negative
        valid_input = input_token_count if (input_token_count is not None and input_token_count >= 0) else None
        valid_output = output_token_count if (output_token_count is not None and output_token_count >= 0) else None
        token_usage_available = valid_input is not None or valid_output is not None

        meta: dict[str, Any] = {
            "provider": provider,
            "model": model,
            "latency_ms": round(max(0.0, latency_ms), 2),
            "token_usage_available": token_usage_available,
            "retry_count": max(0, retry_count),
        }
        if token_usage_available:
            meta["input_token_count"] = valid_input
            meta["output_token_count"] = valid_output
            calc_total = total_token_count if (total_token_count is not None and total_token_count >= 0) else ((valid_input or 0) + (valid_output or 0))
            meta["total_token_count"] = calc_total
        if finish_reason:
            meta["finish_reason"] = finish_reason
        if safety_status:
            meta["safety_status"] = safety_status
        if time_to_first_token_ms is not None and time_to_first_token_ms >= 0:
            meta["time_to_first_token_ms"] = round(time_to_first_token_ms, 2)

        status = TraceStatus.SUCCESS if error is None else TraceStatus.ERROR
        err_cat = map_exception_to_category(error).value if error else None

        record = SpanRecord(
            span_name=SpanName.LLM_GENERATION.value,
            span_type=SpanType.AI_PROVIDER.value,
            parent_span_id=self.current_span_id(),
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
            duration_ms=round(max(0.0, latency_ms), 2),
            status=status,
            error_type=err_cat,
            metadata=sanitize_metadata(meta),
        )
        self.spans.append(record)

    def finalize(self) -> None:
        """Compute final latency and completion time."""
        if self.completed_at is None:
            self.completed_at = datetime.now(timezone.utc)
            self.total_latency_ms = max(0.0, (perf_counter() - self._start_perf) * 1000)

    def persist(self, db: Session) -> QueryTrace | None:
        """Persist the complete query trace and all child spans to the database.

        Uses an isolated savepoint so that trace persistence failures NEVER
        break the business transaction or raise unhandled exceptions.
        """
        self.finalize()
        try:
            with db.begin_nested():
                trace_row = QueryTrace(
                    id=self.id,
                    trace_id=self.trace_id,
                    request_id=self.request_id,
                    organization_id=self.organization_id,
                    workspace_id=self.workspace_id,
                    actor_user_id=self.actor_user_id,
                    conversation_id=self.conversation_id,
                    operation_type=self.operation_type,
                    status=self.status,
                    started_at=self.started_at,
                    completed_at=self.completed_at,
                    total_latency_ms=self.total_latency_ms,
                    error_type=self.error_type,
                    error_code=self.error_code,
                    retrieval_mode=self.retrieval_mode,
                    grounded=self.grounded,
                    result_count=self.result_count,
                    metadata_=sanitize_metadata(self.metadata),
                )
                db.add(trace_row)
                db.flush()

                for span_rec in self.spans:
                    span_row = QueryTraceSpan(
                        id=span_rec.id,
                        trace_id=self.trace_id,
                        parent_span_id=span_rec.parent_span_id,
                        span_name=span_rec.span_name,
                        span_type=span_rec.span_type,
                        started_at=span_rec.started_at,
                        completed_at=span_rec.completed_at or span_rec.started_at,
                        duration_ms=span_rec.duration_ms,
                        status=span_rec.status,
                        error_type=span_rec.error_type,
                        metadata_=sanitize_metadata(span_rec.metadata),
                    )
                    db.add(span_row)

                db.flush()
                return trace_row
        except Exception as exc:
            logger.warning("Failed to persist QueryTrace (trace_id=%s): %s", self.trace_id, exc)
            return None
