"""Phase 2: pgvector embedding storage and the lexical search index.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-28

Adding `paper.search_tsv` as a STORED generated column rewrites the paper table.
That is acceptable at Phase 2 corpus size and is preferable to a trigger, which
can be bypassed by a bulk load and then silently disagree with the row it
indexes.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import HALFVEC
from sqlalchemy.dialects import postgresql

from academious.db.ddl import (
    DROP_KEYWORDS_TEXT_FUNCTION,
    KEYWORDS_TEXT_FUNCTION,
    SEARCH_TSV_EXPRESSION,
    create_extensions_sql,
)

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMBEDDING_DIM = 768


def upgrade() -> None:
    for statement in create_extensions_sql():
        op.execute(statement)
    op.execute(KEYWORDS_TEXT_FUNCTION)

    op.add_column(
        "paper",
        sa.Column(
            "search_tsv",
            postgresql.TSVECTOR(),
            sa.Computed(SEARCH_TSV_EXPRESSION, persisted=True),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_paper_search_tsv", "paper", ["search_tsv"], postgresql_using="gin"
    )

    op.create_table(
        "paper_embedding",
        sa.Column("paper_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("model_key", sa.String(64), nullable=False),
        sa.Column("embedding", HALFVEC(EMBEDDING_DIM), nullable=False),
        sa.Column("dim", sa.Integer(), nullable=False),
        sa.Column("input_strategy", sa.String(32), nullable=False),
        sa.Column("input_text_hash", sa.String(64), nullable=False),
        sa.Column("token_count", sa.Integer()),
        sa.Column("truncated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["paper_id"],
            ["paper.id"],
            name="fk_paper_embedding_paper_id_paper",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("paper_id", "model_key", name="pk_paper_embedding"),
    )
    op.create_index(
        "ix_paper_embedding_model_paper", "paper_embedding", ["model_key", "paper_id"]
    )

    # No ANN index here, deliberately. Phase 2 measures exact search first; the
    # decision and the numbers behind it are in docs/retrieval.md, and the index
    # itself arrives in its own migration once the measurement justifies it.


def downgrade() -> None:
    op.drop_index("ix_paper_embedding_model_paper", table_name="paper_embedding")
    op.drop_table("paper_embedding")
    op.drop_index("ix_paper_search_tsv", table_name="paper")
    op.drop_column("paper", "search_tsv")
    op.execute(DROP_KEYWORDS_TEXT_FUNCTION)
