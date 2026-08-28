"""bioRxiv / medRxiv harvesting.

Two endpoints matter:

* `/details/{server}/{from}/{to}/{cursor}` - preprint metadata, 30 per page.
  Each record carries a `published` field holding the published DOI once the
  preprint has appeared in a journal.
* `/pubs/{server}/{from}/{to}/{cursor}` - 100 per page, and an authoritative
  preprint-DOI to published-DOI map.

The publication map is the reason this source is in Phase 1 at all. OpenAlex
stores a preprint and its published version as two separate works with two
different titles (verified), so no amount of title matching will ever link them.
This endpoint is the only free, authoritative link between the two.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, timedelta
from typing import Any

from academious.core.clock import utcnow
from academious.core.config import Settings, get_settings
from academious.core.errors import PermanentSourceError
from academious.core.http import SourceHttpClient
from academious.core.logging import get_logger
from academious.sources.base import HarvestPage, RawRecord

log = get_logger(__name__)

SOURCE_KEY = "biorxiv"
BASE_URL = "https://api.biorxiv.org"
DETAILS_PAGE_SIZE = 30
PUBS_PAGE_SIZE = 100
MAX_PAGES_PER_RUN = 400
DEFAULT_WINDOW_DAYS = 7


def _messages(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise PermanentSourceError(SOURCE_KEY, "expected a JSON object")
    messages = payload.get("messages") or [{}]
    return messages[0] if isinstance(messages[0], dict) else {}


def _total(message: dict[str, Any]) -> int:
    try:
        return int(message.get("total", 0))
    except (TypeError, ValueError):
        return 0


class BiorxivClient:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        http: SourceHttpClient | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._http = http or SourceHttpClient(SOURCE_KEY, settings=self._settings)

    def close(self) -> None:
        self._http.close()

    def _paginate(
        self, endpoint: str, server: str, start: date, end: date, page_size: int
    ) -> Iterator[tuple[list[dict[str, Any]], int, int]]:
        cursor = 0
        for _ in range(MAX_PAGES_PER_RUN):
            url = f"{BASE_URL}/{endpoint}/{server}/{start.isoformat()}/{end.isoformat()}/{cursor}"
            payload = self._http.get_json(url)
            message = _messages(payload)
            collection = payload.get("collection") or []
            total = _total(message)
            yield collection, cursor, total

            if not collection:
                return
            cursor += len(collection)
            if total:
                # `total` is authoritative when the API reports it.
                if cursor >= total:
                    return
            elif len(collection) < page_size:
                # No total: a short page is the only end-of-results signal.
                return

    def harvest_server(
        self, server: str, since: date | None, cursor: str | None
    ) -> Iterator[HarvestPage]:
        """Harvest preprint details for one server over a date window."""
        end = utcnow().date()
        start = since or (end - timedelta(days=DEFAULT_WINDOW_DAYS))
        if cursor:
            try:
                start = date.fromisoformat(cursor)
            except ValueError:
                log.warning("biorxiv.bad_cursor", cursor=cursor)

        for collection, offset, total in self._paginate(
            "details", server, start, end, DETAILS_PAGE_SIZE
        ):
            fetched_at = utcnow()
            records = [
                RawRecord(
                    source_key=SOURCE_KEY,
                    source_id=f"{item.get('doi')}v{item.get('version') or '1'}",
                    payload={**item, "server": item.get("server") or server},
                    fetched_at=fetched_at,
                )
                for item in collection
                if item.get("doi")
            ]
            log.info(
                "biorxiv.page", server=server, offset=offset, total=total, records=len(records)
            )
            # The window end is the resumption point for the next run.
            yield HarvestPage(records=records, next_cursor=end.isoformat())

    def harvest(self, since: date | None, cursor: str | None) -> Iterator[HarvestPage]:
        servers = self._settings.biorxiv_server_list
        for server in servers:
            server_cursor = cursor if server == servers[0] else None
            yield from self.harvest_server(server, since, server_cursor)

    def publication_links(
        self, server: str, since: date | None
    ) -> Iterator[tuple[str, str, dict[str, Any]]]:
        """Yield (preprint_doi, published_doi, record) for newly published preprints."""
        end = utcnow().date()
        start = since or (end - timedelta(days=DEFAULT_WINDOW_DAYS))
        for collection, _offset, _total in self._paginate(
            "pubs", server, start, end, PUBS_PAGE_SIZE
        ):
            for item in collection:
                preprint_doi = (item.get("preprint_doi") or "").strip()
                published_doi = (item.get("published_doi") or "").strip()
                if preprint_doi and published_doi:
                    yield preprint_doi, published_doi, item
