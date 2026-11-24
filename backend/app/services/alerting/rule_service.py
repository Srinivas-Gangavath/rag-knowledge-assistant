"""Alert Rule Management Service with role-based validation and tenant isolation."""

from __future__ import annotations

import math
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.core.permissions import Permission
from app.core.workspace_context import WorkspaceContext
from app.db.models import AlertOperator, AlertRule, OrganizationRole, Workspace, WorkspaceRole
from app.schemas.alert import AlertRuleCreateRequest, AlertRuleUpdateRequest


class AlertRuleService:
    """Provides validated, tenant-isolated alert rule management."""

    @staticmethod
    def _verify_rule_read_access(context: WorkspaceContext) -> None:
        """Verify the caller has authority to inspect alert rules."""
        is_org_admin = context.organization_role in {OrganizationRole.OWNER, OrganizationRole.ADMIN}
        is_ws_admin = context.workspace_role == WorkspaceRole.WORKSPACE_ADMIN

        if not is_org_admin and not is_ws_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Alert rule inspection requires Workspace Admin or Organization Admin privileges.",
            )

    @staticmethod
    def _verify_rule_manage_access(context: WorkspaceContext) -> None:
        """Verify the caller has authority to modify alert rules."""
        is_org_admin = context.organization_role in {OrganizationRole.OWNER, OrganizationRole.ADMIN}
        is_ws_admin = context.workspace_role == WorkspaceRole.WORKSPACE_ADMIN

        if not is_org_admin and not is_ws_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Alert rule management requires Workspace Admin or Organization Admin privileges.",
            )

    @classmethod
    def list_rules(
        cls,
        session: Session,
        context: WorkspaceContext,
        *,
        workspace_id: UUID | None = None,
        enabled_only: bool = False,
    ) -> list[AlertRule]:
        """List alert rules visible to caller within their organization."""
        cls._verify_rule_read_access(context)

        is_org_admin = context.organization_role in {OrganizationRole.OWNER, OrganizationRole.ADMIN}

        stmt: Select[tuple[AlertRule]] = select(AlertRule).where(
            AlertRule.organization_id == context.organization_id
        )

        if not is_org_admin:
            # Workspace Admin can only view rules for their authorized workspace, plus org-wide defaults
            stmt = stmt.where(
                (AlertRule.workspace_id == context.workspace_id) | (AlertRule.workspace_id.is_(None))
            )
        elif workspace_id is not None:
            # Org Admin filtering by specific workspace
            target_ws = session.get(Workspace, workspace_id)
            if target_ws is None or target_ws.organization_id != context.organization_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Requested workspace does not belong to your organization.",
                )
            stmt = stmt.where(
                (AlertRule.workspace_id == workspace_id) | (AlertRule.workspace_id.is_(None))
            )

        if enabled_only:
            stmt = stmt.where(AlertRule.enabled.is_(True))

        stmt = stmt.order_by(AlertRule.created_at.desc())
        return list(session.scalars(stmt).all())

    @classmethod
    def get_rule(
        cls,
        session: Session,
        context: WorkspaceContext,
        rule_id: UUID,
    ) -> AlertRule:
        """Retrieve a specific alert rule after verifying tenant and role access."""
        cls._verify_rule_read_access(context)

        rule = session.get(AlertRule, rule_id)
        if rule is None or rule.organization_id != context.organization_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Alert rule not found.",
            )

        is_org_admin = context.organization_role in {OrganizationRole.OWNER, OrganizationRole.ADMIN}
        if not is_org_admin and rule.workspace_id is not None and rule.workspace_id != context.workspace_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Workspace Admin cannot access alert rules for another workspace.",
            )

        return rule

    @classmethod
    def create_rule(
        cls,
        session: Session,
        context: WorkspaceContext,
        payload: AlertRuleCreateRequest,
    ) -> AlertRule:
        """Create a new alert rule with strict tenant and scope validation."""
        cls._verify_rule_manage_access(context)

        is_org_admin = context.organization_role in {OrganizationRole.OWNER, OrganizationRole.ADMIN}

        # Validate threshold
        if math.isnan(payload.threshold) or math.isinf(payload.threshold):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Threshold must be a valid finite number.",
            )

        # Scoping validation
        target_ws_id = payload.workspace_id
        if not is_org_admin:
            # Workspace Admin MUST create workspace-scoped rule for their active workspace ONLY
            if target_ws_id is None:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Workspace Admin cannot create organization-wide alert rules.",
                )
            if target_ws_id != context.workspace_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Workspace Admin can only create rules for their authorized workspace.",
                )
        else:
            # Org admin can create org-level (target_ws_id=None) or workspace-scoped
            if target_ws_id is not None:
                target_ws = session.get(Workspace, target_ws_id)
                if target_ws is None or target_ws.organization_id != context.organization_id:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Target workspace does not belong to your organization.",
                    )

        rule = AlertRule(
            organization_id=context.organization_id,
            workspace_id=target_ws_id,
            rule_type=payload.rule_type,
            metric_name=payload.metric_name,
            operator=payload.operator.value if hasattr(payload.operator, "value") else str(payload.operator),
            threshold=float(payload.threshold),
            window_minutes=payload.window_minutes,
            minimum_sample_size=payload.minimum_sample_size,
            severity=payload.severity.value if hasattr(payload.severity, "value") else str(payload.severity),
            enabled=payload.enabled,
            cooldown_minutes=payload.cooldown_minutes,
            created_by=context.user_id,
        )

        session.add(rule)
        session.commit()
        session.refresh(rule)
        return rule

    @classmethod
    def update_rule(
        cls,
        session: Session,
        context: WorkspaceContext,
        rule_id: UUID,
        payload: AlertRuleUpdateRequest,
    ) -> AlertRule:
        """Update an existing alert rule with tenant boundary checks."""
        cls._verify_rule_manage_access(context)

        rule = session.get(AlertRule, rule_id)
        if rule is None or rule.organization_id != context.organization_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Alert rule not found.",
            )

        is_org_admin = context.organization_role in {OrganizationRole.OWNER, OrganizationRole.ADMIN}

        # Workspace Admin cannot edit organization-wide rules or other workspaces' rules
        if not is_org_admin:
            if rule.workspace_id is None:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Workspace Admin cannot modify organization-wide alert rules.",
                )
            if rule.workspace_id != context.workspace_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Workspace Admin cannot modify alert rules of another workspace.",
                )

        if payload.threshold is not None:
            if math.isnan(payload.threshold) or math.isinf(payload.threshold):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Threshold must be a valid finite number.",
                )
            rule.threshold = float(payload.threshold)

        if payload.rule_type is not None:
            rule.rule_type = payload.rule_type
        if payload.metric_name is not None:
            rule.metric_name = payload.metric_name
        if payload.operator is not None:
            rule.operator = payload.operator.value if hasattr(payload.operator, "value") else str(payload.operator)
        if payload.window_minutes is not None:
            rule.window_minutes = payload.window_minutes
        if payload.minimum_sample_size is not None:
            rule.minimum_sample_size = payload.minimum_sample_size
        if payload.severity is not None:
            rule.severity = payload.severity.value if hasattr(payload.severity, "value") else str(payload.severity)
        if payload.enabled is not None:
            rule.enabled = payload.enabled
        if payload.cooldown_minutes is not None:
            rule.cooldown_minutes = payload.cooldown_minutes

        session.commit()
        session.refresh(rule)
        return rule

    @classmethod
    def delete_rule(
        cls,
        session: Session,
        context: WorkspaceContext,
        rule_id: UUID,
    ) -> None:
        """Delete an alert rule with authorization verification."""
        cls._verify_rule_manage_access(context)

        rule = session.get(AlertRule, rule_id)
        if rule is None or rule.organization_id != context.organization_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Alert rule not found.",
            )

        is_org_admin = context.organization_role in {OrganizationRole.OWNER, OrganizationRole.ADMIN}

        if not is_org_admin:
            if rule.workspace_id is None:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Workspace Admin cannot delete organization-wide alert rules.",
                )
            if rule.workspace_id != context.workspace_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Workspace Admin cannot delete alert rules of another workspace.",
                )

        session.delete(rule)
        session.commit()
