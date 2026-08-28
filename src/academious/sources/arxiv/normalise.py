"""Pure arXiv OAI record -> PaperCandidate.

Two facts verified against a live record (tests/fixtures/arxiv/):

* Most arXiv papers carry arXiv's own non-exclusive licence, not a CC licence.
  We therefore link to arXiv and never store or re-serve full text.
* Older papers have no DOI at all, and arXiv's newer DOI prefix (10.65215/...)
  is opaque - it cannot be derived from the arXiv id. Cross-source matching to
  OpenAlex therefore relies on the arXiv id when OpenAlex exposes it in a URL,
  and falls through to fuzzy title matching otherwise.
"""

from __future__ import annotations

from datetime import date
from typing import Any

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

SOURCE_KEY = "arxiv"
ABS_URL = "https://arxiv.org/abs/{arxiv_id}"
PDF_URL = "https://arxiv.org/pdf/{arxiv_id}"
CC_LICENCE_MARKERS = ("creativecommons.org", "publicdomain")


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _author_name(author: dict[str, Any]) -> str | None:
    forenames = (author.get("forenames") or "").strip()
    keyname = (author.get("keyname") or "").strip()
    if keyname and forenames:
        return f"{forenames} {keyname}"
    return keyname or forenames or None


def is_open_licence(licence: str | None) -> bool:
    """True only for licences that permit storing and processing full text."""
    if not licence:
        return False
    lowered = licence.lower()
    return any(marker in lowered for marker in CC_LICENCE_MARKERS)


def normalise(raw: RawRecord) -> PaperCandidate | None:
    record = raw.payload
    arxiv_id = idutil.normalise_arxiv(record.get("id"))
    title = clean_display_text(record.get("title"))
    if not arxiv_id or not title:
        return None

    identifiers = [CandidateIdentifier(id_type=IdType.ARXIV, value=arxiv_id)]
    doi = idutil.normalise_doi(record.get("doi"))
    if doi:
        identifiers.append(CandidateIdentifier(id_type=IdType.DOI, value=doi))

    authors = [
        CandidateAuthor(name=name, position=position)
        for position, author in enumerate(record.get("authors") or [])
        if (name := _author_name(author))
    ]

    categories = (record.get("categories") or "").split()
    licence = record.get("license")
    journal_ref = clean_display_text(record.get("journal_ref"))
    created = _parse_date(record.get("created"))

    return PaperCandidate(
        source_key=SOURCE_KEY,
        source_id=arxiv_id,
        title=title,
        identifiers=identifiers,
        abstract=clean_display_text(record.get("abstract")),
        authors=authors,
        venue=CandidateVenue(name="arXiv", venue_type="preprint_server", is_oa=True),
        published_date=created,
        first_seen_online=created,
        # A journal-ref means the work has appeared somewhere peer reviewed, but
        # the arXiv copy itself is still the preprint record.
        is_preprint=True,
        is_peer_reviewed=bool(journal_ref),
        work_type="preprint",
        language="en",
        topics=[
            {"id": category, "label": category, "scheme": "arxiv"} for category in categories
        ],
        keywords=[],
        oa_status="green",
        locations=[
            CandidateLocation(
                url=ABS_URL.format(arxiv_id=arxiv_id),
                pdf_url=PDF_URL.format(arxiv_id=arxiv_id),
                host_type="preprint",
                version="submittedVersion",
                licence=licence,
                source_name="arXiv",
                is_best=True,
            )
        ],
    )
