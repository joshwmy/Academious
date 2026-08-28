"""Harvest jobs: the scheduled entry points for ingestion."""

from __future__ import annotations

from datetime import date, timedelta

from academious.core.clock import utcnow
from academious.core.config import get_settings
from academious.core.logging import get_logger
from academious.db.models.ops import IngestionRun
from academious.db.session import session_scope
from academious.ingest import retractions
from academious.ingest.pipeline import IngestPipeline, load_cursor
from academious.sources import registry
from academious.sources.biorxiv.client import BiorxivClient
from academious.sources.retractionwatch.client import RetractionWatchClient

log = get_logger(__name__)


def default_since() -> date:
    return utcnow().date() - timedelta(days=get_settings().initial_backfill_days)


def harvest_source(
    source_key: str,
    *,
    since: date | None = None,
    max_records: int | None = None,
    use_cursor: bool = True,
) -> IngestionRun:
    """Run one source end to end."""
    connector = registry.build(source_key)
    pipeline = IngestPipeline()
    try:
        with session_scope() as session:
            cursor = load_cursor(session, source_key) if use_cursor else None
            run = pipeline.run(
                session,
                connector,
                since=since or default_since(),
                cursor=cursor,
                max_records=max_records,
            )
            session.flush()
            return run
    finally:
        close = getattr(connector, "close", None)
        if callable(close):
            close()


def harvest_all(*, since: date | None = None, max_records: int | None = None) -> list[IngestionRun]:
    runs = []
    for source_key in registry.ALL_SOURCES:
        try:
            runs.append(harvest_source(source_key, since=since, max_records=max_records))
        except Exception:
            log.exception("harvest.source_crashed", source=source_key)
    return runs


def sync_retractions() -> tuple[int, int, int]:
    """Download Retraction Watch, store notices, apply status. (created, updated, changed)."""
    client = RetractionWatchClient()
    try:
        with session_scope() as session:
            created, updated = retractions.import_notices(session, client.fetch())
            session.flush()
            changed = retractions.apply_to_papers(session)
            log.info(
                "retractions.synced", created=created, updated=updated, papers_changed=changed
            )
            return created, updated, changed
    finally:
        client.close()


def link_publications(since: date | None = None) -> int:
    """Walk the bioRxiv/medRxiv publication map and create preprint_of relations."""
    from academious.ingest.relations import link_preprint_to_published

    settings = get_settings()
    client = BiorxivClient()
    linked = 0
    try:
        with session_scope() as session:
            for server in settings.biorxiv_server_list:
                for preprint_doi, published_doi, _record in client.publication_links(
                    server, since or default_since()
                ):
                    if link_preprint_to_published(
                        session, preprint_doi, published_doi, source_key="biorxiv_pubs"
                    ):
                        linked += 1
            log.info("relations.publication_links", linked=linked)
    finally:
        client.close()
    return linked
