"""Audit logs API endpoints."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_workspace_context
from app.core.permissions import Permission
from app.core.workspace_context import WorkspaceContext
from app.db.database import get_db
from app.db.models import OrganizationRole
from app.schemas.audit import AuditLogItem, AuditLogListResponse, AuditLogVerifyResponse
from app.services.audit_service import AuditLogService

router = APIRouter(prefix="/audit-logs", tags=["audit-logs"])


@router.get("", response_model=AuditLogListResponse)
def list_audit_logs(
    workspace_id: UUID | None = Query(None, description="Optional workspace filter"),
    event_type: str | None = Query(None, description="Filter by event type"),
    action: str | None = Query(None, description="Filter by action"),
    actor_user_id: UUID | None = Query(None, description="Filter by actor user ID"),
    resource_type: str | None = Query(None, description="Filter by resource type"),
    resource_id: str | None = Query(None, description="Filter by resource ID"),
    outcome: str | None = Query(None, description="Filter by outcome (SUCCESS, FAILURE, DENIED)"),
    from_date: datetime | None = Query(None, description="Filter from timestamp (ISO)"),
    to_date: datetime | None = Query(None, description="Filter to timestamp (ISO)"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=100, description="Page size limit"),
    ws_ctx: WorkspaceContext = Depends(get_current_workspace_context),
    db: Session = Depends(get_db),
) -> AuditLogListResponse:
    if not ws_ctx.can(Permission.AUDIT_LOG_READ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied: audit_log:read capability required",
        )

    # Validate workspace filter scope & tenant boundaries
    from app.db.models import Workspace

    effective_ws_id: UUID | None = None
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
                detail="Permission denied: Workspace Admin cannot view audit logs of other workspaces",
            )
        effective_ws_id = workspace_id
    else:
        if ws_ctx.organization_role not in (OrganizationRole.OWNER, OrganizationRole.ADMIN):
            effective_ws_id = ws_ctx.workspace_id
        else:
            effective_ws_id = None

    offset = (page - 1) * page_size
    items, total = AuditLogService.list_audit_logs(
        db,
        organization_id=ws_ctx.organization_id,
        workspace_id=effective_ws_id,
        event_type=event_type,
        action=action,
        actor_user_id=actor_user_id,
        resource_type=resource_type,
        resource_id=resource_id,
        outcome=outcome,
        from_date=from_date,
        to_date=to_date,
        limit=page_size,
        offset=offset,
    )

    return AuditLogListResponse(
        items=[AuditLogItem.model_validate(item) for item in items],
        total=total,
        page=page,
        page_size=page_size,
        has_more=(offset + len(items)) < total,
    )


@router.get("/verify", response_model=AuditLogVerifyResponse)
def verify_audit_logs(
    ws_ctx: WorkspaceContext = Depends(get_current_workspace_context),
    db: Session = Depends(get_db),
) -> AuditLogVerifyResponse:
    # Organization-wide audit chain verification requires Organization Owner or Organization Admin
    if ws_ctx.organization_role not in (OrganizationRole.OWNER, OrganizationRole.ADMIN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permission denied: Organization Owner or Organization Admin authority required to verify organization audit chain",
        )

    is_valid, error_detail, count = AuditLogService.verify_chain(
        db,
        organization_id=ws_ctx.organization_id,
    )

    if not is_valid:
        return AuditLogVerifyResponse(
            is_valid=False,
            events_verified=count,
            message="Audit chain verification failed",
            error_detail=error_detail,
        )

    return AuditLogVerifyResponse(
        is_valid=True,
        events_verified=count,
        message="Audit log hash chain verified successfully",
        error_detail=None,
    )
