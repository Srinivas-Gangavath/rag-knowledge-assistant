"""Add document_acls table for document-level access control.

Revision ID: 0009_document_acls
Revises: 0008_auth_rbac_management
Create Date: 2026-10-01

Enhancements for Phase 1.4 Document-Level Access Control Lists (ACL):
- document_acls table with principal_type (USER, WORKSPACE_ROLE) and document_permission (READ, WRITE, ADMIN)
- unique constraint on (document_id, principal_type, principal_id, permission)
- indexes for document_id and (principal_type, principal_id)
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009_document_acls"
down_revision: Union[str, None] = "0008_auth_rbac_management"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

principal_type_enum = postgresql.ENUM("USER", "WORKSPACE_ROLE", name="principal_type", create_type=False)
document_permission_enum = postgresql.ENUM("READ", "WRITE", "ADMIN", name="document_permission", create_type=False)


def upgrade() -> None:
    # 1. Create Enums
    principal_type_enum.create(op.get_bind(), checkfirst=True)
    document_permission_enum.create(op.get_bind(), checkfirst=True)

    # 2. Create document_acls table
    op.create_table(
        "document_acls",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "document_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "principal_type",
            principal_type_enum,
            nullable=False,
        ),
        sa.Column(
            "principal_id",
            sa.String(255),
            nullable=False,
        ),
        sa.Column(
            "permission",
            document_permission_enum,
            nullable=False,
            server_default="READ",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "document_id",
            "principal_type",
            "principal_id",
            "permission",
            name="uq_document_acls_doc_principal_perm",
        ),
    )
    op.create_index(
        "ix_document_acls_document_id",
        "document_acls",
        ["document_id"],
    )
    op.create_index(
        "ix_document_acls_principal",
        "document_acls",
        ["principal_type", "principal_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_document_acls_principal", table_name="document_acls")
    op.drop_index("ix_document_acls_document_id", table_name="document_acls")
    op.drop_table("document_acls")
    document_permission_enum.drop(op.get_bind(), checkfirst=True)
    principal_type_enum.drop(op.get_bind(), checkfirst=True)
