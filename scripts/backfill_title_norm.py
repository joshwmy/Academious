"""Recompute `paper.title_norm` for papers already stored.

`normalise_title` deleted every character outside `a-z0-9`, so a Chinese,
Japanese, Korean, Cyrillic, Arabic or Greek title folded to the empty string.
That key is the dedup blocking key, and 3,819 papers in the live corpus held it
on 2026-09-03. Nothing merged wrongly - `find_fuzzy` refuses a key shorter than
12 characters - but those papers could only ever deduplicate by identifier, so
a second record of the same work stayed a second paper.

    python scripts/backfill_title_norm.py                 # report only
    python scripts/backfill_title_norm.py --apply         # rewrite the keys

The fix is in `core/text.py`; this applies it to rows written before it. A
recomputed key does not merge anything by itself - deduplication runs at
ingestion - so this makes future harvests able to match those papers rather
than retroactively folding them. Existing duplicates stay until something
re-ingests them.

Re-runnable and idempotent: a row whose key already matches is skipped.
"""

from __future__ import annotations

import argparse
import sys
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from academious.core.logging import configure_logging, get_logger
from academious.core.text import normalise_title
from academious.db.models.paper import Paper
from academious.db.session import session_scope

log = get_logger(__name__)


def backfill(session: Session, *, apply: bool, batch_size: int) -> dict[str, int]:
    """Rewrite stale keys, paging on the primary key.

    Paged rather than streamed because a `yield_per` cursor is closed by the
    commit inside the loop - the failure that hit `backfill_fields.py` first.
    """
    counts = {"scanned": 0, "changed": 0, "was_empty": 0, "now_empty": 0}
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
            recomputed = normalise_title(paper.title)
            if recomputed == paper.title_norm:
                continue

            counts["changed"] += 1
            if not paper.title_norm:
                counts["was_empty"] += 1
            if not recomputed:
                # A title that still folds to nothing is punctuation or digits
                # only. Worth seeing rather than silently rewriting.
                counts["now_empty"] += 1
            if len(examples) < 10:
                examples.append((paper.title[:48], recomputed[:48]))

            if apply:
                paper.title_norm = recomputed
                changed = True

        after = batch[-1].id
        if apply and changed:
            session.commit()
        else:
            for paper in batch:
                session.expunge(paper)

    _print(counts, examples, applied=apply)
    return counts


def _print(counts: dict[str, int], examples: list[tuple[str, str]], *, applied: bool) -> None:
    print()
    print(f"papers scanned            {counts['scanned']}")
    print(f"{'rewritten' if applied else 'would rewrite'}             {counts['changed']}")
    print(f"  key was empty           {counts['was_empty']}")
    print(f"  key still empty after   {counts['now_empty']}")
    if examples:
        print()
        print("examples (title -> new key)")
        for title, key in examples:
            print(f"  {title}  ->  {key}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write the recomputed keys")
    parser.add_argument("--batch-size", type=int, default=1000, help="rows per commit")
    args = parser.parse_args(argv)

    configure_logging()
    with session_scope() as session:
        backfill(session, apply=args.apply, batch_size=args.batch_size)

    if not args.apply:
        print()
        print("dry run: nothing written. Re-run with --apply.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
