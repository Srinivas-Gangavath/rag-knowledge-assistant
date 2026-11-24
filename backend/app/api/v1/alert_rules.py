"""Operator API endpoints for managing alert rules."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_workspace_context
from app.core.workspace_context import WorkspaceContext
from app.db.database import get_db
from app.schemas.alert import (
    AlertRuleCreateRequest,
    AlertRuleListResponse,
    AlertRuleResponse,
    AlertRuleUpdateRequest,
)
from app.services.alerting.rule_service import AlertRuleService

router = APIRouter(prefix="/alert-rules", tags=["alert-rules"])


@router.get("", response_model=AlertRuleListResponse)
def list_rules(
    workspace_id: UUID | None = Query(None, description="Optional workspace filter"),
    enabled_only: bool = Query(False, description="Filter for enabled rules only"),
    ws_ctx: WorkspaceContext = Depends(get_current_workspace_context),
    db: Session = Depends(get_db),
) -> AlertRuleListResponse:
    """List alert rules visible to caller."""
    rules = AlertRuleService.list_rules(
        db,
        ws_ctx,
        workspace_id=workspace_id,
        enabled_only=enabled_only,
    )
    return AlertRuleListResponse(
        items=[AlertRuleResponse.model_validate(r) for r in rules],
        total=len(rules),
    )


@router.post("", response_model=AlertRuleResponse, status_code=status.HTTP_201_CREATED)
def create_rule(
    payload: AlertRuleCreateRequest,
    ws_ctx: WorkspaceContext = Depends(get_current_workspace_context),
    db: Session = Depends(get_db),
) -> AlertRuleResponse:
    """Create a new alert rule with role scoping and parameter validation."""
    rule = AlertRuleService.create_rule(db, ws_ctx, payload)
    return AlertRuleResponse.model_validate(rule)


@router.get("/{rule_id}", response_model=AlertRuleResponse)
def get_rule(
    rule_id: UUID,
    ws_ctx: WorkspaceContext = Depends(get_current_workspace_context),
    db: Session = Depends(get_db),
) -> AlertRuleResponse:
    """Get details of a specific alert rule."""
    rule = AlertRuleService.get_rule(db, ws_ctx, rule_id)
    return AlertRuleResponse.model_validate(rule)


@router.patch("/{rule_id}", response_model=AlertRuleResponse)
def update_rule(
    rule_id: UUID,
    payload: AlertRuleUpdateRequest,
    ws_ctx: WorkspaceContext = Depends(get_current_workspace_context),
    db: Session = Depends(get_db),
) -> AlertRuleResponse:
    """Update configuration of an existing alert rule."""
    rule = AlertRuleService.update_rule(db, ws_ctx, rule_id, payload)
    return AlertRuleResponse.model_validate(rule)


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_rule(
    rule_id: UUID,
    ws_ctx: WorkspaceContext = Depends(get_current_workspace_context),
    db: Session = Depends(get_db),
) -> Response:
    """Delete an alert rule with authorization verification."""
    AlertRuleService.delete_rule(db, ws_ctx, rule_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

