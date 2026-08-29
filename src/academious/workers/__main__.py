"""Worker CLI.

Scheduling is deliberately external - cron or systemd timers invoking these
subcommands. Explicit, greppable, and a failure is visible in the scheduler's
own logs rather than swallowed by an in-process scheduler.

    python -m academious.workers harvest --source all --since 2026-08-01
    python -m academious.workers retractions
    python -m academious.workers link-publications
    python -m academious.workers embed --max-papers 500
    python -m academious.workers search "cancer genomics machine learning"
    python -m academious.workers evaluate --depth 20
    python -m academious.workers label --judge joshua
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from academious.core.logging import configure_logging, get_logger
from academious.sources import registry
from academious.workers import embed as embed_worker
from academious.workers import evaluate as evaluate_worker
from academious.workers import harvest as harvest_worker
from academious.workers import label as label_worker
from academious.workers import search as search_worker

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

    embed = subcommands.add_parser(
        "embed", help="Reap stale jobs, queue papers needing embeddings, then embed them"
    )
    embed.add_argument("--profile", default=None, help="Embedding profile key")
    embed.add_argument("--batch-size", type=int, default=None, help="Papers per job")
    embed.add_argument("--max-papers", type=int, default=None, help="Cap papers queued")
    embed.add_argument("--max-jobs", type=int, default=None, help="Cap jobs drained")
    embed.add_argument(
        "--enqueue-only", action="store_true", help="Queue work without loading the model"
    )
    embed.add_argument(
        "--pending", action="store_true", help="Report how many papers need work, then exit"
    )

    search = subcommands.add_parser("search", help="Search the corpus by research interest")
    search.add_argument("query")
    search.add_argument("--method", default="hybrid", choices=("lexical", "semantic", "hybrid"))
    search.add_argument("--limit", type=int, default=20)
    search.add_argument("--profile", default=None)
    search.add_argument("--from", dest="published_from", type=_parse_date, default=None)
    search.add_argument("--to", dest="published_to", type=_parse_date, default=None)
    search.add_argument("--source", action="append", default=[], dest="sources")
    search.add_argument("--field", action="append", default=[], dest="fields")
    search.add_argument(
        "--preprints", default="any", choices=("any", "only_preprints", "exclude_preprints")
    )
    search.add_argument("--peer-reviewed", action="store_true")
    search.add_argument("--open-access", action="store_true")
    search.add_argument(
        "--include-retracted",
        action="store_true",
        help="Retracted papers are excluded by default",
    )
    search.add_argument(
        "--only-flagged",
        action="store_true",
        help="Only papers carrying a retraction, correction or concern notice",
    )

    evaluate = subcommands.add_parser(
        "evaluate", help="Run the retrieval benchmark and refresh the judgment pool"
    )
    evaluate.add_argument("--profile", default=None)
    evaluate.add_argument("--depth", type=int, default=20)
    evaluate.add_argument("--domain", default="all", choices=("all", "biomedical", "computing"))
    evaluate.add_argument("--judgments", type=Path, default=None)
    evaluate.add_argument("--show-hits", type=int, default=5)
    evaluate.add_argument(
        "--no-write", action="store_true", help="Do not update the judgment pool file"
    )

    label = subcommands.add_parser(
        "label", help="Interactively grade the pooled papers a benchmark run produced"
    )
    label.add_argument("--judge", required=True, help="Recorded on every judgment")
    label.add_argument("--judgments", type=Path, default=None)
    label.add_argument("--query", default=None, help="Judge only one benchmark query")

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

    if args.command == "embed":
        if args.pending:
            print(embed_worker.pending_count(args.profile))
            return 0
        stats = embed_worker.run(
            args.profile,
            batch_size=args.batch_size,
            max_papers=args.max_papers,
            max_jobs=args.max_jobs,
            enqueue_only=args.enqueue_only,
        )
        log.info("embed.finished", **stats.as_dict())
        return 1 if stats.failed else 0

    if args.command == "search":
        search_worker.run(
            args.query,
            method=args.method,
            limit=args.limit,
            profile_key=args.profile,
            search_filters=search_worker.build_filters(
                published_from=args.published_from,
                published_to=args.published_to,
                sources=tuple(args.sources),
                fields=tuple(args.fields),
                preprints=args.preprints,
                peer_reviewed_only=args.peer_reviewed,
                open_access_only=args.open_access,
                include_retracted=args.include_retracted,
                only_flagged=args.only_flagged,
            ),
        )
        return 0

    if args.command == "label":
        label_worker.run(
            args.judgments or evaluate_worker.DEFAULT_JUDGMENTS_PATH,
            judge=args.judge,
            query_id=args.query,
        )
        return 0

    if args.command == "evaluate":
        evaluate_worker.run(
            profile_key=args.profile,
            depth=args.depth,
            domain=args.domain,
            judgments_path=args.judgments or evaluate_worker.DEFAULT_JUDGMENTS_PATH,
            write_pool=not args.no_write,
            show_hits=args.show_hits,
        )
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
