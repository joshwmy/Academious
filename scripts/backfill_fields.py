"""Derive `paper.fields` for papers already in the database.

Migration 0004 adds the column empty, because the mapping it holds lives in
Python and a data migration written today would freeze one version of it into
history. This script derives the column from each paper's stored topics through
`ingest/taxonomy.py`, and it is re-runnable: after a mapping change, run it
again and the corpus catches up.

    python scripts/backfill_fields.py                 # report only
    python scripts/backfill_fields.py --apply         # write
    python scripts/backfill_fields.py --apply --batch-size 2000

What it reports matters as much as what it writes. A field facet is only honest
if the share of the corpus it cannot reach is known, so the summary states how
many papers carry no field and lists the category labels that mapped to nothing
- which is how an unrecognised bioRxiv category or a new OpenAlex field becomes
a number rather than a quietly unclassified paper.

Safe by construction:

* **Dry run by default.** `--apply` is required before anything is written.
* **Idempotent.** A paper whose derived fields already match is skipped, so a
  second run writes nothing and a repeated run is free.
* **Batched and committed as it goes**, so an interrupted run leaves the rows it
  finished and the next run resumes without redoing them.
"""

from __future__ import annotations

import argparse
import collections
import sys
import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from academious.core.logging import configure_logging, get_logger
from academious.db.models.paper import Paper
from academious.db.session import session_scope
from academious.ingest.taxonomy import fields_for, unmapped_topics

log = get_logger(__name__)


@dataclass
class Report:
    papers: int = 0
    updated: int = 0
    unchanged: int = 0
    with_fields: int = 0
    without_fields: int = 0
    #: Papers carrying topics that mapped to nothing at all.
    unclassified_with_topics: int = 0
    #: Papers with no topics from any source: nothing to classify them by.
    without_topics: int = 0
    per_field: collections.Counter[str] = field(default_factory=collections.Counter)
    unmapped: collections.Counter[tuple[str, str]] = field(default_factory=collections.Counter)

    def observe(self, paper: Paper, derived: tuple[str, ...]) -> None:
        self.papers += 1
        topics = paper.topics or []
        if derived:
            self.with_fields += 1
            self.per_field.update(derived)
        else:
            self.without_fields += 1
            if topics:
                self.unclassified_with_topics += 1
            else:
                self.without_topics += 1
        for entry in unmapped_topics(topics):
            self.unmapped[entry] += 1

    def print(self, *, applied: bool) -> None:
        pct = (100 * self.with_fields / self.papers) if self.papers else 0.0
        print(f"\npapers scanned            {self.papers}")
        print(f"  with at least one field {self.with_fields} ({pct:.1f}%)")
        print(f"  without a field         {self.without_fields}")
        print(f"    - carried topics      {self.unclassified_with_topics}")
        print(f"    - carried no topics   {self.without_topics}")
        print(f"{'updated' if applied else 'would update'}                   {self.updated}")
        print(f"already correct           {self.unchanged}")

        if self.per_field:
            print("\npapers per field")
            for slug, count in self.per_field.most_common():
                print(f"  {count:>8}  {slug}")

        if self.unmapped:
            print("\nunmapped topic vocabulary (papers, scheme, value)")
            for (scheme, value), count in self.unmapped.most_common(40):
                print(f"  {count:>8}  {scheme:<10} {value}")
            if len(self.unmapped) > 40:
                print(f"  ... and {len(self.unmapped) - 40} more")


def backfill(session: Session, *, apply: bool, batch_size: int) -> Report:
    """Walk the corpus in batches, keyed on `paper.id`.

    Deliberately **not** one streaming cursor with commits inside it. A
    `yield_per` result set is a server-side cursor, and committing closes it
    mid-iteration - the loop then dies on its next fetch, part-way through a
    corpus it has half rewritten. Paging on the primary key means each batch is
    its own query, so a commit between batches is free and an interrupted run
    resumes from what it finished.
    """
    report = Report()
    after: uuid.UUID | None = None

    while True:
        stmt = select(Paper).order_by(Paper.id).limit(batch_size)
        if after is not None:
            stmt = stmt.where(Paper.id > after)
        batch = list(session.scalars(stmt))
        if not batch:
            break

        changed = False
        for paper in batch:
            derived = fields_for(paper.topics or [])
            report.observe(paper, derived)
            if list(derived) == list(paper.fields or []):
                report.unchanged += 1
                continue
            report.updated += 1
            if apply:
                paper.fields = list(derived)
                changed = True

        after = batch[-1].id
        if apply and changed:
            session.commit()
        else:
            # Detach this batch: holding every paper in the identity map turns
            # a 100k-row corpus into a memory problem. Only the batch, though -
            # expunge_all() would also detach objects the caller holds.
            for paper in batch:
                session.expunge(paper)

    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write the derived fields")
    parser.add_argument("--batch-size", type=int, default=1000, help="rows per commit")
    args = parser.parse_args(argv)

    configure_logging()
    with session_scope() as session:
        report = backfill(session, apply=args.apply, batch_size=args.batch_size)

    report.print(applied=args.apply)
    if not args.apply:
        print("\ndry run: nothing written. Re-run with --apply.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
