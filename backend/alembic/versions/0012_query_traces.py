"""Add query_traces and query_trace_spans tables for Platform Observability.

Revision ID: 0012_query_traces
Revises: 0011_audit_log_fk_immutability
Create Date: 2026-10-01

Enhancements for Phase 1.6 Platform Observability & Query Tracing:
- query_traces table for structured RAG request telemetry and latency measurements.
- query_trace_spans table for granular child span stage metrics.
- Efficient administrative and tenant-scoped indexes.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012_query_traces"
down_revision: Union[str, None] = "0011_audit_log_fk_immutability"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create query_traces table
    op.create_table(
        "query_traces",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "trace_id",
            sa.String(64),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "request_id",
            sa.String(64),
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
            sa.ForeignKey("workspaces.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "actor_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "operation_type",
            sa.String(64),
            nullable=False,
            server_default="CHAT",
        ),
        sa.Column(
            "status",
            sa.String(32),
            nullable=False,
            server_default="SUCCESS",
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "total_latency_ms",
            sa.Float(),
            nullable=True,
        ),
        sa.Column(
            "error_type",
            sa.String(64),
            nullable=True,
        ),
        sa.Column(
            "error_code",
            sa.String(64),
            nullable=True,
        ),
        sa.Column(
            "retrieval_mode",
            sa.String(32),
            nullable=True,
        ),
        sa.Column(
            "grounded",
            sa.Boolean(),
            nullable=True,
        ),
        sa.Column(
            "result_count",
            sa.Integer(),
            nullable=True,
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )

    # Indexes on query_traces
    op.create_index(
        "ix_query_traces_org_started_at",
        "query_traces",
        ["organization_id", "started_at"],
    )
    op.create_index(
        "ix_query_traces_ws_started_at",
        "query_traces",
        ["workspace_id", "started_at"],
    )
    op.create_index(
        "ix_query_traces_trace_id",
        "query_traces",
        ["trace_id"],
    )
    op.create_index(
        "ix_query_traces_request_id",
        "query_traces",
        ["request_id"],
    )
    op.create_index(
        "ix_query_traces_op_started_at",
        "query_traces",
        ["operation_type", "started_at"],
    )
    op.create_index(
        "ix_query_traces_status_started_at",
        "query_traces",
        ["status", "started_at"],
    )

    # 2. Create query_trace_spans table
    op.create_table(
        "query_trace_spans",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "trace_id",
            sa.String(64),
            sa.ForeignKey("query_traces.trace_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "parent_span_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("query_trace_spans.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "span_name",
            sa.String(64),
            nullable=False,
        ),
        sa.Column(
            "span_type",
            sa.String(64),
            nullable=False,
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "duration_ms",
            sa.Float(),
            nullable=True,
        ),
        sa.Column(
            "status",
            sa.String(32),
            nullable=False,
            server_default="SUCCESS",
        ),
        sa.Column(
            "error_type",
            sa.String(64),
            nullable=True,
        ),
        sa.Column(
            "metadata",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )

    op.create_index(
        "ix_query_trace_spans_trace_id",
        "query_trace_spans",
        ["trace_id"],
    )
    op.create_index(
        "ix_query_trace_spans_trace_started",
        "query_trace_spans",
        ["trace_id", "started_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_query_trace_spans_trace_started", table_name="query_trace_spans")
    op.drop_index("ix_query_trace_spans_trace_id", table_name="query_trace_spans")
    op.drop_table("query_trace_spans")

    op.drop_index("ix_query_traces_status_started_at", table_name="query_traces")
    op.drop_index("ix_query_traces_op_started_at", table_name="query_traces")
    op.drop_index("ix_query_traces_request_id", table_name="query_traces")
    op.drop_index("ix_query_traces_trace_id", table_name="query_traces")
    op.drop_index("ix_query_traces_ws_started_at", table_name="query_traces")
    op.drop_index("ix_query_traces_org_started_at", table_name="query_traces")
    op.drop_table("query_traces")
