"""Clear publication dates the feed cannot believe, for papers already stored.

`ingest/dates.py` applies the plausibility horizon to everything arriving from
now on. It does nothing for what is already in the table, and those rows are
the ones doing the damage: the feed orders by `published_date DESC`, so a paper
dated 2050 holds the first position until 2050 and looks entirely healthy while
it does.

    python scripts/sanitise_dates.py                  # report only
    python scripts/sanitise_dates.py --apply          # clear them

Measured on the live corpus on 2026-09-03, before this existed: 607 future-dated
papers, all from OpenAlex, running out to 2050-02-21.

What "clear" means: `published_date`, `published_year` and `first_seen_online`
become NULL where the stored value is past the horizon. Nothing is invented and
nothing is clamped - a fabricated date moved to the horizon is still fabricated,
and it would then rank above every paper genuinely published today. The raw
payload in `source_record` is untouched, so the original value survives and the
decision can be replayed after any change to the rule.

Re-runnable and idempotent: a row already cleared no longer matches.
"""

from __future__ import annotations

import argparse
import collections
import sys
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from academious.core.logging import configure_logging, get_logger
from academious.db.models.paper import Paper
from academious.db.models.support import SourceRecord
from academious.db.session import session_scope
from academious.ingest.dates import FUTURE_HORIZON_DAYS, is_plausible

log = get_logger(__name__)


def sanitise_stored(session: Session, *, apply: bool, batch_size: int) -> dict[str, int]:
    """Clear implausible dates, paging on the primary key.

    Paged rather than streamed for the same reason `backfill_fields.py` is: a
    `yield_per` cursor is closed by the commit inside the loop, which kills the
    run part-way through a table it has half rewritten.
    """
    # Seeded so the summary keys always exist: a run that finds nothing should
    # report zeros, not omit the line, and a caller reading the result should
    # not have to distinguish "none" from "not counted".
    counts: collections.Counter[str] = collections.Counter(
        {"scanned": 0, "affected": 0, "published_date": 0, "first_seen_online": 0}
    )
    after: uuid.UUID | None = None
    examples: list[tuple[str, str]] = []

    while True:
        stmt = select(Paper).order_by(Paper.id).limit(batch_size)
        if after is not None:
            stmt = stmt.where(Paper.id > after)
        batch = list(session.scalars(stmt))
        if not batch:
            break

        changed = False
        for paper in batch:
            counts["scanned"] += 1
            bad_published = not is_plausible(paper.published_date)
            bad_online = not is_plausible(paper.first_seen_online)
            if not bad_published and not bad_online:
                continue

            counts["affected"] += 1
            if bad_published:
                counts["published_date"] += 1
                if len(examples) < 10 and paper.published_date is not None:
                    examples.append((paper.published_date.isoformat(), paper.title[:60]))
            if bad_online:
                counts["first_seen_online"] += 1

            for key in _sources_of(session, paper.id):
                counts[f"source:{key}"] += 1

            if apply:
                if bad_published:
                    paper.published_date = None
                    paper.published_year = None
                if bad_online:
                    paper.first_seen_online = None
                changed = True

        after = batch[-1].id
        if apply and changed:
            session.commit()
        else:
            # Only this batch: expunge_all() would detach objects the caller
            # holds, which is a side effect a report has no business having.
            for paper in batch:
                session.expunge(paper)

    _print(counts, examples, applied=apply)
    return dict(counts)


def _sources_of(session: Session, paper_id: uuid.UUID) -> list[str]:
    rows = session.scalars(select(SourceRecord.source_key).where(SourceRecord.paper_id == paper_id))
    return sorted(set(rows))


def _print(
    counts: collections.Counter[str], examples: list[tuple[str, str]], *, applied: bool
) -> None:
    print(f"\nhorizon                   today + {FUTURE_HORIZON_DAYS} days")
    print(f"papers scanned            {counts['scanned']}")
    print(f"{'cleared' if applied else 'would clear'}               {counts['affected']}")
    print(f"  published_date          {counts['published_date']}")
    print(f"  first_seen_online       {counts['first_seen_online']}")

    by_source = {k.removeprefix("source:"): v for k, v in counts.items() if k.startswith("source:")}
    if by_source:
        print("\nby source")
        for key, count in sorted(by_source.items(), key=lambda item: -item[1]):
            print(f"  {count:>8}  {key}")

    if examples:
        print("\nexamples")
        for value, title in examples:
            print(f"  {value}  {title}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="clear the implausible dates")
    parser.add_argument("--batch-size", type=int, default=1000, help="rows per commit")
    args = parser.parse_args(argv)

    configure_logging()
    with session_scope() as session:
        sanitise_stored(session, apply=args.apply, batch_size=args.batch_size)

    if not args.apply:
        print("\ndry run: nothing written. Re-run with --apply.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
