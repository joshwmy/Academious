"""bioRxiv / medRxiv connector."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date

from academious.sources.base import HarvestPage, PaperCandidate, RawRecord
from academious.sources.biorxiv.client import SOURCE_KEY, BiorxivClient
from academious.sources.biorxiv.normalise import normalise as normalise_record


class BiorxivConnector:
    key = SOURCE_KEY

    def __init__(self, client: BiorxivClient | None = None) -> None:
        self.client = client or BiorxivClient()

    def harvest(self, since: date | None, cursor: str | None) -> Iterator[HarvestPage]:
        yield from self.client.harvest(since, cursor)

    def normalise(self, raw: RawRecord) -> PaperCandidate | None:
        return normalise_record(raw)

    def close(self) -> None:
        self.client.close()
