"""Pure Europe PMC result -> PaperCandidate. No I/O.

Behaviours below were verified against live payloads captured in
tests/fixtures/europepmc/, not inferred from documentation:

* `pubTypeList` mixes two vocabularies - MEDLINE ("Journal Article", "Review",
  "Retracted Publication") and JATS ("research-article", "correction"). A record
  routinely carries both, so scope is decided by looking for a research type
  first and only then for an excluded one.
* A **retraction notice** ("Retraction of Publication") is a different document
  from the **retracted article** ("Retracted Publication"). The first is not
  research output; the second is a paper that must be kept and flagged.
* `license` is populated on records that are not open access at all
  (`article_subscription.json`: `cc by`, `isOpenAccess` `N`, and the only URL is
  a subscription DOI link). Licence therefore never decides OA status here.
* Abstracts contain markup - `<sup>`, `<h4>` - and preprint abstracts contain
  mojibake from the source. Tags are stripped; the mojibake is left alone,
  because guessing an encoding fix would corrupt text that is merely unusual.
* `author.fullName` is the MEDLINE abbreviation ("Jumper J"). `firstName` and
  `lastName` are present alongside it and are preferred, because a surname
  overlap check against another source's full names is what dedup runs on.
* A "Preprint of" entry in `commentCorrectionList` is a **heuristic** link: the
  payload says so in its own `note` field ("Link created based on a title-first
  author match") and carries a citation string, not a DOI. It is deliberately
  not turned into a preprint relation - see docs/sources.md.
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

SOURCE_KEY = "europepmc"

#: Databases whose records are peer-reviewed literature. PPR (preprints) and
#: books are deliberately absent.
PEER_REVIEWED_DATABASES = frozenset({"MED", "PMC", "AGR", "CBA"})
PREPRINT_DATABASE = "PPR"

#: Any of these means the record is research output, whatever else it carries.
RESEARCH_TYPES = frozenset(
    {
        "journal article",
        "research-article",
        "review",
        "review-article",
        "case reports",
        "case-report",
        "case-study",
        "clinical trial",
        "clinical trial protocol",
        "randomized controlled trial",
        "observational study",
        "meta-analysis",
        "systematic review",
        "preprint",
        "book chapter",
        "chapter",
    }
)
#: Not research output. Excluded at normalisation; see docs/ingestion.md.
EXCLUDED_TYPES = frozenset(
    {
        "published erratum",
        "erratum",
        "correction",
        "retraction of publication",
        "retraction notice",
        "expression of concern",
        "editorial",
        "editorial-material",
        "comment",
        "letter",
        "news",
        "obituary",
        "abstract",
        "congress",
    }
)
RETRACTED_TYPES = frozenset({"retracted publication", "retracted-article"})
REVIEW_TYPES = frozenset({"review", "review-article", "systematic review"})

#: Full-text URLs worth recording. "Subscription required" is not a location a
#: reader can be sent to, so it is dropped rather than stored as a dead end.
FREE_AVAILABILITY_CODES = frozenset({"OA", "F"})
#: `site` values that are repository copies rather than the publisher's own.
REPOSITORY_SITES = frozenset({"europe_pmc", "pubmedcentral", "ncbi_bookshelf"})
#: The site whose copy is most certain to stay reachable.
PREFERRED_SITE = "Europe_PMC"

#: Europe PMC reports ISO 639-2; the rest of the corpus stores ISO 639-1.
LANGUAGE_MAP = {
    "eng": "en",
    "fre": "fr",
    "fra": "fr",
    "ger": "de",
    "deu": "de",
    "spa": "es",
    "ita": "it",
    "por": "pt",
    "rus": "ru",
    "chi": "zh",
    "zho": "zh",
    "jpn": "ja",
    "kor": "ko",
    "dut": "nl",
    "nld": "nl",
    "pol": "pl",
    "tur": "tr",
}


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _pub_types(result: dict[str, Any]) -> set[str]:
    types = (result.get("pubTypeList") or {}).get("pubType") or []
    return {str(pub_type).strip().lower() for pub_type in types if pub_type}


def map_language(code: str | None) -> str | None:
    """ISO 639-2 to ISO 639-1 where known; the raw code otherwise."""
    if not code:
        return None
    folded = code.strip().lower()
    return LANGUAGE_MAP.get(folded, folded or None)


def map_licence(code: str | None) -> str | None:
    """'cc by-nc-nd' -> 'cc-by-nc-nd', matching the SPDX-style form stored."""
    if not code:
        return None
    folded = " ".join(code.strip().lower().split())
    return folded.replace(" ", "-") or None


def is_in_scope(result: dict[str, Any]) -> bool:
    """Research output, by publication type. Notices and paratext are not."""
    types = _pub_types(result)
    if types & RESEARCH_TYPES:
        return True
    # Unlabelled records are kept: Europe PMC leaves pubTypeList empty on some
    # preprints, and dropping them would silently lose whole sources.
    return not types & EXCLUDED_TYPES


def work_type_of(result: dict[str, Any], *, is_preprint: bool) -> str:
    if is_preprint:
        return "preprint"
    types = _pub_types(result)
    if types & REVIEW_TYPES:
        return "review"
    if result.get("hasBook") == "Y" or types & {"chapter", "book chapter"}:
        return "book-chapter"
    return "article"


def _identifiers(result: dict[str, Any]) -> list[CandidateIdentifier]:
    found: list[CandidateIdentifier] = []
    seen: set[tuple[str, str]] = set()

    def add(id_type: IdType, raw: Any) -> None:
        value = idutil.normalise(id_type, raw)
        if value and (id_type, value) not in seen:
            seen.add((id_type, value))
            found.append(CandidateIdentifier(id_type=id_type, value=value))

    add(IdType.DOI, result.get("doi"))
    add(IdType.PMID, result.get("pmid"))
    add(IdType.PMCID, result.get("pmcid"))
    return found


def _author_name(author: dict[str, Any]) -> str | None:
    first = clean_display_text(author.get("firstName"))
    last = clean_display_text(author.get("lastName"))
    if first and last:
        return f"{first} {last}"
    return clean_display_text(author.get("fullName") or last or first)


def _affiliations(author: dict[str, Any]) -> list[str]:
    details = (author.get("authorAffiliationDetailsList") or {}).get("authorAffiliation") or []
    affiliations = (clean_display_text(entry.get("affiliation")) for entry in details)
    return [affiliation for affiliation in affiliations if affiliation]


def _authors(result: dict[str, Any]) -> list[CandidateAuthor]:
    authors: list[CandidateAuthor] = []
    entries = (result.get("authorList") or {}).get("author") or []
    for position, author in enumerate(entries):
        name = _author_name(author)
        if not name:
            continue
        author_id = author.get("authorId") or {}
        orcid = author_id.get("value") if author_id.get("type") == "ORCID" else None
        authors.append(
            CandidateAuthor(
                name=name,
                position=position,
                orcid=orcid,
                affiliations=_affiliations(author),
            )
        )
    return authors


def _venue(result: dict[str, Any], *, is_preprint: bool) -> CandidateVenue | None:
    journal = (result.get("journalInfo") or {}).get("journal") or {}
    name = clean_display_text(journal.get("title"))
    if name:
        return CandidateVenue(
            name=name,
            issn_l=journal.get("issn") or journal.get("essn"),
            venue_type="journal",
            is_oa=result.get("isOpenAccess") == "Y",
        )

    # Preprints have no journal; the server is named on the report details.
    publisher = clean_display_text((result.get("bookOrReportDetails") or {}).get("publisher"))
    if publisher and is_preprint:
        return CandidateVenue(name=publisher, venue_type="preprint_server", is_oa=True)
    return None


def _host_type(site: str, *, is_preprint: bool) -> str:
    if is_preprint:
        return "preprint"
    if site.lower() in REPOSITORY_SITES:
        return "repository"
    return "publisher"


def _locations(result: dict[str, Any], *, is_preprint: bool) -> list[CandidateLocation]:
    """One location per site, with the PDF folded into the record it belongs to.

    Europe PMC lists the HTML and PDF renderings of the same copy as two
    separate URLs; the corpus models a location as a landing page that may also
    have a PDF, so they are grouped rather than stored twice.
    """
    licence = map_licence(result.get("license"))
    version = "submittedVersion" if is_preprint else "publishedVersion"
    grouped: dict[str, CandidateLocation] = {}

    for entry in (result.get("fullTextUrlList") or {}).get("fullTextUrl") or []:
        url = entry.get("url")
        if not url or entry.get("availabilityCode") not in FREE_AVAILABILITY_CODES:
            continue
        site = str(entry.get("site") or "unknown")
        is_pdf = (entry.get("documentStyle") or "").lower() == "pdf"

        location = grouped.get(site)
        if location is None:
            grouped[site] = CandidateLocation(
                url=url,
                pdf_url=url if is_pdf else None,
                host_type=_host_type(site, is_preprint=is_preprint),
                version=version,
                licence=licence,
                source_name=site.replace("_", " "),
                is_best=site == PREFERRED_SITE,
            )
        elif is_pdf:
            location.pdf_url = location.pdf_url or url
        elif location.pdf_url is None:
            # A landing page is a better primary URL than the PDF that was seen
            # first, so it displaces one only by keeping the PDF as the PDF.
            location.pdf_url = location.url
            location.url = url

    locations = list(grouped.values())
    if locations and not any(location.is_best for location in locations):
        locations[0].is_best = True
    return locations


def oa_status_of(result: dict[str, Any], locations: list[CandidateLocation]) -> str:
    """What Europe PMC can attest to, and nothing more.

    Only `green`, `bronze` and `closed` are ever returned. Europe PMC reports
    that a free copy exists and where it lives; it does not report whether the
    *journal* is open access, so `gold`, `hybrid` and `diamond` are left to
    OpenAlex, which computes them. `merge.better_oa_status` only ever upgrades a
    status, so a green from here can never demote an OpenAlex gold.
    """
    if result.get("isOpenAccess") == "Y":
        return "green"
    if locations:
        # Free to read, with no open licence asserted for the work itself.
        return "bronze"
    return "closed"


def _topics(result: dict[str, Any]) -> list[dict[str, Any]]:
    """MeSH descriptors. Europe PMC exposes the term, not its descriptor UI."""
    topics: list[dict[str, Any]] = []
    headings = (result.get("meshHeadingList") or {}).get("meshHeading") or []
    for heading in headings:
        descriptor = clean_display_text(heading.get("descriptorName"))
        if not descriptor:
            continue
        topics.append(
            {
                "id": descriptor,
                "label": descriptor,
                "score": 1.0 if heading.get("majorTopic_YN") == "Y" else None,
                "scheme": "mesh",
            }
        )
    return topics


def _keywords(result: dict[str, Any]) -> list[str]:
    raw_keywords = (result.get("keywordList") or {}).get("keyword") or []
    keywords = (clean_display_text(keyword) for keyword in raw_keywords)
    return [keyword for keyword in keywords if keyword]


def _is_retracted(result: dict[str, Any]) -> bool:
    if _pub_types(result) & RETRACTED_TYPES:
        return True
    corrections = (result.get("commentCorrectionList") or {}).get("commentCorrection") or []
    return any(
        str(correction.get("type") or "").strip().lower() == "retraction in"
        for correction in corrections
    )


def normalise(raw: RawRecord) -> PaperCandidate | None:
    """Returns None when the record is out of ingestion scope."""
    result = raw.payload
    title = clean_display_text(result.get("title"))
    if not title or not is_in_scope(result):
        return None

    identifiers = _identifiers(result)
    if not identifiers:
        return None

    database = str(result.get("source") or "").upper()
    is_preprint = database == PREPRINT_DATABASE or "preprint" in _pub_types(result)
    published = (
        _parse_date(result.get("firstPublicationDate"))
        or _parse_date(result.get("electronicPublicationDate"))
        or _parse_date((result.get("journalInfo") or {}).get("printPublicationDate"))
    )
    locations = _locations(result, is_preprint=is_preprint)

    return PaperCandidate(
        source_key=SOURCE_KEY,
        source_id=raw.source_id,
        title=title,
        identifiers=identifiers,
        abstract=clean_display_text(result.get("abstractText")),
        authors=_authors(result),
        venue=_venue(result, is_preprint=is_preprint),
        published_date=published,
        first_seen_online=published,
        is_preprint=is_preprint,
        is_peer_reviewed=not is_preprint and database in PEER_REVIEWED_DATABASES,
        work_type=work_type_of(result, is_preprint=is_preprint),
        language=map_language(result.get("language")),
        topics=_topics(result),
        keywords=_keywords(result),
        citation_count=result.get("citedByCount"),
        oa_status=oa_status_of(result, locations),
        locations=locations,
        is_retracted_hint=_is_retracted(result),
    )
