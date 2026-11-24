"""Enterprise Audit Logging & Compliance Service.

Provides:
- Centralized event logging with tenant scoping (organization_id, workspace_id)
- Deterministic SHA-256 hash chaining (previous_hash -> event_hash)
- Metadata sanitization (blocks passwords, tokens, full query text, document contents)
- Chain verification for tamper evidence
- Filtered audit log retrieval
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.db.models import AuditEventType, AuditLog, AuditOutcome

logger = get_logger(__name__)

# Keys that must NEVER be stored in audit metadata
SENSITIVE_KEYS = {
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
    "content",
    "chunk_content",
    "prompt",
    "response",
    "raw_response",
}


def sanitize_audit_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    """Recursively sanitize metadata by removing sensitive keys and secrets."""
    if not metadata:
        return {}

    sanitized: dict[str, Any] = {}
    for key, value in metadata.items():
        key_lower = str(key).lower()
        if any(sens in key_lower for sens in SENSITIVE_KEYS):
            continue

        if isinstance(value, dict):
            sanitized[key] = sanitize_audit_metadata(value)
        elif isinstance(value, (list, tuple, set)):
            clean_list = []
            for item in value:
                if isinstance(item, dict):
                    clean_list.append(sanitize_audit_metadata(item))
                elif not any(sens in str(item).lower() for sens in SENSITIVE_KEYS):
                    clean_list.append(str(item) if isinstance(item, UUID) else item)
            sanitized[key] = clean_list
        elif isinstance(value, UUID):
            sanitized[key] = str(value)
        elif isinstance(value, (str, int, float, bool)) or value is None:
            sanitized[key] = value
        else:
            sanitized[key] = str(value)

    return sanitized


def compute_canonical_payload(
    organization_id: UUID | str,
    workspace_id: UUID | str | None,
    actor_user_id: UUID | str | None,
    actor_email: str | None,
    event_type: str,
    action: str,
    outcome: str,
    resource_type: str | None,
    resource_id: str | None,
    clean_metadata: dict[str, Any],
    ip_address: str | None,
    user_agent: str | None,
    request_id: str | None,
    created_at: datetime,
    previous_hash: str | None,
) -> bytes:
    """Build the deterministic canonical JSON representation of an audit event."""
    canonical_dict = {
        "action": str(action),
        "actor_email_snapshot": str(actor_email) if actor_email else None,
        "actor_user_id": str(actor_user_id) if actor_user_id else None,
        "created_at": created_at.isoformat(),
        "event_type": str(event_type),
        "ip_address": str(ip_address) if ip_address else None,
        "metadata": clean_metadata,
        "organization_id": str(organization_id),
        "outcome": str(outcome),
        "previous_hash": previous_hash,
        "request_id": str(request_id) if request_id else None,
        "resource_id": str(resource_id) if resource_id else None,
        "resource_type": str(resource_type) if resource_type else None,
        "user_agent": str(user_agent) if user_agent else None,
        "workspace_id": str(workspace_id) if workspace_id else None,
    }
    return json.dumps(
        canonical_dict,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


class AuditLogService:
    @staticmethod
    def record_event(
        db: Session,
        *,
        organization_id: UUID,
        workspace_id: UUID | None = None,
        actor_user_id: UUID | None = None,
        actor_email: str | None = None,
        event_type: AuditEventType | str,
        action: str,
        outcome: AuditOutcome | str = AuditOutcome.SUCCESS,
        resource_type: str | None = None,
        resource_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        request_id: str | None = None,
        autocommit: bool = False,
    ) -> AuditLog:
        """Create and persist an immutable, tamper-evident audit log record."""
        # 1. Acquire transaction advisory lock for deterministic hash chaining in PostgreSQL
        try:
            db.execute(
                select(
                    func.pg_advisory_xact_lock(
                        func.hashtext(f"audit_stream_{organization_id}")
                    )
                )
            )
        except Exception:
            # Advisory lock is PostgreSQL specific; continue cleanly in mock/sqlite test engines
            pass

        # 2. Obtain previous event hash for this organization's audit stream
        last_event = db.scalars(
            select(AuditLog)
            .where(AuditLog.organization_id == organization_id)
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .limit(1)
        ).first()

        previous_hash = last_event.event_hash if last_event else None

        # 3. Canonical payload and hash generation
        created_at = datetime.now(timezone.utc)
        clean_metadata = sanitize_audit_metadata(metadata)

        canonical_bytes = compute_canonical_payload(
            organization_id=organization_id,
            workspace_id=workspace_id,
            actor_user_id=actor_user_id,
            actor_email=actor_email,
            event_type=str(event_type),
            action=action,
            outcome=str(outcome),
            resource_type=resource_type,
            resource_id=resource_id,
            clean_metadata=clean_metadata,
            ip_address=ip_address,
            user_agent=user_agent,
            request_id=request_id,
            created_at=created_at,
            previous_hash=previous_hash,
        )
        event_hash = hashlib.sha256(canonical_bytes).hexdigest()

        audit_log = AuditLog(
            id=uuid4(),
            organization_id=organization_id,
            workspace_id=workspace_id,
            actor_user_id=actor_user_id,
            actor_email_snapshot=actor_email,
            event_type=str(event_type),
            action=action,
            outcome=str(outcome),
            resource_type=resource_type,
            resource_id=str(resource_id) if resource_id is not None else None,
            metadata_=clean_metadata,
            ip_address=ip_address,
            user_agent=user_agent[:512] if user_agent else None,
            request_id=request_id,
            created_at=created_at,
            previous_hash=previous_hash,
            event_hash=event_hash,
        )

        db.add(audit_log)
        db.flush()

        if autocommit:
            db.commit()

        logger.info(
            "AUDIT EVENT recorded (org=%s ws=%s actor=%s event=%s action=%s outcome=%s)",
            organization_id,
            workspace_id,
            actor_email or actor_user_id,
            event_type,
            action,
            outcome,
        )
        return audit_log

    @staticmethod
    def verify_chain(db: Session, organization_id: UUID) -> tuple[bool, str | None, int]:
        """Verify the cryptographic hash chain integrity for an organization's audit log.

        Returns (is_valid, error_detail, verified_count).
        """
        events = db.scalars(
            select(AuditLog)
            .where(AuditLog.organization_id == organization_id)
            .order_by(AuditLog.created_at.asc(), AuditLog.id.asc())
        ).all()

        expected_previous_hash = None
        for idx, event in enumerate(events):
            # 1. Verify previous_hash link
            if event.previous_hash != expected_previous_hash:
                return (
                    False,
                    f"Chain link broken at event {event.id} (index {idx}): expected previous_hash '{expected_previous_hash}', got '{event.previous_hash}'",
                    idx,
                )

            # 2. Recompute event_hash from canonical payload
            clean_metadata = sanitize_audit_metadata(event.metadata_)
            canonical_bytes = compute_canonical_payload(
                organization_id=event.organization_id,
                workspace_id=event.workspace_id,
                actor_user_id=event.actor_user_id,
                actor_email=event.actor_email_snapshot,
                event_type=event.event_type,
                action=event.action,
                outcome=event.outcome,
                resource_type=event.resource_type,
                resource_id=event.resource_id,
                clean_metadata=clean_metadata,
                ip_address=event.ip_address,
                user_agent=event.user_agent,
                request_id=event.request_id,
                created_at=event.created_at,
                previous_hash=event.previous_hash,
            )
            computed_hash = hashlib.sha256(canonical_bytes).hexdigest()

            if computed_hash != event.event_hash:
                return (
                    False,
                    f"Hash mismatch at event {event.id} (index {idx}): stored '{event.event_hash}', computed '{computed_hash}'",
                    idx,
                )

            expected_previous_hash = event.event_hash

        return True, None, len(events)

    @staticmethod
    def list_audit_logs(
        db: Session,
        *,
        organization_id: UUID,
        workspace_id: UUID | None = None,
        event_type: str | None = None,
        action: str | None = None,
        actor_user_id: UUID | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
        outcome: str | None = None,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[AuditLog], int]:
        """Query audit logs with tenant boundaries and filters."""
        stmt = select(AuditLog).where(AuditLog.organization_id == organization_id)

        if workspace_id is not None:
            stmt = stmt.where(AuditLog.workspace_id == workspace_id)
        if event_type:
            stmt = stmt.where(AuditLog.event_type == event_type)
        if action:
            stmt = stmt.where(AuditLog.action == action)
        if actor_user_id:
            stmt = stmt.where(AuditLog.actor_user_id == actor_user_id)
        if resource_type:
            stmt = stmt.where(AuditLog.resource_type == resource_type)
        if resource_id:
            stmt = stmt.where(AuditLog.resource_id == resource_id)
        if outcome:
            stmt = stmt.where(AuditLog.outcome == outcome)
        if from_date:
            stmt = stmt.where(AuditLog.created_at >= from_date)
        if to_date:
            stmt = stmt.where(AuditLog.created_at <= to_date)

        # Count query
        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = db.scalar(count_stmt) or 0

        # Data query
        stmt = stmt.order_by(AuditLog.created_at.desc(), AuditLog.id.desc()).limit(limit).offset(offset)
        items = list(db.scalars(stmt))

        return items, total
