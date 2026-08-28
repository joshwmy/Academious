"""Identifier normalisation.

Every external identifier is reduced to one canonical string form before it is
stored or compared. This module is the sole authority on that form: if two
records refer to the same paper, normalising their identifiers here must produce
equal strings, because identifier equality is the primary deduplication path
(see docs/data-model.md).

All functions return None for input they cannot confidently normalise. Returning
a best-effort guess would create false merges, which are far worse than misses.
"""

from __future__ import annotations

import re
from enum import StrEnum


class IdType(StrEnum):
    DOI = "doi"
    PMID = "pmid"
    PMCID = "pmcid"
    ARXIV = "arxiv"
    OPENALEX = "openalex"
    MAG = "mag"


_DOI_CORE = re.compile(r"(10\.\d{4,9}/[^\s\"'<>]+)", re.IGNORECASE)
_DOI_TRAILING_JUNK = re.compile(r"[.,;:)\]}>]+$")

_ARXIV_NEW = re.compile(r"\b(\d{4}\.\d{4,5})(v\d+)?\b")
_ARXIV_OLD = re.compile(r"\b([a-z][a-z-]*(?:\.[A-Za-z]{2})?/\d{7})(v\d+)?\b", re.IGNORECASE)
# arXiv mints DOIs under two prefixes; 10.48550 is derivable from the arXiv ID,
# 10.65215 is opaque and is NOT (verified against live OpenAlex data).
_ARXIV_DOI = re.compile(r"^10\.48550/arxiv\.(.+)$", re.IGNORECASE)

_DIGITS = re.compile(r"\d+")


def normalise_doi(raw: str | None) -> str | None:
    """Bare lowercase DOI: 'https://doi.org/10.X/Y' -> '10.x/y'."""
    if not raw:
        return None
    match = _DOI_CORE.search(raw.strip())
    if not match:
        return None
    doi = _DOI_TRAILING_JUNK.sub("", match.group(1)).lower()
    return doi or None


def normalise_pmid(raw: str | int | None) -> str | None:
    """Digits only. Accepts bare ids and pubmed.ncbi.nlm.nih.gov URLs."""
    if raw is None:
        return None
    match = _DIGITS.search(str(raw))
    if not match:
        return None
    pmid = match.group(0).lstrip("0") or "0"
    return pmid if pmid != "0" else None


def normalise_pmcid(raw: str | None) -> str | None:
    """'PMC' + digits, uppercase prefix."""
    if not raw:
        return None
    match = _DIGITS.search(str(raw))
    if not match:
        return None
    return f"PMC{match.group(0)}"


def normalise_arxiv(raw: str | None) -> str | None:
    """Bare arXiv id with the version suffix stripped.

    '2401.12345v3', 'arXiv:2401.12345', 'https://arxiv.org/abs/2401.12345v2',
    'oai:arXiv.org:1706.03762' and '10.48550/arXiv.1706.03762' all normalise to
    the same value. Version suffixes are dropped deliberately: v1 and v3 of a
    preprint are the same paper for discovery purposes.
    """
    if not raw:
        return None
    text = raw.strip()

    doi_match = _ARXIV_DOI.match(text)
    if doi_match:
        text = doi_match.group(1)

    new_style = _ARXIV_NEW.search(text)
    if new_style:
        return new_style.group(1)

    old_style = _ARXIV_OLD.search(text)
    if old_style:
        return old_style.group(1).lower()

    return None


def normalise_openalex(raw: str | None) -> str | None:
    """'https://openalex.org/W123' -> 'W123'."""
    if not raw:
        return None
    match = re.search(r"\b([WwSsAaIiPpTtCcFfDd]\d{4,})\b", raw.strip())
    return match.group(1).upper() if match else None


def normalise_mag(raw: str | int | None) -> str | None:
    if raw is None:
        return None
    match = _DIGITS.search(str(raw))
    return match.group(0) if match else None


_NORMALISERS = {
    IdType.DOI: normalise_doi,
    IdType.PMID: normalise_pmid,
    IdType.PMCID: normalise_pmcid,
    IdType.ARXIV: normalise_arxiv,
    IdType.OPENALEX: normalise_openalex,
    IdType.MAG: normalise_mag,
}


def normalise(id_type: IdType, raw: str | int | None) -> str | None:
    """Dispatch to the normaliser for id_type."""
    return _NORMALISERS[id_type](raw)  # type: ignore[operator]


def arxiv_id_from_url(url: str | None) -> str | None:
    """Extract an arXiv id from a location URL, if the URL is an arXiv one.

    OpenAlex does not expose arXiv ids as first-class identifiers; the only link
    is the landing page or PDF URL on a location record. Verified against live
    OpenAlex payloads.
    """
    if not url or "arxiv.org" not in url.lower():
        return None
    return normalise_arxiv(url)
