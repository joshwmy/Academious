"""Record which paper version each embedding was built from.

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-30

Staleness was decided by `paper.updated_at > paper_embedding.updated_at`. Those
two timestamps come from different clocks with different semantics - PostgreSQL
at transaction start for the paper, the application at statement time for the
embedding - so an edit that opens before the embed worker writes but commits
after it carries the *earlier* timestamp. The comparison then reports the vector
as current and the obsolete vector is stranded until some unrelated later write
happens to bump the paper row.

`source_updated_at` replaces that inference with a fact: the version the worker
actually read. Comparing it to `paper.updated_at` cannot be fooled by commit
ordering or by clock skew between the application and database hosts.

Existing rows are left NULL on purpose rather than backfilled to
`paper.updated_at`. Backfilling would assert that every stored vector matches
its paper's current text, which is exactly the assumption this defect makes
unsafe. NULL reads as "version unknown", compares as distinct from every paper
version, and so re-checks each row once on the next embedding pass. That pass
compares `input_text_hash` against the text built now: unchanged papers are
dismissed without model inference and stamped with their version, and any vector
the old rule had stranded is rebuilt. The backfill is therefore self-healing and
costs no GPU/CPU inference for a corpus that is genuinely up to date.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "paper_embedding",
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("paper_embedding", "source_updated_at")
