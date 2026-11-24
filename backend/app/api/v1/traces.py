"""Operator API endpoints for platform query traces, analytics, diagnostics, retention, and export."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_workspace_context
from app.core.workspace_context import WorkspaceContext
from app.db.database import get_db
from app.db.models import OrganizationRole, Workspace
from app.schemas.trace import (
    QueryTraceDetailResponse,
    QueryTraceListResponse,
    QueryTraceSpanResponse,
    QueryTraceSummaryResponse,
    SlowTraceListResponse,
    TraceAnalyticsResponse,
    TraceExportResponse,
    TraceRetentionCleanupRequest,
    TraceRetentionCleanupResponse,
    TraceRetentionPreviewResponse,
)
from app.services.tracing.analytics_service import TraceAnalyticsService
from app.services.tracing.retention_service import TraceRetentionService
from app.services.tracing.service import TraceService

router = APIRouter(prefix="/traces", tags=["traces"])


@router.get("", response_model=QueryTraceListResponse)
def list_traces(
    workspace_id: UUID | None = Query(None, description="Optional workspace filter"),
    status_filter: str | None = Query(None, alias="status", description="Filter by status (SUCCESS, ERROR, PARTIAL, CANCELLED)"),
    operation_type: str | None = Query(None, description="Filter by operation type (CHAT, EMBEDDING, etc.)"),
    from_time: datetime | None = Query(None, description="Filter from timestamp (ISO)"),
    to_time: datetime | None = Query(None, description="Filter to timestamp (ISO)"),
    min_latency_ms: float | None = Query(None, description="Filter by minimum total latency in ms"),
    request_id: str | None = Query(None, description="Filter by request ID"),
    actor_user_id: UUID | None = Query(None, description="Filter by actor user ID"),
    limit: int = Query(50, ge=1, le=100, description="Items limit"),
    offset: int = Query(0, ge=0, description="Items offset"),
    ws_ctx: WorkspaceContext = Depends(get_current_workspace_context),
    db: Session = Depends(get_db),
) -> QueryTraceListResponse:
    """List platform query traces with tenant scoping and role-based filtering."""
    if workspace_id is not None:
        target_ws = db.get(Workspace, workspace_id)
        if target_ws is None or target_ws.organization_id != ws_ctx.organization_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied to requested workspace",
            )
        if (
            ws_ctx.organization_role not in (OrganizationRole.OWNER, OrganizationRole.ADMIN)
            and workspace_id != ws_ctx.workspace_id
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Permission denied: Workspace Admin cannot view traces of other workspaces",
            )

    items, total = TraceService.list_traces(
        db,
        ws_ctx,
        workspace_id=workspace_id,
        status_filter=status_filter,
        operation_type=operation_type,
        from_time=from_time,
        to_time=to_time,
        min_latency_ms=min_latency_ms,
        request_id=request_id,
        actor_user_id=actor_user_id,
        limit=limit,
        offset=offset,
    )

    summaries: list[QueryTraceSummaryResponse] = []
    for item in items:
        summaries.append(
            QueryTraceSummaryResponse(
                id=item.id,
                trace_id=item.trace_id,
                request_id=item.request_id,
                organization_id=item.organization_id,
                workspace_id=item.workspace_id,
                actor_user_id=item.actor_user_id,
                conversation_id=item.conversation_id,
                operation_type=item.operation_type,
                status=item.status,
                started_at=item.started_at,
                completed_at=item.completed_at,
                total_latency_ms=item.total_latency_ms,
                error_type=item.error_type,
                error_code=item.error_code,
                retrieval_mode=item.retrieval_mode,
                grounded=item.grounded,
                result_count=item.result_count,
                span_count=len(item.spans) if item.spans else 0,
            )
        )

    return QueryTraceListResponse(
        items=summaries,
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/analytics", response_model=TraceAnalyticsResponse)
def get_trace_analytics(
    workspace_id: UUID | None = Query(None, description="Optional workspace filter"),
    from_time: datetime | None = Query(None, description="Filter from timestamp (ISO)"),
    to_time: datetime | None = Query(None, description="Filter to timestamp (ISO)"),
    operation_type: str | None = Query(None, description="Filter by operation type"),
    retrieval_mode: str | None = Query(None, description="Filter by retrieval mode"),
    ws_ctx: WorkspaceContext = Depends(get_current_workspace_context),
    db: Session = Depends(get_db),
) -> TraceAnalyticsResponse:
    """Retrieve aggregated latency statistics, percentiles, stage breakdowns, and error metrics."""
    if workspace_id is not None:
        target_ws = db.get(Workspace, workspace_id)
        if target_ws is None or target_ws.organization_id != ws_ctx.organization_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied to requested workspace",
            )
        if (
            ws_ctx.organization_role not in (OrganizationRole.OWNER, OrganizationRole.ADMIN)
            and workspace_id != ws_ctx.workspace_id
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Permission denied: Workspace Admin cannot view analytics of other workspaces",
            )

    return TraceAnalyticsService.get_analytics(
        db,
        ws_ctx,
        workspace_id=workspace_id,
        from_time=from_time,
        to_time=to_time,
        operation_type=operation_type,
        retrieval_mode=retrieval_mode,
    )


@router.get("/slow", response_model=SlowTraceListResponse)
def list_slow_traces(
    min_latency_ms: float | None = Query(None, description="Override minimum latency threshold in ms"),
    workspace_id: UUID | None = Query(None, description="Optional workspace filter"),
    from_time: datetime | None = Query(None, description="Filter from timestamp (ISO)"),
    to_time: datetime | None = Query(None, description="Filter to timestamp (ISO)"),
    limit: int = Query(50, ge=1, le=100, description="Items limit"),
    offset: int = Query(0, ge=0, description="Items offset"),
    ws_ctx: WorkspaceContext = Depends(get_current_workspace_context),
    db: Session = Depends(get_db),
) -> SlowTraceListResponse:
    """List slow query traces with dominant bottleneck classifications."""
    if workspace_id is not None:
        target_ws = db.get(Workspace, workspace_id)
        if target_ws is None or target_ws.organization_id != ws_ctx.organization_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied to requested workspace",
            )
        if (
            ws_ctx.organization_role not in (OrganizationRole.OWNER, OrganizationRole.ADMIN)
            and workspace_id != ws_ctx.workspace_id
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Permission denied: Workspace Admin cannot view slow queries of other workspaces",
            )

    return TraceAnalyticsService.list_slow_traces(
        db,
        ws_ctx,
        min_latency_ms=min_latency_ms,
        workspace_id=workspace_id,
        from_time=from_time,
        to_time=to_time,
        limit=limit,
        offset=offset,
    )


@router.get("/retention/preview", response_model=TraceRetentionPreviewResponse)
def preview_trace_retention(
    days: int | None = Query(None, ge=1, le=3650, description="Override retention days threshold"),
    ws_ctx: WorkspaceContext = Depends(get_current_workspace_context),
    db: Session = Depends(get_db),
) -> TraceRetentionPreviewResponse:
    """Preview expired trace and span counts eligible for cleanup under retention policy."""
    return TraceRetentionService.preview_expired_traces(db, ws_ctx, days=days)


@router.post("/retention/cleanup", response_model=TraceRetentionCleanupResponse)
def cleanup_trace_retention(
    payload: TraceRetentionCleanupRequest | None = None,
    ws_ctx: WorkspaceContext = Depends(get_current_workspace_context),
    db: Session = Depends(get_db),
) -> TraceRetentionCleanupResponse:
    """Execute retention cleanup of expired query traces (Org Admin only)."""
    days = payload.days if payload else None
    dry_run = payload.dry_run if payload else False
    return TraceRetentionService.delete_expired_traces(db, ws_ctx, days=days, dry_run=dry_run)


@router.get("/{trace_id}/export", response_model=TraceExportResponse)
def export_trace_detail(
    trace_id: str,
    ws_ctx: WorkspaceContext = Depends(get_current_workspace_context),
    db: Session = Depends(get_db),
) -> TraceExportResponse:
    """Export sanitized diagnostic trace data with stage and bottleneck breakdown."""
    return TraceAnalyticsService.export_trace(db, ws_ctx, trace_id=trace_id)


@router.get("/{trace_id}", response_model=QueryTraceDetailResponse)
def get_trace_detail(
    trace_id: str,
    ws_ctx: WorkspaceContext = Depends(get_current_workspace_context),
    db: Session = Depends(get_db),
) -> QueryTraceDetailResponse:
    """Retrieve detailed query trace and all chronological execution spans."""
    trace = TraceService.get_trace_by_id(db, ws_ctx, trace_id=trace_id)

    sorted_spans = sorted(trace.spans or [], key=lambda s: (s.started_at, str(s.id)))
    span_responses = [
        QueryTraceSpanResponse(
            id=s.id,
            trace_id=s.trace_id,
            parent_span_id=s.parent_span_id,
            span_name=s.span_name,
            span_type=s.span_type,
            started_at=s.started_at,
            completed_at=s.completed_at,
            duration_ms=s.duration_ms,
            status=s.status,
            error_type=s.error_type,
            metadata_=s.metadata_ or {},
        )
        for s in sorted_spans
    ]

    return QueryTraceDetailResponse(
        id=trace.id,
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
        metadata_=trace.metadata_ or {},
        spans=span_responses,
    )
