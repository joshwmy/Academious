"""Ingestion orchestration: harvest -> normalise -> canonicalise -> enrich.

Idempotency is a property of this module, not an accident. Every raw record is
stored once per (source_key, source_id) with a content hash; a re-run whose
payload has not changed is counted as skipped and does no further work. Re-runs
are therefore cheap and safe, which is what makes an interrupted harvest
recoverable by simply running it again.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from academious.core.clock import utcnow
from academious.core.config import Settings, get_settings
from academious.core.errors import SourceError
from academious.core.ids import IdType
from academious.core.logging import get_logger
from academious.db.models.ops import IngestionRun, RunStatus, SourceCursor
from academious.db.models.paper import Paper, PaperIdentifier
from academious.db.models.support import SourceRecord, Venue
from academious.ingest import canonicalise, dates, oa, relations, scope
from academious.ingest.merge import apply_candidate
from academious.sources.base import PaperCandidate, RawRecord, SourceConnector

log = get_logger(__name__)


@dataclass(slots=True)
class RunCounters:
    records_fetched: int = 0
    records_skipped: int = 0
    papers_created: int = 0
    papers_updated: int = 0
    papers_merged: int = 0
    relations_created: int = 0
    oa_locations_created: int = 0
    errors: int = 0
    error_samples: list[str] = field(default_factory=list)

    def record_error(self, message: str) -> None:
        self.errors += 1
        if len(self.error_samples) < 10:
            self.error_samples.append(message[:300])


def content_hash(payload: dict[str, object]) -> str:
    """Stable hash of a payload, insensitive to key ordering."""
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _upsert_venue(session: Session, candidate: PaperCandidate) -> Venue | None:
    if candidate.venue is None:
        return None
    venue_data = candidate.venue
    existing = None
    if venue_data.openalex_id:
        existing = session.execute(
            select(Venue).where(Venue.openalex_id == venue_data.openalex_id)
        ).scalars().first()
    if existing is None:
        existing = session.execute(
            select(Venue).where(Venue.name == venue_data.name)
        ).scalars().first()
    if existing is None:
        existing = Venue(
            openalex_id=venue_data.openalex_id,
            issn_l=venue_data.issn_l,
            name=venue_data.name,
            publisher=venue_data.publisher,
            venue_type=venue_data.venue_type,
            is_oa=venue_data.is_oa,
        )
        session.add(existing)
        session.flush()
    return existing


def _sync_identifiers(session: Session, paper: Paper, candidate: PaperCandidate) -> None:
    """Attach any identifier the candidate carries that the paper lacks."""
    existing = {(i.id_type, i.value) for i in paper.identifiers}
    for identifier in candidate.identifiers:
        key = (identifier.id_type.value, identifier.value)
        if key in existing:
            continue
        # Another paper may already own it; find_by_identifiers has run, so this
        # only happens when that paper was kept separate as a genuine conflict.
        owner = session.get(PaperIdentifier, key)
        if owner is not None:
            continue
        row = PaperIdentifier(
            id_type=identifier.id_type.value,
            value=identifier.value,
            paper_id=paper.id,
            source_key=candidate.source_key,
        )
        session.add(row)
        paper.identifiers.append(row)
        existing.add(key)

    if not paper.canonical_doi:
        dois = candidate.identifier_values(IdType.DOI)
        if dois:
            paper.canonical_doi = dois[0]


class IngestPipeline:
    """Runs one source end to end and records metrics for the run."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def process_record(
        self, session: Session, connector: SourceConnector, raw: RawRecord, counters: RunCounters
    ) -> None:
        digest = content_hash(raw.payload)
        stored = session.execute(
            select(SourceRecord).where(
                SourceRecord.source_key == raw.source_key,
                SourceRecord.source_id == raw.source_id,
            )
        ).scalars().first()

        if stored is not None and stored.content_hash == digest:
            counters.records_skipped += 1
            return

        candidate = connector.normalise(raw)
        # Corpus admission is one decision for every source (ingest/scope.py).
        # Connectors apply it while normalising, because that is the earliest
        # point the work type is known; it is enforced again here so a source
        # that forgets cannot quietly widen the corpus.
        if candidate is not None and not scope.is_discovery_eligible(candidate.work_type):
            log.info(
                "ingest.out_of_scope",
                source=raw.source_key,
                source_id=raw.source_id,
                reason=scope.describe(candidate.work_type),
            )
            candidate = None
        # A publication date the feed cannot believe is cleared here, for the
        # same reason admission is decided here: one rule, every source. See
        # ingest/dates.py - the ordering makes a wrong date a front-page claim.
        if candidate is not None:
            candidate = dates.sanitise(candidate)
        if candidate is None:
            counters.records_skipped += 1
            if stored is None:
                session.add(
                    SourceRecord(
                        source_key=raw.source_key,
                        source_id=raw.source_id,
                        payload=raw.payload,
                        content_hash=digest,
                        fetched_at=raw.fetched_at,
                    )
                )
            return

        match = canonicalise.resolve(session, candidate, self._settings)
        counters.papers_merged += len(match.merged_paper_ids)
        if match.created:
            counters.papers_created += 1

        _sync_identifiers(session, match.paper, candidate)
        venue = _upsert_venue(session, candidate)
        if venue is not None and match.paper.venue_id is None:
            match.paper.venue_id = venue.id

        changed = apply_candidate(match.paper, candidate)
        counters.oa_locations_created += oa.apply_locations(
            session, match.paper, candidate.locations, discovered_via=candidate.source_key
        )

        if candidate.preprint_of_doi:
            linked = relations.link_preprint_to_published(
                session,
                candidate.primary_doi,
                candidate.preprint_of_doi,
                source_key=candidate.source_key,
            )
            if linked:
                counters.relations_created += 1

        if changed and not match.created:
            counters.papers_updated += 1

        if stored is None:
            session.add(
                SourceRecord(
                    source_key=raw.source_key,
                    source_id=raw.source_id,
                    paper_id=match.paper.id,
                    payload=raw.payload,
                    content_hash=digest,
                    fetched_at=raw.fetched_at,
                )
            )
        else:
            stored.payload = raw.payload
            stored.content_hash = digest
            stored.paper_id = match.paper.id
            stored.fetched_at = raw.fetched_at

    def run(
        self,
        session: Session,
        connector: SourceConnector,
        *,
        since: date | None = None,
        cursor: str | None = None,
        max_records: int | None = None,
    ) -> IngestionRun:
        """Harvest and ingest one source. Always writes an IngestionRun row."""
        run = IngestionRun(
            source_key=connector.key,
            status=RunStatus.RUNNING.value,
            started_at=utcnow(),
            cursor_start=cursor,
        )
        session.add(run)
        session.flush()

        counters = RunCounters()
        last_cursor = cursor
        failed = False

        try:
            for page in connector.harvest(since, cursor):
                for raw in page.records:
                    counters.records_fetched += 1
                    try:
                        self.process_record(session, connector, raw, counters)
                    except SourceError as exc:
                        counters.record_error(str(exc))
                        log.warning("ingest.record_failed", source=connector.key, error=str(exc))
                    except Exception as exc:  # noqa: BLE001 - one bad record must not stop a run
                        counters.record_error(f"{type(exc).__name__}: {exc}")
                        log.exception("ingest.record_error", source=connector.key)
                last_cursor = page.next_cursor or last_cursor
                session.flush()
                if max_records is not None and counters.records_fetched >= max_records:
                    log.info("ingest.max_records_reached", source=connector.key, cap=max_records)
                    break
        except SourceError as exc:
            failed = True
            counters.record_error(str(exc))
            log.error("ingest.source_failed", source=connector.key, error=str(exc))

        run.finished_at = utcnow()
        run.cursor_end = last_cursor
        run.records_fetched = counters.records_fetched
        run.records_skipped = counters.records_skipped
        run.papers_created = counters.papers_created
        run.papers_updated = counters.papers_updated
        run.papers_merged = counters.papers_merged
        run.relations_created = counters.relations_created
        run.oa_locations_created = counters.oa_locations_created
        run.errors = counters.errors
        run.detail = {"error_samples": counters.error_samples}
        if failed:
            run.status = RunStatus.FAILED.value
        elif counters.errors:
            run.status = RunStatus.PARTIAL.value
        else:
            run.status = RunStatus.SUCCEEDED.value

        # Only advance the stored cursor when the run did not fail outright, so a
        # failed harvest is retried from where it left off rather than skipped.
        if not failed and last_cursor is not None:
            _save_cursor(session, connector.key, last_cursor)

        log.info(
            "ingest.run_finished",
            source=connector.key,
            status=run.status,
            fetched=run.records_fetched,
            created=run.papers_created,
            updated=run.papers_updated,
            merged=run.papers_merged,
            skipped=run.records_skipped,
            errors=run.errors,
        )
        return run


def _save_cursor(session: Session, source_key: str, cursor: str) -> None:
    existing = session.get(SourceCursor, source_key)
    now = utcnow()
    if existing is None:
        session.add(
            SourceCursor(
                source_key=source_key, cursor=cursor, last_success_at=now, updated_at=now
            )
        )
    else:
        existing.cursor = cursor
        existing.last_success_at = now
        existing.updated_at = now


def load_cursor(session: Session, source_key: str) -> str | None:
    existing = session.get(SourceCursor, source_key)
    return existing.cursor if existing else None
