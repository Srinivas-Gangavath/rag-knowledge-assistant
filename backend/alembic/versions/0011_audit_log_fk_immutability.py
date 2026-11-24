"""Hardened audit log foreign keys to prevent indirect mutation via entity deletion.

Revision ID: 0011_audit_log_fk_immutability
Revises: 0010_audit_logs
Create Date: 2026-10-01

Enhancements for Phase 1.5 Enterprise Audit Logging & Compliance:
- Replace ON DELETE SET NULL on actor_user_id and workspace_id with ON DELETE RESTRICT
  to ensure referenced entity deletion cannot silently mutate historical audit event fields
  and invalidate cryptographic hash chains.
- Optimize verification query indexing with composite (organization_id, created_at, id) index.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0011_audit_log_fk_immutability"
down_revision: Union[str, None] = "0010_audit_logs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Update foreign key constraints to ON DELETE RESTRICT
    op.drop_constraint("audit_logs_actor_user_id_fkey", "audit_logs", type_="foreignkey")
    op.create_foreign_key(
        "audit_logs_actor_user_id_fkey",
        "audit_logs",
        "users",
        ["actor_user_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.drop_constraint("audit_logs_workspace_id_fkey", "audit_logs", type_="foreignkey")
    op.create_foreign_key(
        "audit_logs_workspace_id_fkey",
        "audit_logs",
        "workspaces",
        ["workspace_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    # 2. Optimize index for verification query ordering (WHERE org = :org ORDER BY created_at ASC, id ASC)
    op.drop_index("ix_audit_logs_org_created_at", table_name="audit_logs")
    op.create_index(
        "ix_audit_logs_org_created_at_id",
        "audit_logs",
        ["organization_id", "created_at", "id"],
    )


def downgrade() -> None:
    op.drop_index("ix_audit_logs_org_created_at_id", table_name="audit_logs")
    op.create_index(
        "ix_audit_logs_org_created_at",
        "audit_logs",
        ["organization_id", "created_at"],
    )

    op.drop_constraint("audit_logs_workspace_id_fkey", "audit_logs", type_="foreignkey")
    op.create_foreign_key(
        "audit_logs_workspace_id_fkey",
        "audit_logs",
        "workspaces",
        ["workspace_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.drop_constraint("audit_logs_actor_user_id_fkey", "audit_logs", type_="foreignkey")
    op.create_foreign_key(
        "audit_logs_actor_user_id_fkey",
        "audit_logs",
        "users",
        ["actor_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
