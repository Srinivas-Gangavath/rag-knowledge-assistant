"""Trace Retention Service for safe lifecycle management of QueryTrace records.

Enforces:
- Organization-scoped retention policy execution
- Cascade deletion of spans with their parent trace
- Non-interference with immutable AuditLog records
- Preview / dry-run capabilities
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.workspace_context import WorkspaceContext
from app.db.models import (
    AuditEventType,
    AuditOutcome,
    OrganizationRole,
    QueryTrace,
    QueryTraceSpan,
)
from app.schemas.trace import (
    TraceRetentionCleanupResponse,
    TraceRetentionPreviewResponse,
)
from app.services.audit_service import AuditLogService

logger = get_logger(__name__)


class TraceRetentionService:
    """Provides preview and deletion capabilities for expired query traces."""

    @staticmethod
    def _verify_retention_access(context: WorkspaceContext) -> None:
        """Enforce that only Organization Owner or Admin can manage trace retention."""
        if context.organization_role not in {OrganizationRole.OWNER, OrganizationRole.ADMIN}:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Retention management requires Organization Owner or Admin privileges.",
            )

    @classmethod
    def preview_expired_traces(
        cls,
        session: Session,
        context: WorkspaceContext,
        *,
        days: int | None = None,
        cutoff: datetime | None = None,
    ) -> TraceRetentionPreviewResponse:
        """Calculate eligible trace and span counts for retention cleanup without deleting."""
        cls._verify_retention_access(context)
        settings = get_settings()

        effective_days = days if days is not None else settings.trace_retention_days
        effective_cutoff = cutoff or (datetime.now(timezone.utc) - timedelta(days=effective_days))

        # Base trace filter
        trace_match = (
            (QueryTrace.organization_id == context.organization_id)
            & (QueryTrace.started_at < effective_cutoff)
        )

        # Count eligible traces
        trace_count = session.scalar(
            select(func.count(QueryTrace.id)).where(trace_match)
        ) or 0

        # Count eligible spans (via subquery matching trace_id)
        subquery_trace_ids = select(QueryTrace.trace_id).where(trace_match)
        span_count = session.scalar(
            select(func.count(QueryTraceSpan.id)).where(QueryTraceSpan.trace_id.in_(subquery_trace_ids))
        ) or 0

        # Oldest trace in organization
        oldest_ts = session.scalar(
            select(func.min(QueryTrace.started_at)).where(
                QueryTrace.organization_id == context.organization_id
            )
        )

        # Newest eligible trace timestamp
        newest_eligible_ts = session.scalar(
            select(func.max(QueryTrace.started_at)).where(trace_match)
        )

        return TraceRetentionPreviewResponse(
            cutoff=effective_cutoff,
            eligible_trace_count=trace_count,
            eligible_span_count=span_count,
            oldest_trace_timestamp=oldest_ts,
            newest_eligible_timestamp=newest_eligible_ts,
        )

    @classmethod
    def delete_expired_traces(
        cls,
        session: Session,
        context: WorkspaceContext,
        *,
        days: int | None = None,
        cutoff: datetime | None = None,
        dry_run: bool = False,
    ) -> TraceRetentionCleanupResponse:
        """Execute deletion of expired QueryTrace records for the organization."""
        cls._verify_retention_access(context)
        settings = get_settings()

        effective_days = days if days is not None else settings.trace_retention_days
        effective_cutoff = cutoff or (datetime.now(timezone.utc) - timedelta(days=effective_days))

        if dry_run:
            preview = cls.preview_expired_traces(session, context, days=days, cutoff=effective_cutoff)
            return TraceRetentionCleanupResponse(
                cutoff=effective_cutoff,
                deleted_traces_count=preview.eligible_trace_count,
                deleted_spans_count=preview.eligible_span_count,
                dry_run=True,
            )

        trace_match = (
            (QueryTrace.organization_id == context.organization_id)
            & (QueryTrace.started_at < effective_cutoff)
        )

        # Count spans before deletion for accurate reporting
        subquery_trace_ids = select(QueryTrace.trace_id).where(trace_match)
        span_count = session.scalar(
            select(func.count(QueryTraceSpan.id)).where(QueryTraceSpan.trace_id.in_(subquery_trace_ids))
        ) or 0

        try:
            with session.begin_nested():
                # Perform bulk deletion of eligible traces
                # QueryTraceSpan rows cascade delete automatically via ON DELETE CASCADE foreign key
                result = session.execute(
                    delete(QueryTrace).where(trace_match)
                )
                deleted_traces = result.rowcount or 0

                # Record immutable compliance audit event for destructive trace deletion
                AuditLogService.record_event(
                    session,
                    organization_id=context.organization_id,
                    workspace_id=context.workspace_id,
                    actor_user_id=context.user_id,
                    actor_email=None,
                    event_type=AuditEventType.TRACE_RETENTION_EXECUTED,
                    action="DELETE",
                    outcome=AuditOutcome.SUCCESS,
                    resource_type="QUERY_TRACE",
                    resource_id=None,
                    metadata={
                        "cutoff": effective_cutoff.isoformat(),
                        "retention_days": effective_days,
                        "deleted_traces_count": deleted_traces,
                        "deleted_spans_count": span_count,
                        "dry_run": False,
                    },
                )

            session.flush()
            logger.info(
                "TRACE RETENTION executed (org=%s cutoff=%s deleted_traces=%s deleted_spans=%s)",
                context.organization_id,
                effective_cutoff.isoformat(),
                deleted_traces,
                span_count,
            )
            return TraceRetentionCleanupResponse(
                cutoff=effective_cutoff,
                deleted_traces_count=deleted_traces,
                deleted_spans_count=span_count,
                dry_run=False,
            )
        except Exception as exc:
            logger.error("TRACE RETENTION failed: %s", exc, exc_info=True)
            raise
