"""Connector registry. Adding a source means adding one line here."""

from __future__ import annotations

from collections.abc import Callable

from academious.sources.arxiv.connector import ArxivConnector
from academious.sources.base import SourceConnector
from academious.sources.biorxiv.connector import BiorxivConnector
from academious.sources.openalex.connector import OpenAlexConnector

CONNECTOR_FACTORIES: dict[str, Callable[[], SourceConnector]] = {
    "openalex": OpenAlexConnector,
    "arxiv": ArxivConnector,
    "biorxiv": BiorxivConnector,
}

ALL_SOURCES = tuple(CONNECTOR_FACTORIES)


def build(source_key: str) -> SourceConnector:
    try:
        return CONNECTOR_FACTORIES[source_key]()
    except KeyError:
        raise ValueError(
            f"unknown source {source_key!r}; known sources: {', '.join(ALL_SOURCES)}"
        ) from None
