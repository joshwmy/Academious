"""Pure bioRxiv/medRxiv record -> PaperCandidate.

The `published` field carries the published DOI once a preprint has appeared in
a journal. It is surfaced as `preprint_of_doi` so the ingest pipeline can create
a typed relation instead of merging two distinct works.

Licence codes are bioRxiv's own short forms, mapped here to SPDX-style strings.
Only genuinely open licences permit storing full text; `cc_no` and an empty
value do not (see docs/open-access.md).
"""

from __future__ import annotations

from datetime import date

from academious.core import ids as idutil
from academious.core.ids import IdType
from academious.core.text import clean_display_text
from academious.sources.base import (
    CandidateAuthor,
    CandidateIdentifier,
    CandidateLocation,
    CandidateVenue,
    PaperCandidate,
    RawRecord,
)

SOURCE_KEY = "biorxiv"

LICENCE_MAP = {
    "cc0": "cc0",
    "cc_by": "cc-by",
    "cc_by_sa": "cc-by-sa",
    "cc_by_nc": "cc-by-nc",
    "cc_by_nd": "cc-by-nd",
    "cc_by_nc_nd": "cc-by-nc-nd",
    # bioRxiv's "no reuse allowed without permission".
    "cc_no": "biorxiv-no-reuse",
}
STORABLE_LICENCES = frozenset({"cc0", "cc-by", "cc-by-sa"})

SERVER_LABELS = {"biorxiv": "bioRxiv", "medrxiv": "medRxiv"}


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def split_authors(raw: str | None) -> list[CandidateAuthor]:
    """bioRxiv gives one semicolon-separated string: 'Loot, C.; Millot, G.'."""
    if not raw:
        return []
    authors: list[CandidateAuthor] = []
    for position, chunk in enumerate(raw.split(";")):
        name = clean_display_text(chunk)
        if name:
            authors.append(CandidateAuthor(name=name, position=position))
    return authors


def map_licence(code: str | None) -> str | None:
    if not code:
        return None
    return LICENCE_MAP.get(code.strip().lower(), code.strip().lower())


def is_storable_licence(code: str | None) -> bool:
    """True only when the licence permits storing and processing full text."""
    return map_licence(code) in STORABLE_LICENCES


def normalise(raw: RawRecord) -> PaperCandidate | None:
    record = raw.payload
    doi = idutil.normalise_doi(record.get("doi"))
    title = clean_display_text(record.get("title"))
    if not doi or not title:
        return None

    server_key = (record.get("server") or "biorxiv").lower()
    server_label = SERVER_LABELS.get(server_key, record.get("server") or "bioRxiv")
    posted = _parse_date(record.get("date"))
    licence = map_licence(record.get("license"))
    published_doi = idutil.normalise_doi(record.get("published"))
    category = clean_display_text(record.get("category"))
    landing = f"https://www.{server_key}.org/content/{doi}v{record.get('version') or '1'}"

    return PaperCandidate(
        source_key=SOURCE_KEY,
        source_id=raw.source_id,
        title=title,
        identifiers=[CandidateIdentifier(id_type=IdType.DOI, value=doi)],
        abstract=clean_display_text(record.get("abstract")),
        authors=split_authors(record.get("authors")),
        venue=CandidateVenue(name=server_label, venue_type="preprint_server", is_oa=True),
        published_date=posted,
        first_seen_online=posted,
        is_preprint=True,
        is_peer_reviewed=False,
        work_type="preprint",
        language="en",
        topics=[{"id": category, "label": category, "scheme": "biorxiv"}] if category else [],
        keywords=[],
        oa_status="green",
        locations=[
            CandidateLocation(
                url=landing,
                pdf_url=f"{landing}.full.pdf",
                host_type="preprint",
                version="submittedVersion",
                licence=licence,
                source_name=server_label,
                is_best=True,
            )
        ],
        preprint_of_doi=published_doi,
    )
