"""Add document-level category, source, and tags.

Revision ID: 0004_document_metadata
Revises: 0003_conversations
Create Date: 2026-09-04

Non-destructive: existing rows keep category/source NULL and tags [].
Chunk rows, embeddings, and chunk JSONB are not modified.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_document_metadata"
down_revision: Union[str, None] = "0003_conversations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("category", sa.String(length=64), nullable=True))
    op.add_column("documents", sa.Column("source", sa.String(length=64), nullable=True))
    op.add_column(
        "documents",
        sa.Column(
            "tags",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.create_index("ix_documents_category", "documents", ["category"])


def downgrade() -> None:
    op.drop_index("ix_documents_category", table_name="documents")
    op.drop_column("documents", "tags")
    op.drop_column("documents", "source")
    op.drop_column("documents", "category")
