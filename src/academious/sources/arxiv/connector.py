"""arXiv connector."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date

from academious.sources.arxiv.client import SOURCE_KEY, ArxivClient
from academious.sources.arxiv.normalise import normalise as normalise_record
from academious.sources.base import HarvestPage, PaperCandidate, RawRecord


class ArxivConnector:
    key = SOURCE_KEY

    def __init__(self, client: ArxivClient | None = None) -> None:
        self._client = client or ArxivClient()

    def harvest(self, since: date | None, cursor: str | None) -> Iterator[HarvestPage]:
        yield from self._client.harvest(since, cursor)

    def normalise(self, raw: RawRecord) -> PaperCandidate | None:
        return normalise_record(raw)

    def close(self) -> None:
        self._client.close()
