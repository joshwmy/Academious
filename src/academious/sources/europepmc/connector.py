"""Europe PMC connector: harvest + normalise behind the SourceConnector protocol."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date

from academious.sources.base import HarvestPage, PaperCandidate, RawRecord
from academious.sources.europepmc.client import SOURCE_KEY, EuropePmcClient
from academious.sources.europepmc.normalise import normalise as normalise_result


class EuropePmcConnector:
    key = SOURCE_KEY

    def __init__(self, client: EuropePmcClient | None = None) -> None:
        self._client = client or EuropePmcClient()

    def harvest(self, since: date | None, cursor: str | None) -> Iterator[HarvestPage]:
        yield from self._client.harvest(since, cursor)

    def normalise(self, raw: RawRecord) -> PaperCandidate | None:
        return normalise_result(raw)

    def close(self) -> None:
        self._client.close()
