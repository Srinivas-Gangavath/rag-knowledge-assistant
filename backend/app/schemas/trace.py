"""Pydantic schemas for Platform Observability & Query Tracing APIs.

Covers Phase 1.6 & Phase 1.7:
- Raw query traces and spans
- Trace analytics & percentiles (p50, p95, p99)
- Stage latency breakdowns
- Slow query diagnostics and bottleneck classifications
- AI provider & streaming analytics
- Privacy-safe diagnostic trace export
- Trace retention preview and execution
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class QueryTraceSpanResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    trace_id: str
    parent_span_id: UUID | None = None
    span_name: str
    span_type: str
    started_at: datetime
    completed_at: datetime | None = None
    duration_ms: float | None = None
    status: str
    error_type: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")


class QueryTraceSummaryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    trace_id: str
    request_id: str
    organization_id: UUID
    workspace_id: UUID | None = None
    actor_user_id: UUID | None = None
    conversation_id: UUID | None = None
    operation_type: str
    status: str
    started_at: datetime
    completed_at: datetime | None = None
    total_latency_ms: float | None = None
    error_type: str | None = None
    error_code: str | None = None
    retrieval_mode: str | None = None
    grounded: bool | None = None
    result_count: int | None = None
    span_count: int = 0


class QueryTraceDetailResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    trace_id: str
    request_id: str
    organization_id: UUID
    workspace_id: UUID | None = None
    actor_user_id: UUID | None = None
    conversation_id: UUID | None = None
    operation_type: str
    status: str
    started_at: datetime
    completed_at: datetime | None = None
    total_latency_ms: float | None = None
    error_type: str | None = None
    error_code: str | None = None
    retrieval_mode: str | None = None
    grounded: bool | None = None
    result_count: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="metadata_")
    spans: list[QueryTraceSpanResponse] = Field(default_factory=list)


class QueryTraceListResponse(BaseModel):
    items: list[QueryTraceSummaryResponse]
    total: int
    limit: int
    offset: int


# =========================================================================
# Phase 1.7 Performance Analytics & Diagnostics Schemas
# =========================================================================

class StageLatencyStats(BaseModel):
    stage: str
    count: int
    average_ms: float
    p50_ms: float
    p95_ms: float
    p99_ms: float
    max_ms: float
    percentage_of_total: float = 0.0


class TraceAnalyticsOverview(BaseModel):
    request_count: int
    successful_count: int
    error_count: int
    cancelled_count: int
    partial_count: int
    error_rate: float
    average_latency_ms: float
    p50_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float


class SlowQuerySummary(BaseModel):
    slow_count: int
    very_slow_count: int
    slow_rate: float
    threshold_ms: float


class ErrorAnalytics(BaseModel):
    total_errors: int
    error_rate: float
    errors_by_category: dict[str, int] = Field(default_factory=dict)
    errors_by_operation: dict[str, int] = Field(default_factory=dict)
    top_failing_stages: list[dict[str, Any]] = Field(default_factory=list)


class ProviderModelStats(BaseModel):
    provider: str
    model: str
    request_count: int
    error_count: int
    average_latency_ms: float
    p95_latency_ms: float
    input_token_count: int = 0
    output_token_count: int = 0
    total_token_count: int = 0
    token_usage_available: bool = True


class StreamingAnalytics(BaseModel):
    stream_count: int
    success_rate: float
    cancellation_rate: float
    partial_rate: float
    provider_error_rate: float
    average_ttft_ms: float | None = None
    p50_ttft_ms: float | None = None
    p95_ttft_ms: float | None = None
    p99_ttft_ms: float | None = None
    average_stream_duration_ms: float | None = None


class TraceAnalyticsResponse(BaseModel):
    overview: TraceAnalyticsOverview
    stages: list[StageLatencyStats] = Field(default_factory=list)
    slow_queries: SlowQuerySummary
    errors: ErrorAnalytics
    providers: list[ProviderModelStats] = Field(default_factory=list)
    streaming: StreamingAnalytics


class SlowTraceItemResponse(BaseModel):
    trace_id: str
    request_id: str
    organization_id: UUID
    workspace_id: UUID | None = None
    started_at: datetime
    total_latency_ms: float
    status: str
    operation_type: str
    retrieval_mode: str | None = None
    slow_classification: str  # FAST, NORMAL, SLOW, VERY_SLOW
    dominant_stage: str | None = None
    dominant_stage_duration_ms: float | None = None
    dominant_stage_percentage: float | None = None
    is_retrieval_dominant: bool = False
    is_generation_dominant: bool = False


class SlowTraceListResponse(BaseModel):
    items: list[SlowTraceItemResponse]
    total: int
    limit: int
    offset: int


class TraceExportDiagnostics(BaseModel):
    slow_classification: str
    dominant_stage: str | None = None
    dominant_stage_duration_ms: float | None = None
    dominant_stage_percentage: float | None = None
    stage_durations_ms: dict[str, float] = Field(default_factory=dict)
    stage_percentages: dict[str, float] = Field(default_factory=dict)
    is_retrieval_dominant: bool = False
    is_generation_dominant: bool = False


class TraceExportResponse(BaseModel):
    trace_id: str
    request_id: str
    organization_id: UUID
    workspace_id: UUID | None = None
    actor_user_id: UUID | None = None
    conversation_id: UUID | None = None
    operation_type: str
    status: str
    started_at: datetime
    completed_at: datetime | None = None
    total_latency_ms: float | None = None
    error_type: str | None = None
    error_code: str | None = None
    retrieval_mode: str | None = None
    grounded: bool | None = None
    result_count: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    spans: list[QueryTraceSpanResponse] = Field(default_factory=list)
    diagnostics: TraceExportDiagnostics


# =========================================================================
# Retention Schemas
# =========================================================================

class TraceRetentionPreviewResponse(BaseModel):
    cutoff: datetime
    eligible_trace_count: int
    eligible_span_count: int
    oldest_trace_timestamp: datetime | None = None
    newest_eligible_timestamp: datetime | None = None


class TraceRetentionCleanupRequest(BaseModel):
    days: int | None = Field(None, ge=1, le=3650, description="Override retention days threshold")
    dry_run: bool = Field(False, description="Dry run mode (preview without deletion)")


class TraceRetentionCleanupResponse(BaseModel):
    cutoff: datetime
    deleted_traces_count: int
    deleted_spans_count: int
    dry_run: bool
