"""Create organizations and workspaces tables, add workspace scoping to existing resources.

Revision ID: 0006_orgs_and_workspaces
Revises: 0005_chunk_content_tsv
Create Date: 2026-10-01

Establishes tenancy foundation:
- organizations table
- workspaces table
- bootstrap default organization and default workspace
- workspace_id on documents, document_chunks, conversations
- composite foreign key (document_id, workspace_id) on document_chunks to guarantee chunk-document tenant consistency
- indexes for tenant filtering and ordering
"""

from typing import Sequence, Union
import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_orgs_and_workspaces"
down_revision: Union[str, None] = "0005_chunk_content_tsv"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create organizations table
    op.create_table(
        "organizations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug", name="uq_organizations_slug"),
    )
    op.create_index("ix_organizations_slug", "organizations", ["slug"])

    # 2. Create workspaces table
    op.create_table(
        "workspaces",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=255), nullable=False),
        sa.Column(
            "settings",
            postgresql.JSONB(astext_type=sa.Text()),
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
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            ondelete="CASCADE",
            name="fk_workspaces_organization_id_organizations",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "organization_id", "slug", name="uq_workspaces_organization_id_slug"
        ),
    )
    op.create_index("ix_workspaces_organization_id", "workspaces", ["organization_id"])
    op.create_index("ix_workspaces_slug", "workspaces", ["slug"])

    # 3. Insert bootstrap default organization & workspace
    bind = op.get_bind()
    default_org_id = uuid.uuid4()
    default_ws_id = uuid.uuid4()

    bind.execute(
        sa.text(
            "INSERT INTO organizations (id, name, slug) "
            "VALUES (:id, 'Default Organization', 'default') "
            "ON CONFLICT (slug) DO NOTHING"
        ),
        {"id": default_org_id},
    )
    org_row = bind.execute(
        sa.text("SELECT id FROM organizations WHERE slug = 'default'")
    ).first()
    org_id = org_row[0]

    bind.execute(
        sa.text(
            "INSERT INTO workspaces (id, organization_id, name, slug, settings) "
            "VALUES (:id, :org_id, 'Default Workspace', 'default', '{}'::jsonb) "
            "ON CONFLICT (organization_id, slug) DO NOTHING"
        ),
        {"id": default_ws_id, "org_id": org_id},
    )
    ws_row = bind.execute(
        sa.text("SELECT id FROM workspaces WHERE organization_id = :org_id AND slug = 'default'"),
        {"org_id": org_id},
    ).first()
    workspace_id = ws_row[0]

    # 4. Add nullable workspace_id columns to existing tables
    op.add_column(
        "documents",
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "document_chunks",
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "conversations",
        sa.Column("workspace_id", postgresql.UUID(as_uuid=True), nullable=True),
    )

    # 5. Backfill existing records to the default workspace
    bind.execute(
        sa.text("UPDATE documents SET workspace_id = :ws_id WHERE workspace_id IS NULL"),
        {"ws_id": workspace_id},
    )
    bind.execute(
        sa.text(
            "UPDATE document_chunks c SET workspace_id = d.workspace_id "
            "FROM documents d WHERE c.document_id = d.id AND c.workspace_id IS NULL"
        )
    )
    bind.execute(
        sa.text("UPDATE document_chunks SET workspace_id = :ws_id WHERE workspace_id IS NULL"),
        {"ws_id": workspace_id},
    )
    bind.execute(
        sa.text("UPDATE conversations SET workspace_id = :ws_id WHERE workspace_id IS NULL"),
        {"ws_id": workspace_id},
    )

    # 6. Add unique constraint on documents (id, workspace_id)
    op.create_unique_constraint(
        "uq_documents_id_workspace_id",
        "documents",
        ["id", "workspace_id"],
    )

    # 7. Alter workspace_id to NOT NULL
    op.alter_column("documents", "workspace_id", nullable=False)
    op.alter_column("document_chunks", "workspace_id", nullable=False)
    op.alter_column("conversations", "workspace_id", nullable=False)

    # 8. Add Foreign Key constraints
    op.create_foreign_key(
        "fk_documents_workspace_id_workspaces",
        "documents",
        "workspaces",
        ["workspace_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_document_chunks_workspace_id_workspaces",
        "document_chunks",
        "workspaces",
        ["workspace_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_document_chunks_document_workspace",
        "document_chunks",
        "documents",
        ["document_id", "workspace_id"],
        ["id", "workspace_id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_conversations_workspace_id_workspaces",
        "conversations",
        "workspaces",
        ["workspace_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # 9. Add indexes
    op.create_index("ix_documents_workspace_id", "documents", ["workspace_id"])
    op.create_index("ix_document_chunks_workspace_id", "document_chunks", ["workspace_id"])
    op.create_index("ix_conversations_workspace_id", "conversations", ["workspace_id"])
    op.create_index(
        "ix_conversations_workspace_id_updated_at",
        "conversations",
        ["workspace_id", "updated_at"],
    )


def downgrade() -> None:
    # 1. Drop indexes
    op.drop_index("ix_conversations_workspace_id_updated_at", table_name="conversations")
    op.drop_index("ix_conversations_workspace_id", table_name="conversations")
    op.drop_index("ix_document_chunks_workspace_id", table_name="document_chunks")
    op.drop_index("ix_documents_workspace_id", table_name="documents")

    # 2. Drop foreign keys
    op.drop_constraint("fk_conversations_workspace_id_workspaces", "conversations", type_="foreignkey")
    op.drop_constraint("fk_document_chunks_document_workspace", "document_chunks", type_="foreignkey")
    op.drop_constraint("fk_document_chunks_workspace_id_workspaces", "document_chunks", type_="foreignkey")
    op.drop_constraint("fk_documents_workspace_id_workspaces", "documents", type_="foreignkey")

    # 3. Drop unique constraint
    op.drop_constraint("uq_documents_id_workspace_id", "documents", type_="unique")

    # 4. Drop columns
    op.drop_column("conversations", "workspace_id")
    op.drop_column("document_chunks", "workspace_id")
    op.drop_column("documents", "workspace_id")

    # 5. Drop workspaces table
    op.drop_index("ix_workspaces_slug", table_name="workspaces")
    op.drop_index("ix_workspaces_organization_id", table_name="workspaces")
    op.drop_table("workspaces")

    # 6. Drop organizations table
    op.drop_index("ix_organizations_slug", table_name="organizations")
    op.drop_table("organizations")
