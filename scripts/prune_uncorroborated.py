"""Remove papers founded solely on a general-purpose repository deposit.

`ingest/repositories.py` stops these arriving. This removes the ones already
here: on 2026-09-03 that was most of a 25,399-paper Zenodo slice, 24% of the
corpus, including 3,577 automated deposits sharing one first-author surname and
one week.

    python scripts/prune_uncorroborated.py                  # report only
    python scripts/prune_uncorroborated.py --apply          # remove

A paper is removed only when **every** source record it has is a deposit in a
repository that accepts anything. One record from a journal, a subject
repository or any other venue corroborates the work and the paper stays - which
is the whole point of the rule, and the reason this is not "delete everything
from Zenodo".

It is a **replay**, not a query: each stored payload goes back through its
connector's `normalise` and then through the same `is_general_repository` the
pipeline uses. That keeps the script correct after the next change to the rule
rather than only this one.

Safe by construction, following `prune_out_of_scope.py`:

* **Dry run by default.** `--apply` is required before anything is written.
* **Raw payloads are never deleted.** `source_record.paper_id` is `SET NULL`, so
  the evidence survives; a later pass could readmit these papers under a better
  rule without re-harvesting them.
* Identifiers, OA locations and embeddings follow the paper through the schema's
  own `ON DELETE CASCADE`.
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
from academious.db.models.support import SourceRecord, Venue
from academious.db.session import session_scope
from academious.ingest import repositories
from academious.sources import registry
from academious.sources.base import RawRecord, SourceConnector

log = get_logger(__name__)


@dataclass(slots=True)
class Report:
    papers_examined: int = 0
    papers_removed: int = 0
    records_detached: int = 0
    venues: collections.Counter[str] = field(default_factory=collections.Counter)
    samples: list[str] = field(default_factory=list)

    def note(self, venue: str, title: str) -> None:
        self.venues[venue] += 1
        if len(self.samples) < 15:
            self.samples.append(f"{venue[:28]:30} {title[:56]}")

    def print(self, *, applied: bool) -> None:
        print()
        print(f"papers examined           {self.papers_examined}")
        print(f"{'removed' if applied else 'would remove'}              {self.papers_removed}")
        print(f"source records detached   {self.records_detached}")
        if self.venues:
            print()
            print("by venue")
            for venue, count in self.venues.most_common(12):
                print(f"  {count:>8}  {venue}")
        if self.samples:
            print()
            print("samples")
            for line in self.samples:
                print(f"  {line}")


def _connectors() -> dict[str, SourceConnector]:
    """Built for `normalise` only; no request is ever made."""
    return {key: registry.build(key) for key in registry.CONNECTOR_FACTORIES}


def is_uncorroborated(connectors: dict[str, SourceConnector], records: list[SourceRecord]) -> bool:
    """True when every record for this paper is a general-repository deposit.

    A record that no longer normalises at all is *not* treated as corroborating:
    it is evidence of nothing. A record from a source this installation cannot
    build a connector for **is** treated as corroborating, because the safe
    error here is keeping a paper.
    """
    if not records:
        return False

    for record in records:
        connector = connectors.get(record.source_key)
        if connector is None:
            return False
        candidate = connector.normalise(
            RawRecord(
                source_key=record.source_key,
                source_id=record.source_id,
                payload=record.payload,
                fetched_at=record.fetched_at,
            )
        )
        if candidate is None:
            continue
        if not repositories.is_general_repository(candidate):
            return False
    return True


def prune(session: Session, *, apply: bool, batch_size: int) -> Report:
    report = Report()
    connectors = _connectors()
    after: uuid.UUID | None = None

    while True:
        stmt = select(Paper).order_by(Paper.id).limit(batch_size)
        if after is not None:
            stmt = stmt.where(Paper.id > after)
        batch = list(session.scalars(stmt))
        if not batch:
            break
        after = batch[-1].id

        ids = [paper.id for paper in batch]
        records = list(session.scalars(select(SourceRecord).where(SourceRecord.paper_id.in_(ids))))
        by_paper: dict[uuid.UUID, list[SourceRecord]] = collections.defaultdict(list)
        for record in records:
            if record.paper_id is not None:
                by_paper[record.paper_id].append(record)

        removed_any = False
        for paper in batch:
            report.papers_examined += 1
            paper_records = by_paper.get(paper.id, [])
            if not is_uncorroborated(connectors, paper_records):
                continue

            report.papers_removed += 1
            report.records_detached += len(paper_records)
            report.note(_venue_name(session, paper), paper.title)

            if apply:
                for record in paper_records:
                    record.paper_id = None
                session.delete(paper)
                removed_any = True

        if apply and removed_any:
            session.commit()

    return report


def _venue_name(session: Session, paper: Paper) -> str:
    if paper.venue_id is None:
        return "(no venue)"
    venue = session.get(Venue, paper.venue_id)
    return venue.name if venue else "(no venue)"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="remove the papers")
    parser.add_argument("--batch-size", type=int, default=500, help="papers per commit")
    args = parser.parse_args(argv)

    configure_logging()
    with session_scope() as session:
        report = prune(session, apply=args.apply, batch_size=args.batch_size)

    report.print(applied=args.apply)
    if not args.apply:
        print()
        print("dry run: nothing written. Re-run with --apply.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
