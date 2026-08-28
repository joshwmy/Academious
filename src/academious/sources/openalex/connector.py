"""OpenAlex connector: harvest + normalise behind the SourceConnector protocol."""

from __future__ import annotations

from collections.abc import Iterator
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

    def normalise(self, raw: RawRecord) -> PaperCandidate | None:
        return normalise_work(raw)

    def close(self) -> None:
        self._client.close()
