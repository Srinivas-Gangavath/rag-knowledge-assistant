"""Add platform_alerts and alert_rules tables for Operational Alerting.

Revision ID: 0013_platform_alerts_and_rules
Revises: 0012_query_traces
Create Date: 2026-10-01

Enhancements for Phase 1.8 Operational Alerting, Anomaly Detection & Self-Diagnostics:
- platform_alerts table for operational alerts, severity, lifecycle states, and diagnostic evidence.
- alert_rules table for configurable threshold and anomaly rules.
- Scoped tenant indexes and deduplication index.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013_platform_alerts_and_rules"
down_revision: Union[str, None] = "0012_query_traces"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create alert_rules table
    op.create_table(
        "alert_rules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("rule_type", sa.String(64), nullable=False),
        sa.Column("metric_name", sa.String(64), nullable=False),
        sa.Column("operator", sa.String(16), nullable=False),
        sa.Column("threshold", sa.Float(), nullable=False),
        sa.Column("window_minutes", sa.Integer(), nullable=False, server_default="15"),
        sa.Column("minimum_sample_size", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("severity", sa.String(32), nullable=False, server_default="WARNING"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("cooldown_minutes", sa.Integer(), nullable=False, server_default="60"),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_alert_rules_org_id", "alert_rules", ["organization_id"])
    op.create_index("ix_alert_rules_ws_id", "alert_rules", ["workspace_id"])
    op.create_index("ix_alert_rules_enabled", "alert_rules", ["enabled"])

    # 2. Create platform_alerts table
    op.create_table(
        "platform_alerts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("alert_type", sa.String(64), nullable=False),
        sa.Column("severity", sa.String(32), nullable=False, server_default="WARNING"),
        sa.Column("status", sa.String(32), nullable=False, server_default="OPEN"),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("metric_name", sa.String(64), nullable=True),
        sa.Column("metric_value", sa.Float(), nullable=True),
        sa.Column("threshold_value", sa.Float(), nullable=True),
        sa.Column(
            "detected_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "acknowledged_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "resolved_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("resolution_reason", sa.Text(), nullable=True),
        sa.Column("deduplication_key", sa.String(255), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_platform_alerts_org_detected_at",
        "platform_alerts",
        ["organization_id", "detected_at"],
    )
    op.create_index(
        "ix_platform_alerts_ws_detected_at",
        "platform_alerts",
        ["workspace_id", "detected_at"],
    )
    op.create_index(
        "ix_platform_alerts_status_detected_at",
        "platform_alerts",
        ["status", "detected_at"],
    )
    op.create_index(
        "ix_platform_alerts_type_detected_at",
        "platform_alerts",
        ["alert_type", "detected_at"],
    )
    op.create_index(
        "ix_platform_alerts_severity_detected_at",
        "platform_alerts",
        ["severity", "detected_at"],
    )
    op.create_index(
        "ix_platform_alerts_dedup_key",
        "platform_alerts",
        ["deduplication_key"],
    )


def downgrade() -> None:
    op.drop_index("ix_platform_alerts_dedup_key", table_name="platform_alerts")
    op.drop_index("ix_platform_alerts_severity_detected_at", table_name="platform_alerts")
    op.drop_index("ix_platform_alerts_type_detected_at", table_name="platform_alerts")
    op.drop_index("ix_platform_alerts_status_detected_at", table_name="platform_alerts")
    op.drop_index("ix_platform_alerts_ws_detected_at", table_name="platform_alerts")
    op.drop_index("ix_platform_alerts_org_detected_at", table_name="platform_alerts")
    op.drop_table("platform_alerts")

    op.drop_index("ix_alert_rules_enabled", table_name="alert_rules")
    op.drop_index("ix_alert_rules_ws_id", table_name="alert_rules")
    op.drop_index("ix_alert_rules_org_id", table_name="alert_rules")
    op.drop_table("alert_rules")
