"""Re-apply the corpus-admission policy to papers already in the database.

When `ingest/scope.py` changes, the corpus does not change with it: records
admitted under the old policy stay where they are. This script closes that gap
by replaying every stored payload through its connector's `normalise` and the
current policy, and removing the papers that would no longer be admitted.

It is a *replay*, not a query. Nothing here knows what a StatPearls chapter
looks like; it asks the same code the ingest pipeline asks, which is what makes
it still correct after the next policy change rather than only this one.

    python scripts/prune_out_of_scope.py                  # report only
    python scripts/prune_out_of_scope.py --apply          # remove
    python scripts/prune_out_of_scope.py --source europepmc --apply

Safe by construction:

* **Dry run by default.** `--apply` is required before anything is written.
* **Raw payloads are never deleted.** `source_record.paper_id` is `SET NULL`, so
  the evidence survives and a later harvest hash-skips the record instead of
  refetching it.
* **A paper survives while any source still admits it.** One backed by both
  bioRxiv and Europe PMC is not removed because its Europe PMC record became
  inadmissible; only that link is cleared. Removing it would discard a preprint
  bioRxiv is still perfectly happy to supply.
* Identifiers, OA locations and embeddings go with the paper through the
  schema's own `ON DELETE CASCADE`, so no table is missed here and forgotten
  later.
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
from academious.db.models.support import SourceRecord
from academious.db.session import session_scope
from academious.ingest import scope
from academious.sources import registry
from academious.sources.base import RawRecord, SourceConnector

log = get_logger(__name__)


@dataclass(slots=True)
class PruneReport:
    papers_examined: int = 0
    papers_removed: int = 0
    records_detached: int = 0
    reasons: collections.Counter[str] = field(default_factory=collections.Counter)
    samples: list[str] = field(default_factory=list)

    def note(self, reason: str, title: str) -> None:
        self.reasons[reason] += 1
        if len(self.samples) < 15:
            self.samples.append(f"{reason:34} {title[:60]}")


def _connectors(source_keys: list[str]) -> dict[str, SourceConnector]:
    """Connectors are built for `normalise` only; no request is ever made."""
    return {key: registry.build(key) for key in source_keys}


def admissibility(connector: SourceConnector, record: SourceRecord) -> tuple[bool, str]:
    """Would this stored payload be admitted today? Returns (admitted, reason)."""
    raw = RawRecord(
        source_key=record.source_key,
        source_id=record.source_id,
        payload=record.payload,
        fetched_at=record.fetched_at,
    )
    candidate = connector.normalise(raw)
    if candidate is None:
        return False, "rejected_by_normalise"
    return scope.is_discovery_eligible(candidate.work_type), scope.describe(candidate.work_type)


def prune(session: Session, *, source_keys: list[str], apply: bool) -> PruneReport:
    report = PruneReport()
    connectors = _connectors(source_keys)

    records = session.execute(
        select(SourceRecord).where(
            SourceRecord.source_key.in_(source_keys), SourceRecord.paper_id.is_not(None)
        )
    ).scalars().all()

    by_paper: dict[uuid.UUID, list[SourceRecord]] = collections.defaultdict(list)
    for record in records:
        if record.paper_id is not None:
            by_paper[record.paper_id].append(record)

    for paper_id, paper_records in by_paper.items():
        paper = session.get(Paper, paper_id)
        if paper is None:
            continue
        report.papers_examined += 1

        verdicts = [
            admissibility(connectors[record.source_key], record) for record in paper_records
        ]
        if any(admitted for admitted, _ in verdicts):
            continue

        # Every record this scan covers is inadmissible. A record from a source
        # outside the scan still counts, so check the paper's whole provenance.
        other_sources = session.execute(
            select(SourceRecord).where(
                SourceRecord.paper_id == paper_id,
                SourceRecord.source_key.notin_(source_keys),
            )
        ).scalars().all()

        reason = verdicts[0][1]
        if other_sources:
            report.records_detached += len(paper_records)
            report.note(f"detached ({reason})", paper.title or "")
            if apply:
                for record in paper_records:
                    record.paper_id = None
            continue

        report.papers_removed += 1
        report.note(reason, paper.title or "")
        if apply:
            for record in paper_records:
                record.paper_id = None
            session.flush()
            session.delete(paper)

    return report


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = argparse.ArgumentParser(prog="prune_out_of_scope")
    parser.add_argument(
        "--source",
        action="append",
        dest="sources",
        choices=registry.ALL_SOURCES,
        help="Limit to one source; repeatable. Defaults to every source.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write the changes. Without it the script only reports them.",
    )
    args = parser.parse_args(argv)
    source_keys = args.sources or list(registry.ALL_SOURCES)

    with session_scope() as session:
        report = prune(session, source_keys=source_keys, apply=args.apply)
        if not args.apply:
            session.rollback()

    mode = "APPLIED" if args.apply else "DRY RUN - nothing was changed"
    print(f"\n{mode}")
    print(f"  sources examined:  {', '.join(source_keys)}")
    print(f"  papers examined:   {report.papers_examined}")
    print(f"  papers removed:    {report.papers_removed}")
    print(f"  records detached:  {report.records_detached}")
    if report.reasons:
        print("  by reason:")
        for reason, total in report.reasons.most_common():
            print(f"    {total:6d}  {reason}")
        print("  sample:")
        for sample in report.samples:
            print(f"    {sample}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
