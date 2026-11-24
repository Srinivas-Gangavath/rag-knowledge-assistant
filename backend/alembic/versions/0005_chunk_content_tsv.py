"""Add generated tsvector column and GIN index for lexical retrieval.

Revision ID: 0005_chunk_content_tsv
Revises: 0004_document_metadata
Create Date: 2026-09-04

PostgreSQL full-text search uses the `simple` configuration (no stemming).
This is lexical/FTS ranking via ts_rank_cd, not BM25.

Existing chunk content and embeddings are not modified. The STORED generated
column backfills content_tsv for current rows.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0005_chunk_content_tsv"
down_revision: Union[str, None] = "0004_document_metadata"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE document_chunks
        ADD COLUMN content_tsv tsvector
        GENERATED ALWAYS AS (to_tsvector('simple', coalesce(content, ''))) STORED
        NOT NULL
        """
    )
    op.create_index(
        "ix_document_chunks_content_tsv",
        "document_chunks",
        ["content_tsv"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index("ix_document_chunks_content_tsv", table_name="document_chunks")
    op.drop_column("document_chunks", "content_tsv")
