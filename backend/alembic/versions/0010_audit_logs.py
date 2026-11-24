"""Add audit_logs table with immutable trigger and tamper-evident hash chaining.

Revision ID: 0010_audit_logs
Revises: 0009_document_acls
Create Date: 2026-10-01

Enhancements for Phase 1.5 Enterprise Audit Logging & Compliance:
- audit_logs table with tenant-scoping (organization_id, workspace_id)
- actor tracking (actor_user_id, actor_email_snapshot)
- event taxonomy, action, outcome, resource type/id, request context
- previous_hash and event_hash for tamper-evident hash chaining
- database-level append-only trigger preventing UPDATE and DELETE
- indexes for efficient administrative audit review
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010_audit_logs"
down_revision: Union[str, None] = "0009_document_acls"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create audit_logs table
    op.create_table(
        "audit_logs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "actor_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "actor_email_snapshot",
            sa.String(255),
            nullable=True,
        ),
        sa.Column(
            "event_type",
            sa.String(64),
            nullable=False,
        ),
        sa.Column(
            "action",
            sa.String(64),
            nullable=False,
        ),
        sa.Column(
            "outcome",
            sa.String(32),
            nullable=False,
            server_default="SUCCESS",
        ),
        sa.Column(
            "resource_type",
            sa.String(64),
            nullable=True,
        ),
        sa.Column(
            "resource_id",
            sa.String(255),
            nullable=True,
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "ip_address",
            sa.String(64),
            nullable=True,
        ),
        sa.Column(
            "user_agent",
            sa.String(512),
            nullable=True,
        ),
        sa.Column(
            "request_id",
            sa.String(64),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "previous_hash",
            sa.String(64),
            nullable=True,
        ),
        sa.Column(
            "event_hash",
            sa.String(64),
            nullable=False,
        ),
    )

    # 2. Indexes for audit log queries
    op.create_index(
        "ix_audit_logs_org_created_at",
        "audit_logs",
        ["organization_id", "created_at"],
    )
    op.create_index(
        "ix_audit_logs_ws_created_at",
        "audit_logs",
        ["workspace_id", "created_at"],
    )
    op.create_index(
        "ix_audit_logs_event_type_created_at",
        "audit_logs",
        ["event_type", "created_at"],
    )
    op.create_index(
        "ix_audit_logs_actor_created_at",
        "audit_logs",
        ["actor_user_id", "created_at"],
    )
    op.create_index(
        "ix_audit_logs_resource",
        "audit_logs",
        ["resource_type", "resource_id"],
    )
    op.create_index(
        "ix_audit_logs_outcome_created_at",
        "audit_logs",
        ["outcome", "created_at"],
    )

    # 3. Database-level immutability trigger preventing UPDATE and DELETE
    op.execute(
        """
        CREATE OR REPLACE FUNCTION prevent_audit_log_modification()
        RETURNS TRIGGER AS $$
        BEGIN
            RAISE EXCEPTION 'Audit logs are append-only and cannot be updated or deleted';
        END;
        $$ LANGUAGE plpgsql;

        CREATE TRIGGER trg_prevent_audit_log_modification
        BEFORE UPDATE OR DELETE ON audit_logs
        FOR EACH ROW
        EXECUTE FUNCTION prevent_audit_log_modification();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_prevent_audit_log_modification ON audit_logs")
    op.execute("DROP FUNCTION IF EXISTS prevent_audit_log_modification()")
    op.drop_index("ix_audit_logs_outcome_created_at", table_name="audit_logs")
    op.drop_index("ix_audit_logs_resource", table_name="audit_logs")
    op.drop_index("ix_audit_logs_actor_created_at", table_name="audit_logs")
    op.drop_index("ix_audit_logs_event_type_created_at", table_name="audit_logs")
    op.drop_index("ix_audit_logs_ws_created_at", table_name="audit_logs")
    op.drop_index("ix_audit_logs_org_created_at", table_name="audit_logs")
    op.drop_table("audit_logs")
