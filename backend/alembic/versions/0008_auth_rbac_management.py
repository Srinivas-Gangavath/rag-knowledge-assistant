"""Add is_archived to workspaces and user_id to conversations.

Revision ID: 0008_auth_rbac_management
Revises: 0007_auth_and_memberships
Create Date: 2026-10-01

Enhancements for Phase 1.3 Authorization, RBAC & Workspace Management:
- workspaces.is_archived: boolean flag for safe workspace lifecycle management
- conversations.user_id: nullable FK to users.id for conversation privacy boundary
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008_auth_rbac_management"
down_revision: Union[str, None] = "0007_auth_and_memberships"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add is_archived to workspaces
    op.add_column(
        "workspaces",
        sa.Column(
            "is_archived",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_index(
        "ix_workspaces_is_archived",
        "workspaces",
        ["is_archived"],
    )

    # 2. Add user_id to conversations
    op.add_column(
        "conversations",
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_conversations_user_id_users",
        "conversations",
        "users",
        ["user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_conversations_user_id",
        "conversations",
        ["user_id"],
    )


def downgrade() -> None:
    # 2. Drop user_id from conversations
    op.drop_index("ix_conversations_user_id", table_name="conversations")
    op.drop_constraint("fk_conversations_user_id_users", "conversations", type_="foreignkey")
    op.drop_column("conversations", "user_id")

    # 1. Drop is_archived from workspaces
    op.drop_index("ix_workspaces_is_archived", table_name="workspaces")
    op.drop_column("workspaces", "is_archived")
