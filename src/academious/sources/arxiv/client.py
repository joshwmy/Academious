"""arXiv harvesting over OAI-PMH.

arXiv's terms of use permit one request every three seconds from a single
connection, across all of a client's machines, and forbid re-serving PDFs or
source files from our own servers. The REST search API is therefore unusable for
volume; OAI-PMH is the sanctioned bulk interface and is what we use.

Records are converted from XML to a plain dict here so the raw payload can be
stored as JSONB. The conversion is lossless for the fields arXiv publishes.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from typing import Any

from defusedxml import ElementTree as SafeET

from academious.core.clock import utcnow
from academious.core.config import Settings, get_settings
from academious.core.errors import PermanentSourceError
from academious.core.http import SourceHttpClient
from academious.core.logging import get_logger
from academious.sources.base import HarvestPage, RawRecord

log = get_logger(__name__)

SOURCE_KEY = "arxiv"
BASE_URL = "https://export.arxiv.org/oai2"
OAI_NS = "{http://www.openarchives.org/OAI/2.0/}"
ARXIV_NS = "{http://arxiv.org/OAI/arXiv/}"
MAX_PAGES_PER_RUN = 200


def _text(element: Any, tag: str) -> str | None:
    found = element.find(tag)
    if found is None or found.text is None:
        return None
    return " ".join(found.text.split()) or None


def record_to_dict(record: Any) -> dict[str, Any] | None:
    """One <record> element -> plain dict. Returns None for deleted records."""
    header = record.find(f"{OAI_NS}header")
    if header is None:
        return None
    if (header.get("status") or "").lower() == "deleted":
        return None

    metadata = record.find(f"{OAI_NS}metadata")
    meta = metadata.find(f"{ARXIV_NS}arXiv") if metadata is not None else None
    if meta is None:
        return None

    authors = []
    authors_element = meta.find(f"{ARXIV_NS}authors")
    if authors_element is not None:
        for author in authors_element.findall(f"{ARXIV_NS}author"):
            authors.append(
                {
                    "keyname": _text(author, f"{ARXIV_NS}keyname"),
                    "forenames": _text(author, f"{ARXIV_NS}forenames"),
                    "affiliation": _text(author, f"{ARXIV_NS}affiliation"),
                }
            )

    return {
        "identifier": _text(header, f"{OAI_NS}identifier"),
        "datestamp": _text(header, f"{OAI_NS}datestamp"),
        "setSpec": [s.text for s in header.findall(f"{OAI_NS}setSpec") if s.text],
        "id": _text(meta, f"{ARXIV_NS}id"),
        "created": _text(meta, f"{ARXIV_NS}created"),
        "updated": _text(meta, f"{ARXIV_NS}updated"),
        "title": _text(meta, f"{ARXIV_NS}title"),
        "abstract": _text(meta, f"{ARXIV_NS}abstract"),
        "categories": _text(meta, f"{ARXIV_NS}categories"),
        "comments": _text(meta, f"{ARXIV_NS}comments"),
        "license": _text(meta, f"{ARXIV_NS}license"),
        "doi": _text(meta, f"{ARXIV_NS}doi"),
        "journal_ref": _text(meta, f"{ARXIV_NS}journal-ref"),
        "authors": authors,
    }


def parse_list_records(xml_text: str) -> tuple[list[dict[str, Any]], str | None]:
    """Parse a ListRecords response into (records, resumption_token)."""
    try:
        root = SafeET.fromstring(xml_text)
    except Exception as exc:  # defusedxml raises several parse error types
        raise PermanentSourceError(SOURCE_KEY, f"unparseable OAI-PMH XML: {exc}") from exc

    error = root.find(f"{OAI_NS}error")
    if error is not None:
        code = error.get("code") or "unknown"
        # An exhausted incremental window is a normal end state, not a failure.
        if code == "noRecordsMatch":
            return [], None
        raise PermanentSourceError(SOURCE_KEY, f"OAI-PMH error {code}: {error.text}")

    container = root.find(f"{OAI_NS}ListRecords")
    if container is None:
        container = root.find(f"{OAI_NS}GetRecord")
    if container is None:
        return [], None

    records = [
        parsed
        for record in container.findall(f"{OAI_NS}record")
        if (parsed := record_to_dict(record)) is not None
    ]

    token_element = container.find(f"{OAI_NS}resumptionToken")
    token = None
    if token_element is not None and token_element.text and token_element.text.strip():
        token = token_element.text.strip()
    return records, token


class ArxivClient:
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

    def _fetch(self, params: dict[str, Any]) -> tuple[list[dict[str, Any]], str | None]:
        return parse_list_records(self._http.get_text(BASE_URL, params=params))

    def harvest_set(
        self, set_spec: str, since: date | None, cursor: str | None
    ) -> Iterator[HarvestPage]:
        """Harvest one OAI set, following resumption tokens."""
        if cursor:
            # A resumption token is exclusive of every other argument by OAI-PMH rule.
            params: dict[str, Any] = {"verb": "ListRecords", "resumptionToken": cursor}
        else:
            params = {"verb": "ListRecords", "metadataPrefix": "arXiv", "set": set_spec}
            if since is not None:
                params["from"] = since.isoformat()

        for page_number in range(MAX_PAGES_PER_RUN):
            records, token = self._fetch(params)
            fetched_at = utcnow()
            page = HarvestPage(
                records=[
                    RawRecord(
                        source_key=SOURCE_KEY,
                        source_id=record["id"],
                        payload=record,
                        fetched_at=fetched_at,
                    )
                    for record in records
                    if record.get("id")
                ],
                next_cursor=token,
            )
            log.info("arxiv.page", set=set_spec, page=page_number, records=len(page.records))
            yield page

            if not token:
                return
            params = {"verb": "ListRecords", "resumptionToken": token}

        log.warning("arxiv.page_cap_reached", set=set_spec, cap=MAX_PAGES_PER_RUN)

    def harvest(self, since: date | None, cursor: str | None) -> Iterator[HarvestPage]:
        sets = self._settings.arxiv_set_list
        for set_spec in sets:
            set_cursor = cursor if set_spec == sets[0] else None
            yield from self.harvest_set(set_spec, since, set_cursor)
