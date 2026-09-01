"""Europe PMC harvesting.

Europe PMC is the biomedical half of the corpus: MEDLINE metadata, PMC
open-access articles, and preprint records, in one keyless REST API.

Three operational facts drive this client:

* **No key, no registration.** The Articles RESTful API is open, and no request
  ceiling is published, so `core.ratelimit` sets a deliberately conservative
  3 req/s - the same polite-pool convention used for Crossref.
* **The bulk prohibition is quoted verbatim on europepmc.org/developers:** "It
  is not permissible to use any kind of automated process to bulk download other
  content from Europe PMC." Their protocols exist to serve the open-access
  subset and metadata, so `ACADEMIOUS_EUROPEPMC_QUERIES` defaults to
  `OPEN_ACCESS:Y`. Widening it is an environment decision, and one that has to
  be made against those terms rather than by accident.
* **`cursorMark` belongs to one query.** It encodes a position in a result set,
  so a mark minted against last week's window - or against a different query
  expression, since all of them share one `source_cursor` row - is meaningless
  here and is not rejected by the API, merely misapplied. The stored cursor
  therefore carries both with it (`queryfingerprint|start|end|mark`) and is
  discarded when either moves. See `parse_cursor`.
"""

from __future__ import annotations

import hashlib
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

SOURCE_KEY = "europepmc"
BASE_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
# `core` results carry MeSH terms, affiliations, licences and full-text URLs.
# `lite` carries none of them, and a second fetch per record would cost far more
# than the larger page does.
RESULT_TYPE = "core"
# 1000 is the documented maximum. Core records run ~3 KB each, so 100 keeps a
# page around 300 KB - large enough that pagination is not the bottleneck.
PAGE_SIZE = 100
# Guards against an unbounded loop if the API ever returns a non-advancing mark.
MAX_PAGES_PER_RUN = 500
DEFAULT_WINDOW_DAYS = 7
FIRST_MARK = "*"
CURSOR_SEPARATOR = "|"


def query_fingerprint(expression: str) -> str:
    """Short stable digest of one query expression.

    A `cursorMark` is a position in *one* result set, and every expression this
    source harvests shares a single `source_cursor` row. Without this, a mark
    minted by one expression can be replayed against another: the API does not
    reject it, it simply resumes in the middle of a different result set and the
    records before that position are never seen.
    """
    return hashlib.sha256(expression.encode("utf-8")).hexdigest()[:8]


def format_cursor(expression: str, start: date, end: date, mark: str) -> str:
    """A resumable position: the query and window it belongs to, plus the mark."""
    return CURSOR_SEPARATOR.join(
        (query_fingerprint(expression), start.isoformat(), end.isoformat(), mark)
    )


def parse_cursor(cursor: str | None, expression: str) -> tuple[date, date, str] | None:
    """Reverse of `format_cursor`. None when there is nothing usable to resume.

    Returns None - meaning "open a fresh window" - for a cursor belonging to a
    different query expression, and for one written before the fingerprint
    existed. Re-opening a window costs only the page fetches, because unchanged
    payloads are hash-skipped by the pipeline; resuming the wrong result set
    would silently lose records instead.

    A cursor with an empty mark means "this window was harvested to the end", so
    it is deliberately not resumable either.
    """
    if not cursor:
        return None
    parts = cursor.split(CURSOR_SEPARATOR)
    if len(parts) != 4:
        log.warning("europepmc.bad_cursor", cursor=cursor)
        return None
    fingerprint, start_text, end_text, mark = parts
    if not mark:
        return None
    if fingerprint != query_fingerprint(expression):
        log.info("europepmc.cursor_query_changed", cursor=cursor, query=expression)
        return None
    try:
        return date.fromisoformat(start_text), date.fromisoformat(end_text), mark
    except ValueError:
        log.warning("europepmc.bad_cursor", cursor=cursor)
        return None


def build_query(expression: str, start: date, end: date) -> str:
    """Scope an expression to the update window it is being harvested for.

    UPDATE_DATE, not FIRST_PDATE: a paper whose MeSH terms, licence or retraction
    status changed today has to come back today, and its publication date has
    not moved.
    """
    return f"({expression}) AND UPDATE_DATE:[{start.isoformat()} TO {end.isoformat()}]"


class EuropePmcClient:
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

    def _params(self, query: str, mark: str) -> dict[str, Any]:
        return {
            "query": query,
            "format": "json",
            "resultType": RESULT_TYPE,
            "pageSize": PAGE_SIZE,
            "cursorMark": mark,
        }

    def _window(
        self, expression: str, since: date | None, cursor: str | None
    ) -> tuple[date, date, str]:
        resumed = parse_cursor(cursor, expression)
        if resumed is not None:
            return resumed
        end = utcnow().date()
        start = since or (end - timedelta(days=DEFAULT_WINDOW_DAYS))
        return start, end, FIRST_MARK

    def harvest_query(
        self, expression: str, since: date | None, cursor: str | None
    ) -> Iterator[HarvestPage]:
        """Cursor-paginate one query expression over one update window."""
        start, end, mark = self._window(expression, since, cursor)
        query = build_query(expression, start, end)

        for page_number in range(MAX_PAGES_PER_RUN):
            payload = self._http.get_json(BASE_URL, params=self._params(query, mark))
            if not isinstance(payload, dict):
                raise PermanentSourceError(SOURCE_KEY, "expected a JSON object")

            results = (payload.get("resultList") or {}).get("result") or []
            fetched_at = utcnow()
            records = [
                RawRecord(
                    source_key=SOURCE_KEY,
                    # `id` is only unique within a source: MED, PMC and PPR all
                    # number their own records.
                    source_id=f"{result.get('source')}:{result.get('id')}",
                    payload=result,
                    fetched_at=fetched_at,
                )
                for result in results
                if result.get("id") and result.get("source")
            ]

            following = payload.get("nextCursorMark") or ""
            exhausted = not results or not following or following == mark
            log.info(
                "europepmc.page",
                query=expression,
                page=page_number,
                records=len(records),
                total=payload.get("hitCount"),
            )
            # An exhausted window yields a cursor with no mark, so the next run
            # starts a new window rather than resuming a finished one.
            yield HarvestPage(
                records=records,
                next_cursor=format_cursor(
                    expression, start, end, "" if exhausted else following
                ),
            )

            if exhausted:
                return
            mark = following

        log.warning("europepmc.page_cap_reached", query=expression, cap=MAX_PAGES_PER_RUN)

    def harvest(self, since: date | None, cursor: str | None) -> Iterator[HarvestPage]:
        """Harvest every configured query expression in turn."""
        expressions = self._settings.europepmc_query_list
        for expression in expressions:
            # A cursor belongs to one expression; it is only valid for the first.
            expression_cursor = cursor if expression == expressions[0] else None
            yield from self.harvest_query(expression, since, expression_cursor)
