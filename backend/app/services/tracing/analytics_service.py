"""Performance analytics, latency percentiles, and slow-query diagnostics service.

Calculates:
- High-precision latency aggregates (average, p50, p95, p99)
- Stage-level latency breakdowns
- Slow-query and dominant-stage bottleneck diagnostics
- AI provider, model, and token usage analytics
- Streaming TTFT and duration metrics
- Safe diagnostic trace exports
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session, selectinload

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.workspace_context import WorkspaceContext
from app.db.models import (
    AuditEventType,
    AuditOutcome,
    OrganizationRole,
    QueryTrace,
    QueryTraceSpan,
    WorkspaceRole,
)
from app.schemas.trace import (
    ErrorAnalytics,
    ProviderModelStats,
    SlowQuerySummary,
    SlowTraceItemResponse,
    SlowTraceListResponse,
    StageLatencyStats,
    StreamingAnalytics,
    TraceAnalyticsOverview,
    TraceAnalyticsResponse,
    TraceExportDiagnostics,
    TraceExportResponse,
)
from app.services.audit_service import AuditLogService
from app.services.tracing.taxonomy import SpanName, SpanType, TraceStatus

logger = get_logger(__name__)

EXPORT_SENSITIVE_KEYS = {
    "query",
    "question",
    "prompt",
    "context",
    "chunk_text",
    "chunk_content",
    "content",
    "response",
    "raw_response",
    "password",
    "hashed_password",
    "token",
    "access_token",
    "refresh_token",
    "secret",
    "authorization",
    "cookie",
    "api_key",
    "gemini_api_key",
    "key",
}


def sanitize_export_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    """Recursively sanitize trace/span metadata for safe diagnostic export."""
    if not metadata:
        return {}

    sanitized: dict[str, Any] = {}
    for key, value in metadata.items():
        key_lower = str(key).lower()
        if any(sens in key_lower for sens in EXPORT_SENSITIVE_KEYS):
            continue

        if isinstance(value, dict):
            sanitized[key] = sanitize_export_metadata(value)
        elif isinstance(value, (list, tuple, set)):
            clean_list = []
            for item in value:
                if isinstance(item, dict):
                    clean_list.append(sanitize_export_metadata(item))
                elif not any(sens in str(item).lower() for sens in EXPORT_SENSITIVE_KEYS):
                    clean_list.append(str(item) if isinstance(item, UUID) else item)
            sanitized[key] = clean_list
        elif isinstance(value, UUID):
            sanitized[key] = str(value)
        elif isinstance(value, (str, int, float, bool)) or value is None:
            sanitized[key] = value
        else:
            sanitized[key] = str(value)

    return sanitized

RETRIEVAL_SPANS = {
    SpanName.EMBEDDING.value,
    SpanName.DENSE_RETRIEVAL.value,
    SpanName.LEXICAL_RETRIEVAL.value,
    SpanName.HYBRID_RRF.value,
    SpanName.RERANKING.value,
    SpanName.CONTEXT_BUILD.value,
}

GENERATION_SPANS = {
    SpanName.LLM_GENERATION.value,
    SpanName.STREAM_GENERATION.value,
}


def _calculate_percentiles(values: list[float]) -> tuple[float, float, float, float, float]:
    """Calculate (average, p50, p95, p99, max) with linear interpolation."""
    if not values:
        return 0.0, 0.0, 0.0, 0.0, 0.0
    s = sorted(values)
    n = len(s)
    avg = sum(s) / n
    if n == 1:
        v = s[0]
        return avg, v, v, v, v

    def _pct(p: float) -> float:
        idx = (n - 1) * p
        low = int(idx)
        high = min(low + 1, n - 1)
        weight = idx - low
        return s[low] * (1.0 - weight) + s[high] * weight

    return avg, _pct(0.50), _pct(0.95), _pct(0.99), s[-1]


class TraceAnalyticsService:
    """Provides platform performance metrics, slow query diagnosis, and trace export."""

    @staticmethod
    def _verify_analytics_access(
        context: WorkspaceContext,
        target_workspace_id: UUID | None = None,
    ) -> None:
        """Enforce role permissions for analytics retrieval."""
        is_org_admin = context.organization_role in {OrganizationRole.OWNER, OrganizationRole.ADMIN}
        is_ws_admin = context.workspace_role == WorkspaceRole.WORKSPACE_ADMIN

        if not is_org_admin and not is_ws_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Analytics access requires Workspace Admin or Organization Admin privileges.",
            )

        if not is_org_admin and is_ws_admin:
            if target_workspace_id is not None and target_workspace_id != context.workspace_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Workspace Admin is restricted to analytics within their active workspace.",
                )

    @classmethod
    def classify_slow_query(cls, total_latency_ms: float | None) -> str:
        """Categorize total latency into standardized diagnostic buckets."""
        if total_latency_ms is None or total_latency_ms < 0:
            return "UNKNOWN"
        settings = get_settings()
        slow_threshold = settings.trace_slow_query_threshold_ms
        if total_latency_ms < 500.0:
            return "FAST"
        if total_latency_ms < slow_threshold:
            return "NORMAL"
        if total_latency_ms < (slow_threshold * 2.5):
            return "SLOW"
        return "VERY_SLOW"

    @classmethod
    def diagnose_trace(cls, trace: QueryTrace) -> TraceExportDiagnostics:
        """Analyze a trace's span breakdown to identify bottlenecks and dominant stages."""
        slow_class = cls.classify_slow_query(trace.total_latency_ms)
        spans = trace.spans or []
        stage_durations: dict[str, float] = {}
        retrieval_total = 0.0
        generation_total = 0.0

        for span in spans:
            dur = span.duration_ms or 0.0
            stage_durations[span.span_name] = stage_durations.get(span.span_name, 0.0) + dur
            if span.span_name in RETRIEVAL_SPANS:
                retrieval_total += dur
            elif span.span_name in GENERATION_SPANS:
                generation_total += dur

        total_dur = sum(stage_durations.values()) or (trace.total_latency_ms or 0.0)
        dominant_stage: str | None = None
        dominant_duration: float | None = None
        dominant_pct: float | None = None

        if stage_durations:
            dominant_stage, dominant_duration = max(stage_durations.items(), key=lambda x: x[1])
            if total_dur > 0:
                dominant_pct = round((dominant_duration / total_dur) * 100.0, 2)

        stage_pcts: dict[str, float] = {}
        if total_dur > 0:
            for stage, dur in stage_durations.items():
                stage_pcts[stage] = round((dur / total_dur) * 100.0, 2)

        return TraceExportDiagnostics(
            slow_classification=slow_class,
            dominant_stage=dominant_stage,
            dominant_stage_duration_ms=dominant_duration,
            dominant_stage_percentage=dominant_pct,
            stage_durations_ms=stage_durations,
            stage_percentages=stage_pcts,
            is_retrieval_dominant=retrieval_total > generation_total,
            is_generation_dominant=generation_total >= retrieval_total and generation_total > 0,
        )

    @classmethod
    def get_analytics(
        cls,
        session: Session,
        context: WorkspaceContext,
        *,
        workspace_id: UUID | None = None,
        from_time: datetime | None = None,
        to_time: datetime | None = None,
        operation_type: str | None = None,
        retrieval_mode: str | None = None,
    ) -> TraceAnalyticsResponse:
        """Compute aggregated latency, stage breakdowns, slow queries, and error statistics."""
        effective_ws_id = workspace_id or (
            context.workspace_id if context.organization_role not in {OrganizationRole.OWNER, OrganizationRole.ADMIN} else None
        )
        cls._verify_analytics_access(context, target_workspace_id=effective_ws_id)
        settings = get_settings()

        # Build base trace query
        query: Select = select(QueryTrace).where(
            QueryTrace.organization_id == context.organization_id
        )
        if effective_ws_id is not None:
            query = query.where(QueryTrace.workspace_id == effective_ws_id)
        if from_time is not None:
            query = query.where(QueryTrace.started_at >= from_time)
        if to_time is not None:
            query = query.where(QueryTrace.started_at <= to_time)
        if operation_type:
            query = query.where(QueryTrace.operation_type == operation_type.upper())
        if retrieval_mode:
            query = query.where(QueryTrace.retrieval_mode == retrieval_mode.lower())

        traces = list(session.scalars(query.options(selectinload(QueryTrace.spans))).all())
        total_requests = len(traces)

        # 1. Overview counts & latencies
        successful_count = sum(1 for t in traces if t.status == TraceStatus.SUCCESS.value)
        error_count = sum(1 for t in traces if t.status == TraceStatus.ERROR.value)
        cancelled_count = sum(1 for t in traces if t.status == TraceStatus.CANCELLED.value)
        partial_count = sum(1 for t in traces if t.status == TraceStatus.PARTIAL.value)
        error_rate = round(error_count / total_requests, 4) if total_requests > 0 else 0.0

        latencies = [t.total_latency_ms for t in traces if t.total_latency_ms is not None]
        avg_lat, p50_lat, p95_lat, p99_lat, _ = _calculate_percentiles(latencies)

        overview = TraceAnalyticsOverview(
            request_count=total_requests,
            successful_count=successful_count,
            error_count=error_count,
            cancelled_count=cancelled_count,
            partial_count=partial_count,
            error_rate=error_rate,
            average_latency_ms=round(avg_lat, 2),
            p50_latency_ms=round(p50_lat, 2),
            p95_latency_ms=round(p95_lat, 2),
            p99_latency_ms=round(p99_lat, 2),
        )

        # 2. Stage Breakdown
        stage_map: dict[str, list[float]] = {}
        for t in traces:
            for s in (t.spans or []):
                if s.duration_ms is not None:
                    stage_map.setdefault(s.span_name, []).append(s.duration_ms)

        total_stage_time = sum(sum(v) for v in stage_map.values())
        stages_res: list[StageLatencyStats] = []
        for stage_name, durations in sorted(stage_map.items()):
            s_avg, s_p50, s_p95, s_p99, s_max = _calculate_percentiles(durations)
            stage_sum = sum(durations)
            pct = round((stage_sum / total_stage_time) * 100.0, 2) if total_stage_time > 0 else 0.0
            stages_res.append(
                StageLatencyStats(
                    stage=stage_name,
                    count=len(durations),
                    average_ms=round(s_avg, 2),
                    p50_ms=round(s_p50, 2),
                    p95_ms=round(s_p95, 2),
                    p99_ms=round(s_p99, 2),
                    max_ms=round(s_max, 2),
                    percentage_of_total=pct,
                )
            )

        # 3. Slow Queries summary
        slow_thresh = settings.trace_slow_query_threshold_ms
        very_slow_thresh = slow_thresh * 2.5
        slow_cnt = sum(1 for t in traces if t.total_latency_ms and slow_thresh <= t.total_latency_ms < very_slow_thresh)
        very_slow_cnt = sum(1 for t in traces if t.total_latency_ms and t.total_latency_ms >= very_slow_thresh)
        slow_rate = round((slow_cnt + very_slow_cnt) / total_requests, 4) if total_requests > 0 else 0.0

        slow_queries = SlowQuerySummary(
            slow_count=slow_cnt,
            very_slow_count=very_slow_cnt,
            slow_rate=slow_rate,
            threshold_ms=slow_thresh,
        )

        # 4. Errors breakdown
        errors_by_cat: dict[str, int] = {}
        errors_by_op: dict[str, int] = {}
        failing_stages_map: dict[str, int] = {}

        for t in traces:
            if t.status == TraceStatus.ERROR.value:
                cat = t.error_type or "UNKNOWN_ERROR"
                errors_by_cat[cat] = errors_by_cat.get(cat, 0) + 1
                errors_by_op[t.operation_type] = errors_by_op.get(t.operation_type, 0) + 1
            for s in (t.spans or []):
                if s.status == TraceStatus.ERROR.value:
                    failing_stages_map[s.span_name] = failing_stages_map.get(s.span_name, 0) + 1

        top_failing = [
            {"stage": stg, "error_count": cnt}
            for stg, cnt in sorted(failing_stages_map.items(), key=lambda x: x[1], reverse=True)
        ]

        errors_res = ErrorAnalytics(
            total_errors=error_count,
            error_rate=error_rate,
            errors_by_category=errors_by_cat,
            errors_by_operation=errors_by_op,
            top_failing_stages=top_failing,
        )

        # 5. AI Provider / Model Telemetry
        providers_map: dict[tuple[str, str], dict[str, Any]] = {}
        for t in traces:
            for s in (t.spans or []):
                meta = s.metadata_ or {}
                prov = meta.get("provider")
                mod = meta.get("model")
                if prov and mod and prov != "none":
                    key = (str(prov), str(mod))
                    if key not in providers_map:
                        providers_map[key] = {
                            "latencies": [],
                            "error_count": 0,
                            "input_tokens": 0,
                            "output_tokens": 0,
                            "total_tokens": 0,
                            "token_usage_available": True,
                        }
                    entry = providers_map[key]
                    if s.duration_ms is not None:
                        entry["latencies"].append(s.duration_ms)
                    if s.status == TraceStatus.ERROR.value:
                        entry["error_count"] += 1
                    if meta.get("token_usage_available") is False:
                        entry["token_usage_available"] = False
                    entry["input_tokens"] += meta.get("input_token_count") or 0
                    entry["output_tokens"] += meta.get("output_token_count") or 0
                    entry["total_tokens"] += meta.get("total_token_count") or 0

        providers_res: list[ProviderModelStats] = []
        for (prov, mod), data in sorted(providers_map.items()):
            p_avg, _, p_p95, _, _ = _calculate_percentiles(data["latencies"])
            providers_res.append(
                ProviderModelStats(
                    provider=prov,
                    model=mod,
                    request_count=len(data["latencies"]),
                    error_count=data["error_count"],
                    average_latency_ms=round(p_avg, 2),
                    p95_latency_ms=round(p_p95, 2),
                    input_token_count=data["input_tokens"],
                    output_token_count=data["output_tokens"],
                    total_token_count=data["total_tokens"],
                    token_usage_available=data["token_usage_available"],
                )
            )

        # 6. Streaming Analytics
        stream_traces: list[QueryTrace] = []
        ttft_values: list[float] = []
        stream_durations: list[float] = []

        for t in traces:
            # Look for STREAM_GENERATION span or time_to_first_token_ms in metadata
            stream_spans = [s for s in (t.spans or []) if s.span_name == SpanName.STREAM_GENERATION.value]
            if stream_spans or (t.metadata_ and "time_to_first_token_ms" in t.metadata_):
                stream_traces.append(t)
                for s in stream_spans:
                    meta = s.metadata_ or {}
                    ttft = meta.get("time_to_first_token_ms")
                    if ttft is not None:
                        ttft_values.append(float(ttft))
                    if s.duration_ms is not None:
                        stream_durations.append(s.duration_ms)

        stream_count = len(stream_traces)
        if stream_count > 0:
            st_success = sum(1 for t in stream_traces if t.status == TraceStatus.SUCCESS.value)
            st_cancel = sum(1 for t in stream_traces if t.status == TraceStatus.CANCELLED.value)
            st_partial = sum(1 for t in stream_traces if t.status == TraceStatus.PARTIAL.value)
            st_error = sum(1 for t in stream_traces if t.status == TraceStatus.ERROR.value)

            ttft_avg, ttft_p50, ttft_p95, ttft_p99, _ = _calculate_percentiles(ttft_values)
            st_dur_avg, _, _, _, _ = _calculate_percentiles(stream_durations)

            streaming_res = StreamingAnalytics(
                stream_count=stream_count,
                success_rate=round(st_success / stream_count, 4),
                cancellation_rate=round(st_cancel / stream_count, 4),
                partial_rate=round(st_partial / stream_count, 4),
                provider_error_rate=round(st_error / stream_count, 4),
                average_ttft_ms=round(ttft_avg, 2) if ttft_values else None,
                p50_ttft_ms=round(ttft_p50, 2) if ttft_values else None,
                p95_ttft_ms=round(ttft_p95, 2) if ttft_values else None,
                p99_ttft_ms=round(ttft_p99, 2) if ttft_values else None,
                average_stream_duration_ms=round(st_dur_avg, 2) if stream_durations else None,
            )
        else:
            streaming_res = StreamingAnalytics(
                stream_count=0,
                success_rate=0.0,
                cancellation_rate=0.0,
                partial_rate=0.0,
                provider_error_rate=0.0,
            )

        return TraceAnalyticsResponse(
            overview=overview,
            stages=stages_res,
            slow_queries=slow_queries,
            errors=errors_res,
            providers=providers_res,
            streaming=streaming_res,
        )

    @classmethod
    def list_slow_traces(
        cls,
        session: Session,
        context: WorkspaceContext,
        *,
        min_latency_ms: float | None = None,
        workspace_id: UUID | None = None,
        from_time: datetime | None = None,
        to_time: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> SlowTraceListResponse:
        """List slow traces with diagnostic dominant-stage classifications."""
        effective_ws_id = workspace_id or (
            context.workspace_id if context.organization_role not in {OrganizationRole.OWNER, OrganizationRole.ADMIN} else None
        )
        cls._verify_analytics_access(context, target_workspace_id=effective_ws_id)
        settings = get_settings()

        threshold = min_latency_ms if min_latency_ms is not None else settings.trace_slow_query_threshold_ms

        base_query: Select = select(QueryTrace).where(
            QueryTrace.organization_id == context.organization_id,
            QueryTrace.total_latency_ms >= threshold,
        )
        if effective_ws_id is not None:
            base_query = base_query.where(QueryTrace.workspace_id == effective_ws_id)
        if from_time is not None:
            base_query = base_query.where(QueryTrace.started_at >= from_time)
        if to_time is not None:
            base_query = base_query.where(QueryTrace.started_at <= to_time)

        count_stmt = select(func.count()).select_from(base_query.subquery())
        total_count = session.scalar(count_stmt) or 0

        items_stmt = (
            base_query.options(selectinload(QueryTrace.spans))
            .order_by(QueryTrace.total_latency_ms.desc(), QueryTrace.started_at.desc())
            .limit(min(max(1, limit), 100))
            .offset(max(0, offset))
        )
        traces = list(session.scalars(items_stmt).all())

        item_responses: list[SlowTraceItemResponse] = []
        for t in traces:
            diag = cls.diagnose_trace(t)
            item_responses.append(
                SlowTraceItemResponse(
                    trace_id=t.trace_id,
                    request_id=t.request_id,
                    organization_id=t.organization_id,
                    workspace_id=t.workspace_id,
                    started_at=t.started_at,
                    total_latency_ms=t.total_latency_ms or 0.0,
                    status=t.status,
                    operation_type=t.operation_type,
                    retrieval_mode=t.retrieval_mode,
                    slow_classification=diag.slow_classification,
                    dominant_stage=diag.dominant_stage,
                    dominant_stage_duration_ms=diag.dominant_stage_duration_ms,
                    dominant_stage_percentage=diag.dominant_stage_percentage,
                    is_retrieval_dominant=diag.is_retrieval_dominant,
                    is_generation_dominant=diag.is_generation_dominant,
                )
            )

        return SlowTraceListResponse(
            items=item_responses,
            total=total_count,
            limit=limit,
            offset=offset,
        )

    @classmethod
    def export_trace(
        cls,
        session: Session,
        context: WorkspaceContext,
        trace_id: str,
    ) -> TraceExportResponse:
        """Export sanitized diagnostic trace data with bottleneck breakdown and compliance audit record."""
        from app.services.tracing.service import TraceService

        # 1. Authenticate & authorize trace access
        trace = TraceService.get_trace_by_id(session, context, trace_id=trace_id)
        diag = cls.diagnose_trace(trace)

        # 2. Record immutable compliance audit event for operational trace export
        AuditLogService.record_event(
            session,
            organization_id=context.organization_id,
            workspace_id=trace.workspace_id,
            actor_user_id=context.user_id,
            actor_email=None,
            event_type=AuditEventType.TRACE_EXPORTED,
            action="EXPORT",
            outcome=AuditOutcome.SUCCESS,
            resource_type="QUERY_TRACE",
            resource_id=trace.trace_id,
            metadata={
                "trace_id": trace.trace_id,
                "workspace_id": str(trace.workspace_id) if trace.workspace_id else None,
                "request_id": trace.request_id,
                "export_format": "JSON",
                "total_latency_ms": trace.total_latency_ms,
                "operation_type": trace.operation_type,
            },
            request_id=trace.request_id,
        )
        session.flush()

        # 3. Sanitize trace and span metadata recursively
        clean_trace_meta = sanitize_export_metadata(trace.metadata_ or {})

        sorted_spans = sorted(trace.spans or [], key=lambda s: (s.started_at, str(s.id)))
        spans_export = [
            {
                "id": s.id,
                "trace_id": s.trace_id,
                "parent_span_id": s.parent_span_id,
                "span_name": s.span_name,
                "span_type": s.span_type,
                "started_at": s.started_at,
                "completed_at": s.completed_at,
                "duration_ms": s.duration_ms,
                "status": s.status,
                "error_type": s.error_type,
                "metadata_": sanitize_export_metadata(s.metadata_ or {}),
            }
            for s in sorted_spans
        ]

        return TraceExportResponse(
            trace_id=trace.trace_id,
            request_id=trace.request_id,
            organization_id=trace.organization_id,
            workspace_id=trace.workspace_id,
            actor_user_id=trace.actor_user_id,
            conversation_id=trace.conversation_id,
            operation_type=trace.operation_type,
            status=trace.status,
            started_at=trace.started_at,
            completed_at=trace.completed_at,
            total_latency_ms=trace.total_latency_ms,
            error_type=trace.error_type,
            error_code=trace.error_code,
            retrieval_mode=trace.retrieval_mode,
            grounded=trace.grounded,
            result_count=trace.result_count,
            metadata=clean_trace_meta,
            spans=spans_export,
            diagnostics=diag,
        )
