"""Operator API endpoints for platform operational alerts, lifecycle actions, and manual evaluation."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_workspace_context
from app.core.workspace_context import WorkspaceContext
from app.db.database import get_db
from app.db.models import OrganizationRole, Workspace
from app.schemas.alert import (
    AlertEvaluationRequest,
    AlertEvaluationResponse,
    AlertResolveRequest,
    PlatformAlertDetailResponse,
    PlatformAlertListResponse,
    PlatformAlertSummaryResponse,
)
from app.services.alerting.alert_service import AlertService
from app.services.alerting.evaluation_service import AlertEvaluationService

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("", response_model=PlatformAlertListResponse)
def list_alerts(
    workspace_id: UUID | None = Query(None, description="Optional workspace filter"),
    alert_type: str | None = Query(None, description="Filter by alert type"),
    severity: str | None = Query(None, description="Filter by severity (INFO, WARNING, ERROR, CRITICAL)"),
    status_filter: str | None = Query(None, alias="status", description="Filter by status (OPEN, ACKNOWLEDGED, RESOLVED, SUPPRESSED)"),
    from_time: datetime | None = Query(None, description="Filter from timestamp (ISO)"),
    to_time: datetime | None = Query(None, description="Filter to timestamp (ISO)"),
    limit: int = Query(50, ge=1, le=100, description="Items limit"),
    offset: int = Query(0, ge=0, description="Items offset"),
    ws_ctx: WorkspaceContext = Depends(get_current_workspace_context),
    db: Session = Depends(get_db),
) -> PlatformAlertListResponse:
    """List platform operational alerts with tenant scoping and role-based filtering."""
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
                detail="Permission denied: Workspace Admin cannot view alerts of other workspaces",
            )

    items, total = AlertService.list_alerts(
        db,
        ws_ctx,
        workspace_id=workspace_id,
        alert_type=alert_type,
        severity=severity,
        status_filter=status_filter,
        from_time=from_time,
        to_time=to_time,
        limit=limit,
        offset=offset,
    )

    summaries = [
        PlatformAlertSummaryResponse(
            id=item.id,
            organization_id=item.organization_id,
            workspace_id=item.workspace_id,
            alert_type=item.alert_type,
            severity=item.severity,
            status=item.status,
            title=item.title,
            description=item.description,
            metric_name=item.metric_name,
            metric_value=item.metric_value,
            threshold_value=item.threshold_value,
            detected_at=item.detected_at,
            acknowledged_at=item.acknowledged_at,
            resolved_at=item.resolved_at,
            acknowledged_by=item.acknowledged_by,
            resolved_by=item.resolved_by,
            resolution_reason=item.resolution_reason,
            deduplication_key=item.deduplication_key,
            created_at=item.created_at,
            updated_at=item.updated_at,
        )
        for item in items
    ]

    return PlatformAlertListResponse(
        items=summaries,
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("/evaluate", response_model=AlertEvaluationResponse)
def evaluate_alerts(
    payload: AlertEvaluationRequest | None = None,
    ws_ctx: WorkspaceContext = Depends(get_current_workspace_context),
    db: Session = Depends(get_db),
) -> AlertEvaluationResponse:
    """Manually trigger alert rule and anomaly evaluation for caller's authorized tenant context."""
    ws_id = payload.workspace_id if payload else None
    if ws_id is not None:
        target_ws = db.get(Workspace, ws_id)
        if target_ws is None or target_ws.organization_id != ws_ctx.organization_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied to requested workspace",
            )
        if (
            ws_ctx.organization_role not in (OrganizationRole.OWNER, OrganizationRole.ADMIN)
            and ws_id != ws_ctx.workspace_id
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Permission denied: Workspace Admin cannot evaluate alerts of other workspaces",
            )

    return AlertEvaluationService.evaluate(
        db,
        ws_ctx,
        workspace_id=ws_id,
    )


@router.get("/{alert_id}", response_model=PlatformAlertDetailResponse)
def get_alert_detail(
    alert_id: UUID,
    ws_ctx: WorkspaceContext = Depends(get_current_workspace_context),
    db: Session = Depends(get_db),
) -> PlatformAlertDetailResponse:
    """Get operational alert detail and associated deterministic self-diagnostics."""
    return AlertService.get_alert_detail(db, ws_ctx, alert_id)


@router.post("/{alert_id}/acknowledge", response_model=PlatformAlertSummaryResponse)
def acknowledge_alert(
    alert_id: UUID,
    ws_ctx: WorkspaceContext = Depends(get_current_workspace_context),
    db: Session = Depends(get_db),
) -> PlatformAlertSummaryResponse:
    """Acknowledge an operational alert."""
    alert = AlertService.acknowledge_alert(db, ws_ctx, alert_id)
    return PlatformAlertSummaryResponse.model_validate(alert)


@router.post("/{alert_id}/resolve", response_model=PlatformAlertSummaryResponse)
def resolve_alert(
    alert_id: UUID,
    payload: AlertResolveRequest | None = None,
    ws_ctx: WorkspaceContext = Depends(get_current_workspace_context),
    db: Session = Depends(get_db),
) -> PlatformAlertSummaryResponse:
    """Resolve an operational alert with optional resolution justification."""
    reason = payload.resolution_reason if payload else None
    alert = AlertService.resolve_alert(db, ws_ctx, alert_id, resolution_reason=reason)
    return PlatformAlertSummaryResponse.model_validate(alert)
