"""Test helpers: a connector that replays fixed pages with no network."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime

from academious.core.errors import TransientSourceError
from academious.sources.base import HarvestPage, PaperCandidate, RawRecord

WHEN = datetime(2026, 8, 28, tzinfo=UTC)


class StubConnector:
    """Replays prepared pages. Optionally fails after N pages."""

    def __init__(
        self,
        key: str,
        pages: list[list[RawRecord]],
        normaliser,
        *,
        fail_after_pages: int | None = None,
        cursors: list[str | None] | None = None,
    ) -> None:
        self.key = key
        self._pages = pages
        self._normaliser = normaliser
        self._fail_after_pages = fail_after_pages
        self._cursors = cursors or [None] * len(pages)
        self.harvest_calls = 0

    def harvest(self, since: date | None, cursor: str | None) -> Iterator[HarvestPage]:
        self.harvest_calls += 1
        for index, records in enumerate(self._pages):
            if self._fail_after_pages is not None and index >= self._fail_after_pages:
                raise TransientSourceError(self.key, "simulated source outage")
            yield HarvestPage(records=records, next_cursor=self._cursors[index])

    def normalise(self, raw: RawRecord) -> PaperCandidate | None:
        return self._normaliser(raw)


def raw(source_key: str, source_id: str, payload: dict) -> RawRecord:
    return RawRecord(source_key, source_id, payload, WHEN)


def make_paper(
    session,
    title,
    *,
    abstract=None,
    keywords=(),
    topics=(),
    published_date=None,
    is_preprint=False,
    is_peer_reviewed=True,
    oa_status="closed",
    retraction_status="none",
    language="en",
    doi=None,
):
    """Insert one Paper. Only the fields retrieval actually reads are exposed."""
    from academious.core.text import normalise_title
    from academious.db.models.paper import Paper

    paper = Paper(
        title=title,
        title_norm=normalise_title(title),
        abstract=abstract,
        canonical_doi=doi,
        authors=[],
        keywords=list(keywords),
        topics=[dict(topic) for topic in topics],
        published_date=published_date,
        published_year=published_date.year if published_date else None,
        is_preprint=is_preprint,
        is_peer_reviewed=is_peer_reviewed,
        oa_status=oa_status,
        retraction_status=retraction_status,
        language=language,
    )
    session.add(paper)
    session.flush()
    return paper
