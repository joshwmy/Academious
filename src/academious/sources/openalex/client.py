"""OpenAlex harvesting.

OpenAlex is the canonical metadata spine: CC0, every discipline, and OA status,
topics, venue and citation counts in one record.

Two operational facts drive this client:

* A free API key has been required since 2026-02-13. Without one the quota is
  100 credits/day, which is demo-only. With one it is 100,000 credits/day.
* Credits, not requests, are the binding limit: a list call costs 10 credits, a
  singleton 1. 100k credits/day is therefore 10,000 list calls/day - ample at
  200 results per page, but only if we never loop singleton lookups.

The client does two jobs, and the second exists because of that second fact.
`harvest` walks a filter window forwards; `fetch_by_doi` answers "what does
OpenAlex know about these papers we already hold?" for a list of DOIs. Looked up
one at a time that would be a singleton per paper - cheaper per call, but a
50,000-paper enrichment pass is 50,000 requests. Batched into OR filters it is
1,000 list calls and 10,000 credits, which is a tenth of one day's quota.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
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
#: Values per OR-filter on a lookup. OpenAlex documents 50 as the ceiling, and a
#: batch is one list call whatever its size, so this is also the credit budget.
MAX_OR_VALUES = 50
#: A DOI carrying either of these cannot be sent: `|` separates OR values and `,`
#: separates filter keys, so an unlucky DOI would silently rewrite the query into
#: a different one that still returns 200. Such DOIs are skipped and reported.
_FILTER_DELIMITERS = ("|", ",")


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

    def _authenticate(self, params: dict[str, Any]) -> dict[str, Any]:
        """Attach the API key, or say once per call that there is none."""
        if self._settings.openalex_api_key:
            params["api_key"] = self._settings.openalex_api_key
        else:
            log.warning(
                "openalex.no_api_key",
                message="Running without an OpenAlex API key: quota is 100 credits/day",
            )
        return params

    def _params(self, filter_expr: str, since: date | None, cursor: str) -> dict[str, Any]:
        field = self._settings.openalex_incremental_field
        filters = [filter_expr]
        if since is not None:
            filters.append(f"from_{field}:{since.isoformat()}")
        return self._authenticate(
            {
                "filter": ",".join(filters),
                "per-page": PER_PAGE,
                "cursor": cursor,
                # Deterministic ordering so a resumed harvest cannot skip records.
                # Sorted on the same field the window filters, or the cursor walks
                # one ordering while the filter bounds another.
                "sort": f"{field}:asc",
            }
        )

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

    # --- lookup ---------------------------------------------------------------

    def lookup_params(self, dois: Sequence[str]) -> dict[str, Any]:
        """Query for one batch of DOIs. Separate from `_params` on purpose.

        A lookup is not a window: there is no `since`, no sort and no cursor,
        because at most `MAX_OR_VALUES` works can match and one page holds them.
        Reusing the harvest parameters would attach an ordering the API has to
        honour for no benefit.
        """
        return self._authenticate(
            {
                "filter": "doi:" + "|".join(f"https://doi.org/{doi}" for doi in dois),
                "per-page": PER_PAGE,
            }
        )

    def fetch_by_doi(self, dois: Iterable[str]) -> Iterator[RawRecord]:
        """Yield the OpenAlex work for each DOI it knows, in batches.

        Silent about DOIs it does not know: OpenAlex simply returns fewer
        results than were asked for, and there is no per-DOI error to report.
        The caller compares what it asked for against what came back - which is
        also how it learns that a paper is reachable from no other source.
        """
        for batch in _batched(dois, MAX_OR_VALUES):
            payload = self._http.get_json(BASE_URL, params=self.lookup_params(batch))
            if not isinstance(payload, dict):
                raise PermanentSourceError(SOURCE_KEY, "expected a JSON object")

            results = payload.get("results") or []
            fetched_at = utcnow()
            log.info("openalex.lookup", requested=len(batch), returned=len(results))
            for work in results:
                if work.get("id"):
                    yield RawRecord(
                        source_key=SOURCE_KEY,
                        source_id=str(work["id"]),
                        payload=work,
                        fetched_at=fetched_at,
                    )


def is_filterable_doi(doi: str) -> bool:
    """Whether a DOI can appear in an OR filter without changing its meaning."""
    return bool(doi) and not any(char in doi for char in _FILTER_DELIMITERS)


def _batched(dois: Iterable[str], size: int) -> Iterator[list[str]]:
    """Fixed-size batches of distinct, filterable DOIs, order preserved.

    Deduplicates because two papers in the corpus can carry the same DOI - the
    dedup pass keeps conflicting records apart - and a repeated OR value spends
    one of the fifty slots on nothing.
    """
    batch: list[str] = []
    seen: set[str] = set()
    for doi in dois:
        if not is_filterable_doi(doi) or doi in seen:
            continue
        seen.add(doi)
        batch.append(doi)
        if len(batch) == size:
            yield batch
            batch = []
    if batch:
        yield batch
