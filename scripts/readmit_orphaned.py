"""Readmit stored records whose paper was removed, under the current rules.

Every prune in this project detaches rather than deletes: `prune_out_of_scope`
and `prune_uncorroborated` set `source_record.paper_id` to NULL and leave the
payload alone. That is what makes a policy reversible - but only if something
can act on it, and nothing could until this existed.

    python scripts/readmit_orphaned.py                  # report only
    python scripts/readmit_orphaned.py --apply          # re-create the papers
    python scripts/readmit_orphaned.py --source openalex --apply

**A re-harvest will not do this.** `process_record` skips a payload whose
content hash is unchanged, which is what makes harvesting cheap; an orphaned
record is byte-identical to the one already stored, so every future harvest
would skip it forever. What changed is the rule, not the record, so the replay
has to say so - hence `force=True`.

The immediate reason it exists: `prune_uncorroborated` first shipped judging a
record by its DOI prefix, and small journals routinely mint DOIs through
Zenodo. On the live corpus that condemned 458 papers in *Open MIND*, 24 in the
World Journal of Pharmacy, 20 on arXiv and a few hundred more - all genuinely
published, none of them deposits. The rule now lets the venue speak first, and
this brings those papers back.

It runs the same pipeline the harvest runs, so a readmitted paper is
deduplicated, merged, linked and enriched exactly as a freshly harvested one
would be. No network request is made: the payload is already here.
"""

from __future__ import annotations

import argparse
import collections
import logging
import sys

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from academious.core.logging import configure_logging, get_logger
from academious.db.models.support import SourceRecord
from academious.db.session import session_scope
from academious.ingest.pipeline import IngestPipeline, RunCounters
from academious.sources import registry
from academious.sources.base import RawRecord

log = get_logger(__name__)


def readmit(
    session: Session, *, sources: list[str], apply: bool, batch_size: int, limit: int | None
) -> dict[str, int]:
    counts: collections.Counter[str] = collections.Counter(
        {"examined": 0, "readmitted": 0, "still_rejected": 0}
    )
    pipeline = IngestPipeline()
    connectors = {key: registry.build(key) for key in sources}
    seen = 0

    while limit is None or seen < limit:
        take = batch_size if limit is None else min(batch_size, limit - seen)
        orphans = list(
            session.scalars(
                select(SourceRecord)
                .where(SourceRecord.paper_id.is_(None), SourceRecord.source_key.in_(sources))
                .order_by(SourceRecord.id)
                .offset(seen)
                .limit(take)
            )
        )
        if not orphans:
            break
        seen += len(orphans)

        for record in orphans:
            counts["examined"] += 1
            counters = RunCounters()
            pipeline.process_record(
                session,
                connectors[record.source_key],
                RawRecord(
                    source_key=record.source_key,
                    source_id=record.source_id,
                    payload=record.payload,
                    fetched_at=record.fetched_at,
                ),
                counters,
                force=True,
            )
            if record.paper_id is not None:
                counts["readmitted"] += 1
                counts[f"source:{record.source_key}"] += 1
            else:
                counts["still_rejected"] += 1

        if apply:
            session.commit()
        else:
            session.rollback()

    _print(counts, applied=apply)
    return dict(counts)


def _print(counts: collections.Counter[str], *, applied: bool) -> None:
    print()
    print(f"orphaned records examined {counts['examined']}")
    print(f"{'readmitted' if applied else 'would readmit'}            {counts['readmitted']}")
    print(f"still rejected            {counts['still_rejected']}")
    by_source = {k.removeprefix("source:"): v for k, v in counts.items() if k.startswith("source:")}
    if by_source:
        print()
        print("readmitted by source")
        for key, count in sorted(by_source.items(), key=lambda item: -item[1]):
            print(f"  {count:>8}  {key}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="re-create the papers")
    parser.add_argument(
        "--source",
        action="append",
        default=[],
        dest="sources",
        help="limit to these sources (default: all)",
    )
    parser.add_argument("--batch-size", type=int, default=200, help="records per commit")
    parser.add_argument("--limit", type=int, default=None, help="stop after this many records")
    parser.add_argument(
        "--verbose", action="store_true", help="log every record the pipeline decides on"
    )
    args = parser.parse_args(argv)

    sources = args.sources or list(registry.CONNECTOR_FACTORIES)

    configure_logging()
    if not args.verbose:
        # The replay walks every orphaned record, and the great majority are
        # the deposits that were correctly removed - each one logging a line
        # as the pipeline rejects it again. On a corpus with 29,000 of them
        # that buries the summary this script exists to print. WARNING and
        # above still comes through, so a real failure is not hidden.
        structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.WARNING))
    with session_scope() as session:
        readmit(
            session,
            sources=sources,
            apply=args.apply,
            batch_size=args.batch_size,
            limit=args.limit,
        )

    if not args.apply:
        print()
        print("dry run: rolled back. Re-run with --apply.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
