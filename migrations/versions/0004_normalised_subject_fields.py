"""Store the normalised subject field of every paper.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-02

`SearchFilters.fields` matched `topics[].field`, which only OpenAlex records
carry. Filtering the feed by field would therefore have filtered 43% of the
corpus and silently hidden the arXiv, bioRxiv and Europe PMC papers - a filter
whose recall depends on which connector happened to find a paper is worse than
no filter at all.

`paper.fields` holds the field slugs derived from a paper's merged topics by
`academious.ingest.taxonomy`, which maps all four source vocabularies onto one.
A derived column rather than a query-time mapping because the mapping lives in
Python: arXiv archive prefixes and bioRxiv category labels cannot be resolved in
SQL without shipping the tables into the database and joining them per row.

Existing rows are left empty. The column is populated by
`scripts/backfill_fields.py`, which replays stored topics through the current
mapping and can be re-run after any mapping change - which a data migration
written once could not be.

The GIN index is what makes `fields && ARRAY[...]` an index scan rather than a
sequential scan over 100k rows.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "paper",
        sa.Column(
            "fields",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
    )
    op.create_index(
        "ix_paper_fields",
        "paper",
        ["fields"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index("ix_paper_fields", table_name="paper")
    op.drop_column("paper", "fields")
