"""Order the feed by when a paper became available, not by the date it claims.

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-03

The feed ordered on `published_date DESC`. That is the date a paper *claims*,
and journals postdate issues: an article released in September carries a
December issue date, and annual volumes carry next year's. Correct metadata,
and the wrong sort key - on 2026-09-03 the entire first page of the live site
was dated 2027, so papers not yet nominally published outranked work that came
out that week, and would keep doing so for a year.

`feed_date` is the earlier of the two things we know: what the paper says, and
when it first reached us.

    LEAST(published_date, created_at::date)

A postdated 2027 paper harvested today became available today, so it sorts as
today. A genuine 1817 article harvested today stays in 1817, because its own
date is earlier. A paper with no date at all stays NULL and sorts last under
NULLS LAST, which is where an unknown date belongs - notably the 100 rows whose
implausible dates were just cleared, which must not be promoted to "newest" by
having been repaired.

That last case needs the CASE around LEAST, because **PostgreSQL's LEAST skips
NULL arguments** rather than propagating them: `LEAST(NULL, current_date)` is
today. Written without it, every undated paper in the corpus would have been
stamped with the day it was ingested and taken over the front page - the exact
outcome this column exists to prevent, arriving through the fix for it.

Generated and stored rather than maintained in Python, for the reason
`search_tsv` is: it cannot then drift from the row it describes. Every function
in the expression is IMMUTABLE - `timezone(text, timestamptz)` is, and so is
the cast to date and LEAST - which is what a generated column requires; a bare
`created_at::date` is only STABLE, because it would depend on the session
timezone, and PostgreSQL rejects it here.

The index carries the tiebreak column too: `published_date` alone was never a
total order (many papers share a day), and `feed_date` is no different, so
paging without `id DESC` in the same index would let page two repeat page one.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FEED_DATE_EXPRESSION = (
    "CASE WHEN published_date IS NULL THEN NULL "
    "ELSE LEAST(published_date, (created_at AT TIME ZONE 'UTC')::date) END"
)


def upgrade() -> None:
    op.add_column(
        "paper",
        sa.Column(
            "feed_date",
            sa.Date(),
            sa.Computed(FEED_DATE_EXPRESSION, persisted=True),
            nullable=True,
        ),
    )
    op.execute("CREATE INDEX ix_paper_feed_date ON paper (feed_date DESC NULLS LAST, id DESC)")


def downgrade() -> None:
    op.drop_index("ix_paper_feed_date", table_name="paper")
    op.drop_column("paper", "feed_date")
