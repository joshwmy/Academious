"""OpenAlex connector: harvest + normalise behind the SourceConnector protocol.

`fetch_by_doi` is deliberately *not* part of that protocol. Every source can be
harvested; only a source that indexes the whole literature by DOI can be asked
about a paper another source found first. Widening `SourceConnector` for it
would oblige three connectors to implement a method that has no meaning for
them. See `ingest/enrich.py` for what asks.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from datetime import date

from academious.sources.base import HarvestPage, PaperCandidate, RawRecord
from academious.sources.openalex.client import SOURCE_KEY, OpenAlexClient
from academious.sources.openalex.normalise import normalise as normalise_work


class OpenAlexConnector:
    key = SOURCE_KEY

    def __init__(self, client: OpenAlexClient | None = None) -> None:
        self._client = client or OpenAlexClient()

    def harvest(self, since: date | None, cursor: str | None) -> Iterator[HarvestPage]:
        yield from self._client.harvest(since, cursor)

    def fetch_by_doi(self, dois: Iterable[str]) -> Iterator[RawRecord]:
        """Works OpenAlex holds for these DOIs, batched into OR filters."""
        yield from self._client.fetch_by_doi(dois)

    def normalise(self, raw: RawRecord) -> PaperCandidate | None:
        return normalise_work(raw)

    def close(self) -> None:
        self._client.close()
