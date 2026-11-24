"""Trace query and retrieval service with tenant isolation and RBAC."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session, selectinload

from app.core.logging import get_logger
from app.core.workspace_context import WorkspaceContext
from app.db.models import OrganizationRole, QueryTrace, QueryTraceSpan, WorkspaceRole

logger = get_logger(__name__)


class TraceService:
    """Provides filtered, role-authorized querying of platform query traces."""

    @staticmethod
    def _verify_trace_access(
        context: WorkspaceContext,
        target_workspace_id: UUID | None = None,
    ) -> None:
        """Enforce role permissions for trace retrieval."""
        # Viewer and Contributor have no trace access
        is_org_admin = context.organization_role in {OrganizationRole.OWNER, OrganizationRole.ADMIN}
        is_ws_admin = context.workspace_role == WorkspaceRole.WORKSPACE_ADMIN

        if not is_org_admin and not is_ws_admin:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Trace inspection requires Workspace Admin or Organization Admin privileges.",
            )

        # If user is only Workspace Admin, they can only access their authorized workspace
        if not is_org_admin and is_ws_admin:
            if target_workspace_id is not None and target_workspace_id != context.workspace_id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Workspace Admin is restricted to traces in their active workspace.",
                )

    @classmethod
    def list_traces(
        cls,
        session: Session,
        context: WorkspaceContext,
        *,
        workspace_id: UUID | None = None,
        status_filter: str | None = None,
        operation_type: str | None = None,
        from_time: datetime | None = None,
        to_time: datetime | None = None,
        min_latency_ms: float | None = None,
        request_id: str | None = None,
        actor_user_id: UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[QueryTrace], int]:
        """List traces scoped to tenant and role permissions."""
        effective_ws_id = workspace_id or (
            context.workspace_id if context.organization_role not in {OrganizationRole.OWNER, OrganizationRole.ADMIN} else None
        )
        cls._verify_trace_access(context, target_workspace_id=effective_ws_id)

        # Base filter: strictly scoped to organization
        base_query: Select = select(QueryTrace).where(
            QueryTrace.organization_id == context.organization_id
        )

        if effective_ws_id is not None:
            base_query = base_query.where(QueryTrace.workspace_id == effective_ws_id)

        if status_filter:
            base_query = base_query.where(QueryTrace.status == status_filter.upper())

        if operation_type:
            base_query = base_query.where(QueryTrace.operation_type == operation_type.upper())

        if from_time is not None:
            base_query = base_query.where(QueryTrace.started_at >= from_time)

        if to_time is not None:
            base_query = base_query.where(QueryTrace.started_at <= to_time)

        if min_latency_ms is not None:
            base_query = base_query.where(QueryTrace.total_latency_ms >= min_latency_ms)

        if request_id:
            base_query = base_query.where(QueryTrace.request_id == request_id)

        if actor_user_id:
            base_query = base_query.where(QueryTrace.actor_user_id == actor_user_id)

        # Count query
        count_stmt = select(func.count()).select_from(base_query.subquery())
        total_count = session.scalar(count_stmt) or 0

        # Items query with deterministic ordering
        stmt = (
            base_query.options(selectinload(QueryTrace.spans))
            .order_by(QueryTrace.started_at.desc(), QueryTrace.id.desc())
            .limit(min(max(1, limit), 100))
            .offset(max(0, offset))
        )

        items = list(session.scalars(stmt).all())
        return items, total_count

    @classmethod
    def get_trace_by_id(
        cls,
        session: Session,
        context: WorkspaceContext,
        trace_id: str,
    ) -> QueryTrace:
        """Fetch full trace details including all spans."""
        cls._verify_trace_access(context)

        stmt = (
            select(QueryTrace)
            .where(
                QueryTrace.organization_id == context.organization_id,
                QueryTrace.trace_id == trace_id,
            )
            .options(
                selectinload(QueryTrace.spans.and_(QueryTraceSpan.trace_id == trace_id))
            )
        )

        # If user is only Workspace Admin, restrict to their workspace
        is_org_admin = context.organization_role in {OrganizationRole.OWNER, OrganizationRole.ADMIN}
        if not is_org_admin and context.workspace_role == WorkspaceRole.WORKSPACE_ADMIN:
            stmt = stmt.where(QueryTrace.workspace_id == context.workspace_id)

        trace = session.scalars(stmt).first()
        if trace is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Trace not found.",
            )

        return trace
