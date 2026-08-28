"""Worker CLI.

Scheduling is deliberately external - cron or systemd timers invoking these
subcommands. Explicit, greppable, and a failure is visible in the scheduler's
own logs rather than swallowed by an in-process scheduler.

    python -m academious.workers harvest --source all --since 2026-08-01
    python -m academious.workers retractions
    python -m academious.workers link-publications
"""

from __future__ import annotations

import argparse
import sys
from datetime import date

from academious.core.logging import configure_logging, get_logger
from academious.sources import registry
from academious.workers import harvest as harvest_worker

log = get_logger(__name__)


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected YYYY-MM-DD, got {value!r}") from None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="academious.workers")
    subcommands = parser.add_subparsers(dest="command", required=True)

    harvest = subcommands.add_parser("harvest", help="Harvest one source or all of them")
    harvest.add_argument("--source", default="all", choices=("all", *registry.ALL_SOURCES))
    harvest.add_argument("--since", type=_parse_date, default=None)
    harvest.add_argument("--max-records", type=int, default=None)
    harvest.add_argument(
        "--no-cursor",
        action="store_true",
        help="Ignore the stored cursor and harvest the window from scratch",
    )

    subcommands.add_parser("retractions", help="Sync Retraction Watch and apply statuses")

    links = subcommands.add_parser(
        "link-publications", help="Link bioRxiv/medRxiv preprints to published versions"
    )
    links.add_argument("--since", type=_parse_date, default=None)

    return parser


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    args = build_parser().parse_args(argv)

    if args.command == "harvest":
        if args.source == "all":
            runs = harvest_worker.harvest_all(since=args.since, max_records=args.max_records)
        else:
            runs = [
                harvest_worker.harvest_source(
                    args.source,
                    since=args.since,
                    max_records=args.max_records,
                    use_cursor=not args.no_cursor,
                )
            ]
        failed = [run for run in runs if run.status == "failed"]
        return 1 if failed else 0

    if args.command == "retractions":
        harvest_worker.sync_retractions()
        return 0

    if args.command == "link-publications":
        harvest_worker.link_publications(args.since)
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
