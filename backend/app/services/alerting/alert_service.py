"""Operational Alert Query & Lifecycle Service with RBAC, Tenant Isolation, and Auditing."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.core.workspace_context import WorkspaceContext
from app.db.models import (
    AlertSeverity,
    AlertStatus,
    AuditEventType,
    AuditOutcome,
    OrganizationRole,
    PlatformAlert,
    Workspace,
    WorkspaceRole,
)
from app.schemas.alert import PlatformAlertDetailResponse, PlatformAlertSummaryResponse
from app.services.alerting.diagnostics_service import PlatformDiagnosticsService
from app.services.audit_service import AuditLogService

logger = get_logger(__name__)


class AlertService:
    """Provides filtered, role-authorized management of operational platform alerts."""

    @staticmethod
    def _verify_alert_access(
        context: WorkspaceContext,
        target_workspace_id: UUID | None = None,
    ) -> None:
        """Enforce role permissions for alert inspection."""
        is_org_admin = context.organization_role in {OrganizationRole.OWNER, OrganizationRole.ADMIN}
        is_ws_admin = context.workspace_role == WorkspaceRole.WORKSPACE_ADMIN

        if not is_org_admin and not is_ws_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Alert inspection requires Workspace Admin or Organization Admin privileges.",
            )

        if not is_org_admin and is_ws_admin:
            if target_workspace_id is not None and target_workspace_id != context.workspace_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Workspace Admin is restricted to alerts in their active workspace.",
                )

    @classmethod
    def list_alerts(
        cls,
        session: Session,
        context: WorkspaceContext,
        *,
        workspace_id: UUID | None = None,
        alert_type: str | None = None,
        severity: str | None = None,
        status_filter: str | None = None,
        from_time: datetime | None = None,
        to_time: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[PlatformAlert], int]:
        """List platform alerts scoped by tenant boundary and caller permissions."""
        cls._verify_alert_access(context, target_workspace_id=workspace_id)

        is_org_admin = context.organization_role in {OrganizationRole.OWNER, OrganizationRole.ADMIN}

        stmt: Select[tuple[PlatformAlert]] = select(PlatformAlert).where(
            PlatformAlert.organization_id == context.organization_id
        )

        if not is_org_admin:
            # Workspace Admin can ONLY view alerts explicitly scoped to their workspace
            stmt = stmt.where(PlatformAlert.workspace_id == context.workspace_id)
        elif workspace_id is not None:
            # Org admin querying specific workspace
            target_ws = session.get(Workspace, workspace_id)
            if target_ws is None or target_ws.organization_id != context.organization_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Access denied to requested workspace.",
                )
            stmt = stmt.where(PlatformAlert.workspace_id == workspace_id)

        if alert_type:
            stmt = stmt.where(PlatformAlert.alert_type == alert_type)
        if severity:
            stmt = stmt.where(PlatformAlert.severity == severity)
        if status_filter:
            stmt = stmt.where(PlatformAlert.status == status_filter)
        if from_time:
            stmt = stmt.where(PlatformAlert.detected_at >= from_time)
        if to_time:
            stmt = stmt.where(PlatformAlert.detected_at <= to_time)

        # Count total
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = session.scalar(count_stmt) or 0

        # Order and paginate
        stmt = stmt.order_by(PlatformAlert.detected_at.desc()).limit(limit).offset(offset)
        items = list(session.scalars(stmt).all())

        return items, total

    @classmethod
    def get_alert_detail(
        cls,
        session: Session,
        context: WorkspaceContext,
        alert_id: UUID,
    ) -> PlatformAlertDetailResponse:
        """Fetch alert detail with diagnostics and tenant authorization verification."""
        cls._verify_alert_access(context)

        alert = session.get(PlatformAlert, alert_id)
        if alert is None or alert.organization_id != context.organization_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Alert not found.",
            )

        is_org_admin = context.organization_role in {OrganizationRole.OWNER, OrganizationRole.ADMIN}
        if not is_org_admin and alert.workspace_id != context.workspace_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Workspace Admin cannot inspect alerts belonging to another workspace.",
            )

        # Produce self-diagnostics
        diagnostic = PlatformDiagnosticsService.diagnose_alert(alert)

        return PlatformAlertDetailResponse(
            id=alert.id,
            organization_id=alert.organization_id,
            workspace_id=alert.workspace_id,
            alert_type=alert.alert_type,
            severity=alert.severity,
            status=alert.status,
            title=alert.title,
            description=alert.description,
            metric_name=alert.metric_name,
            metric_value=alert.metric_value,
            threshold_value=alert.threshold_value,
            detected_at=alert.detected_at,
            acknowledged_at=alert.acknowledged_at,
            resolved_at=alert.resolved_at,
            acknowledged_by=alert.acknowledged_by,
            resolved_by=alert.resolved_by,
            resolution_reason=alert.resolution_reason,
            deduplication_key=alert.deduplication_key,
            created_at=alert.created_at,
            updated_at=alert.updated_at,
            metadata=alert.metadata_ or {},
            diagnostic=diagnostic,
        )

    @classmethod
    def acknowledge_alert(
        cls,
        session: Session,
        context: WorkspaceContext,
        alert_id: UUID,
    ) -> PlatformAlert:
        """Transition alert to ACKNOWLEDGED state and emit audit log."""
        cls._verify_alert_access(context)

        alert = session.get(PlatformAlert, alert_id)
        if alert is None or alert.organization_id != context.organization_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Alert not found.",
            )

        is_org_admin = context.organization_role in {OrganizationRole.OWNER, OrganizationRole.ADMIN}
        if not is_org_admin and alert.workspace_id != context.workspace_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Workspace Admin cannot acknowledge alerts belonging to another workspace.",
            )

        now = datetime.now(timezone.utc)
        alert.status = AlertStatus.ACKNOWLEDGED.value
        alert.acknowledged_at = now
        alert.acknowledged_by = context.user_id
        alert.updated_at = now

        # Record audit log
        safe_meta = {
            "alert_id": str(alert.id),
            "alert_type": alert.alert_type,
            "severity": alert.severity,
            "metric_name": alert.metric_name,
            "metric_value": alert.metric_value,
            "threshold_value": alert.threshold_value,
            "actor_user_id": str(context.user_id),
        }
        AuditLogService.record_event(
            session,
            organization_id=alert.organization_id,
            workspace_id=alert.workspace_id,
            actor_user_id=context.user_id,
            event_type=AuditEventType.ALERT_ACKNOWLEDGED,
            action="ALERT_ACKNOWLEDGED",
            outcome=AuditOutcome.SUCCESS,
            resource_type="platform_alert",
            resource_id=str(alert.id),
            metadata=safe_meta,
        )

        session.commit()
        session.refresh(alert)
        return alert

    @classmethod
    def resolve_alert(
        cls,
        session: Session,
        context: WorkspaceContext,
        alert_id: UUID,
        *,
        resolution_reason: str | None = None,
    ) -> PlatformAlert:
        """Transition alert to RESOLVED state with reason and emit audit log."""
        cls._verify_alert_access(context)

        alert = session.get(PlatformAlert, alert_id)
        if alert is None or alert.organization_id != context.organization_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Alert not found.",
            )

        is_org_admin = context.organization_role in {OrganizationRole.OWNER, OrganizationRole.ADMIN}
        if not is_org_admin and alert.workspace_id != context.workspace_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Workspace Admin cannot resolve alerts belonging to another workspace.",
            )

        now = datetime.now(timezone.utc)
        alert.status = AlertStatus.RESOLVED.value
        alert.resolved_at = now
        alert.resolved_by = context.user_id
        alert.resolution_reason = resolution_reason
        alert.updated_at = now

        # Record audit log
        safe_meta = {
            "alert_id": str(alert.id),
            "alert_type": alert.alert_type,
            "severity": alert.severity,
            "metric_name": alert.metric_name,
            "metric_value": alert.metric_value,
            "threshold_value": alert.threshold_value,
            "resolution_reason": resolution_reason,
            "actor_user_id": str(context.user_id),
        }
        AuditLogService.record_event(
            session,
            organization_id=alert.organization_id,
            workspace_id=alert.workspace_id,
            actor_user_id=context.user_id,
            event_type=AuditEventType.ALERT_RESOLVED,
            action="ALERT_RESOLVED",
            outcome=AuditOutcome.SUCCESS,
            resource_type="platform_alert",
            resource_id=str(alert.id),
            metadata=safe_meta,
        )

        session.commit()
        session.refresh(alert)
        return alert
