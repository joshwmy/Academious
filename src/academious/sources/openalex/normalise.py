"""Pure OpenAlex payload -> PaperCandidate. No I/O.

Behaviours below were verified against live OpenAlex payloads captured in
tests/fixtures/openalex/, not inferred from documentation:

* Abstracts arrive as `abstract_inverted_index` and must be reconstructed.
  Many published records have no abstract at all, so an abstract cannot be an
  ingestion requirement.
* Preprints and their published versions are SEPARATE works with DIFFERENT
  titles (W4296130942 vs W4390571678), so title matching will never link them.
  Only the bioRxiv publication map does.
* `is_retracted` is a first-class boolean on the work.
* arXiv ids are not exposed as identifiers; the only link is an arxiv.org URL on
  a location record.
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

SOURCE_KEY = "openalex"

PREPRINT_TYPES = frozenset({"preprint"})
PEER_REVIEWED_TYPES = frozenset({"article", "review", "book-chapter", "conference-paper"})
# Not research output. Excluded at normalisation; see docs/ingestion.md.
EXCLUDED_TYPES = frozenset(
    {"paratext", "editorial", "letter", "erratum", "grant", "dataset", "peer-review"}
)


def reconstruct_abstract(inverted: dict[str, list[int]] | None) -> str | None:
    """Rebuild plain text from OpenAlex's inverted index."""
    if not inverted:
        return None
    positions: list[tuple[int, str]] = [
        (position, word) for word, spots in inverted.items() for position in spots
    ]
    if not positions:
        return None
    positions.sort(key=lambda pair: pair[0])
    return clean_display_text(" ".join(word for _, word in positions))


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _host_type(location: dict[str, Any]) -> str:
    source = location.get("source") or {}
    source_type = (source.get("type") or "").lower()
    if source_type == "repository":
        name = (source.get("display_name") or "").lower()
        if any(server in name for server in ("arxiv", "biorxiv", "medrxiv", "preprint")):
            return "preprint"
        return "repository"
    if source_type in {"journal", "conference", "book series", "ebook platform"}:
        return "publisher"
    return "unknown"


def _identifiers(work: dict[str, Any]) -> list[CandidateIdentifier]:
    found: list[CandidateIdentifier] = []
    seen: set[tuple[str, str]] = set()

    def add(id_type: IdType, raw: Any) -> None:
        value = idutil.normalise(id_type, raw)
        if value and (id_type, value) not in seen:
            seen.add((id_type, value))
            found.append(CandidateIdentifier(id_type=id_type, value=value))

    raw_ids = work.get("ids") or {}
    add(IdType.OPENALEX, raw_ids.get("openalex") or work.get("id"))
    add(IdType.DOI, raw_ids.get("doi") or work.get("doi"))
    add(IdType.PMID, raw_ids.get("pmid"))
    add(IdType.PMCID, raw_ids.get("pmcid"))
    add(IdType.MAG, raw_ids.get("mag"))

    # arXiv ids are only recoverable from location URLs.
    for location in work.get("locations") or []:
        for url_field in ("landing_page_url", "pdf_url"):
            arxiv_id = idutil.arxiv_id_from_url(location.get(url_field))
            if arxiv_id:
                add(IdType.ARXIV, arxiv_id)

    doi_text = str(work.get("doi") or "").lower()
    if "arxiv" in doi_text:
        add(IdType.ARXIV, doi_text)
    return found


def _authors(work: dict[str, Any]) -> list[CandidateAuthor]:
    authors: list[CandidateAuthor] = []
    for position, authorship in enumerate(work.get("authorships") or []):
        author = authorship.get("author") or {}
        name = clean_display_text(author.get("display_name"))
        if not name:
            continue
        authors.append(
            CandidateAuthor(
                name=name,
                position=position,
                orcid=author.get("orcid"),
                openalex_id=idutil.normalise_openalex(author.get("id")),
                affiliations=[
                    inst["display_name"]
                    for inst in (authorship.get("institutions") or [])
                    if inst.get("display_name")
                ],
            )
        )
    return authors


def _venue(work: dict[str, Any]) -> CandidateVenue | None:
    primary = work.get("primary_location") or {}
    source = primary.get("source") or {}
    name = clean_display_text(source.get("display_name"))
    if not name:
        return None
    return CandidateVenue(
        name=name,
        openalex_id=idutil.normalise_openalex(source.get("id")),
        issn_l=source.get("issn_l"),
        publisher=clean_display_text(source.get("host_organization_name")),
        venue_type=source.get("type"),
        is_oa=bool(source.get("is_oa")),
    )


def _locations(work: dict[str, Any]) -> list[CandidateLocation]:
    best_url = ((work.get("best_oa_location") or {}).get("landing_page_url")) or (
        (work.get("open_access") or {}).get("oa_url")
    )
    locations: list[CandidateLocation] = []
    seen: set[str] = set()
    for location in work.get("locations") or []:
        if not location.get("is_oa"):
            continue
        url = location.get("landing_page_url") or location.get("pdf_url")
        if not url or url in seen:
            continue
        seen.add(url)
        source = location.get("source") or {}
        locations.append(
            CandidateLocation(
                url=url,
                pdf_url=location.get("pdf_url"),
                host_type=_host_type(location),
                version=location.get("version") or "unknown",
                licence=location.get("license"),
                source_name=clean_display_text(source.get("display_name")),
                is_best=bool(best_url and url == best_url),
            )
        )
    return locations


def _topics(work: dict[str, Any]) -> list[dict[str, Any]]:
    topics = []
    for topic in work.get("topics") or []:
        if not topic.get("id"):
            continue
        topics.append(
            {
                "id": idutil.normalise_openalex(topic.get("id")) or topic["id"],
                "label": topic.get("display_name"),
                "score": topic.get("score"),
                "field": (topic.get("field") or {}).get("display_name"),
                "domain": (topic.get("domain") or {}).get("display_name"),
                "scheme": "openalex",
            }
        )
    return topics


def normalise(raw: RawRecord) -> PaperCandidate | None:
    """Returns None when the record is out of ingestion scope."""
    work = raw.payload
    title = clean_display_text(work.get("title") or work.get("display_name"))
    if not title:
        return None

    work_type = (work.get("type") or "").lower()
    if work_type in EXCLUDED_TYPES or work.get("is_paratext"):
        return None

    identifiers = _identifiers(work)
    if not identifiers:
        return None

    published = _parse_date(work.get("publication_date"))
    return PaperCandidate(
        source_key=SOURCE_KEY,
        source_id=raw.source_id,
        title=title,
        identifiers=identifiers,
        abstract=reconstruct_abstract(work.get("abstract_inverted_index")),
        authors=_authors(work),
        venue=_venue(work),
        published_date=published,
        first_seen_online=published,
        is_preprint=work_type in PREPRINT_TYPES,
        is_peer_reviewed=work_type in PEER_REVIEWED_TYPES,
        work_type=work_type or None,
        language=work.get("language"),
        topics=_topics(work),
        keywords=[
            keyword["display_name"]
            for keyword in (work.get("keywords") or [])
            if keyword.get("display_name")
        ],
        citation_count=work.get("cited_by_count"),
        oa_status=(work.get("open_access") or {}).get("oa_status") or "unknown",
        locations=_locations(work),
        is_retracted_hint=bool(work.get("is_retracted")),
    )
