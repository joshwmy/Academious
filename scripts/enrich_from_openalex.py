"""Give a subject field to papers that arrived without one, by asking OpenAlex.

    python scripts/enrich_from_openalex.py                    # report only
    python scripts/enrich_from_openalex.py --limit 500        # sample first
    python scripts/enrich_from_openalex.py --apply
    python scripts/enrich_from_openalex.py --apply --recheck  # ask again

46% of the live corpus carried no field on 2026-09-03, and all of it came from
Europe PMC, which classifies in MeSH only once MEDLINE has indexed the record -
months after the paper reached us. `backfill_fields.py` cannot help: it derives
fields from stored topics, and these papers have none. This script fetches the
missing classification from the one source that assigns it on publication, and
merges it through the ordinary ingestion pipeline. The reasoning is in
[`ingest/enrich.py`](../src/academious/ingest/enrich.py).

**A dry run still makes the requests.** What the pass would change is a fact
about OpenAlex's answer, not about our database, so it has to ask before it can
report; it then rolls the transaction back. `--limit` bounds a first look, and
because the pass is incremental a limited run is not wasted work.

**It is cheap, and the arithmetic is worth stating.** DOIs go out 50 to a
request, and a list call costs 10 credits: a 50,000-paper pass is 1,000 calls
and 10,000 credits against a daily quota of 100,000. Looked up one at a time it
would be 50,000 requests.

**Re-running is incremental, not a re-scan.** A paper that has been asked about
carries an OpenAlex source record afterwards, whether or not the answer helped,
so the next run skips it. That is what keeps the tail - DOIs OpenAlex does not
index, and works it holds without topics - from being paid for again every
time. `--recheck` deliberately ignores the exclusion, which is what to run
after upstream has had months to catch up.
"""

from __future__ import annotations

import argparse
import logging
import sys

import structlog

from academious.core.logging import configure_logging
from academious.db.session import session_scope
from academious.ingest.enrich import count_candidates, enrich_missing_fields
from academious.sources.openalex.client import MAX_OR_VALUES


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write the enrichment")
    parser.add_argument(
        "--batch-size",
        type=int,
        default=MAX_OR_VALUES,
        help=f"DOIs per request and per commit (max {MAX_OR_VALUES})",
    )
    parser.add_argument("--limit", type=int, default=None, help="stop after this many papers")
    parser.add_argument(
        "--recheck",
        action="store_true",
        help="include papers OpenAlex has already been asked about",
    )
    parser.add_argument(
        "--verbose", action="store_true", help="log every record the pipeline decides on"
    )
    args = parser.parse_args(argv)

    if not 1 <= args.batch_size <= MAX_OR_VALUES:
        parser.error(f"--batch-size must be between 1 and {MAX_OR_VALUES}")

    configure_logging()
    if not args.verbose:
        # A pass over tens of thousands of papers logs a line per record it
        # decides on, which buries the summary this script exists to print.
        # WARNING and above still comes through, so a real failure is not hidden.
        structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(logging.WARNING))

    with session_scope() as session:
        outstanding = count_candidates(session, recheck=args.recheck)
        print(f"papers with no field and a DOI: {outstanding}")
        if not outstanding:
            print("nothing to enrich.")
            return 0

        report = enrich_missing_fields(
            session,
            apply=args.apply,
            batch_size=args.batch_size,
            limit=args.limit,
            recheck=args.recheck,
        )

    report.print(applied=args.apply)
    if not args.apply:
        print()
        print("dry run: rolled back. Re-run with --apply.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
