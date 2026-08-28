"""OpenAlex harvesting.

OpenAlex is the canonical metadata spine: CC0, every discipline, and OA status,
topics, venue and citation counts in one record.

Two operational facts drive this client:

* A free API key has been required since 2026-02-13. Without one the quota is
  100 credits/day, which is demo-only. With one it is 100,000 credits/day.
* Credits, not requests, are the binding limit: a list call costs 10 credits, a
  singleton 1. 100k credits/day is therefore 10,000 list calls/day - ample at
  200 results per page, but only if we never loop singleton lookups.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from typing import Any

from academious.core.clock import utcnow
from academious.core.config import Settings, get_settings
from academious.core.errors import PermanentSourceError
from academious.core.http import SourceHttpClient
from academious.core.logging import get_logger
from academious.sources.base import HarvestPage, RawRecord

log = get_logger(__name__)

SOURCE_KEY = "openalex"
BASE_URL = "https://api.openalex.org/works"
PER_PAGE = 200
# Guards against an unbounded loop if the API ever returns a non-advancing cursor.
MAX_PAGES_PER_RUN = 500


class OpenAlexClient:
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

    def _params(self, filter_expr: str, since: date | None, cursor: str) -> dict[str, Any]:
        filters = [filter_expr]
        if since is not None:
            filters.append(f"from_updated_date:{since.isoformat()}")
        params: dict[str, Any] = {
            "filter": ",".join(filters),
            "per-page": PER_PAGE,
            "cursor": cursor,
            # Deterministic ordering so a resumed harvest cannot skip records.
            "sort": "updated_date:asc",
        }
        if self._settings.openalex_api_key:
            params["api_key"] = self._settings.openalex_api_key
        else:
            log.warning(
                "openalex.no_api_key",
                message="Running without an OpenAlex API key: quota is 100 credits/day",
            )
        return params

    def harvest_filter(
        self, filter_expr: str, since: date | None, cursor: str | None
    ) -> Iterator[HarvestPage]:
        """Cursor-paginate one filter expression."""
        next_cursor = cursor or "*"
        for page_number in range(MAX_PAGES_PER_RUN):
            payload = self._http.get_json(
                BASE_URL, params=self._params(filter_expr, since, next_cursor)
            )
            if not isinstance(payload, dict):
                raise PermanentSourceError(SOURCE_KEY, "expected a JSON object")

            results = payload.get("results") or []
            fetched_at = utcnow()
            records = [
                RawRecord(
                    source_key=SOURCE_KEY,
                    source_id=str(work.get("id") or ""),
                    payload=work,
                    fetched_at=fetched_at,
                )
                for work in results
                if work.get("id")
            ]

            meta = payload.get("meta") or {}
            following = meta.get("next_cursor")
            log.info(
                "openalex.page",
                filter=filter_expr,
                page=page_number,
                records=len(records),
                total=meta.get("count"),
            )

            yield HarvestPage(records=records, next_cursor=following)

            if not following or not results or following == next_cursor:
                return
            next_cursor = following

        log.warning("openalex.page_cap_reached", filter=filter_expr, cap=MAX_PAGES_PER_RUN)

    def harvest(self, since: date | None, cursor: str | None) -> Iterator[HarvestPage]:
        """Harvest every configured filter expression in turn.

        OpenAlex only supports OR within a single filter key, so the two approved
        launch domains are separate expressions harvested sequentially rather
        than one combined query.
        """
        expressions = [e.strip() for e in self._settings.openalex_filters.split(";") if e.strip()]
        for expression in expressions:
            # A cursor belongs to one expression; it is only valid for the first.
            expression_cursor = cursor if expression == expressions[0] else None
            yield from self.harvest_filter(expression, since, expression_cursor)
