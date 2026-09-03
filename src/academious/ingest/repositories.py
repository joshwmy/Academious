"""General-purpose repositories, and why a deposit in one is not enough.

Zenodo, figshare and OSF accept anything anyone uploads. That is their purpose
and it is a good one - but it means a deposit there carries no evidence that the
thing deposited is research. A subject repository is different: arXiv moderates,
bioRxiv screens, and a submission to either has passed something.

**Measured on the live corpus, 2026-09-03.** Zenodo supplied 25,399 papers, 24%
of everything, across 11,442 distinct titles. One title appeared 26 times. 3,577
of them shared a single first-author surname and were deposited inside one week,
with buzzword-recombination Chinese titles. One depositor's personal technical
notes accounted for another ~150, titled "windows archived 2026 08 30" and
similar. A person's name was used as a title.

The obvious defence does not work, and this is worth recording because it was
the first plan:

| slice | no abstract | no authors | no DOI |
|---|---|---|---|
| Zenodo | **1.6%** | 0% | 0% |
| OpenAlex elsewhere | 31.9% | 0% | 7% |
| Europe PMC | 2.0% | 0.5% | 2% |

A content-quality gate - require an abstract, require an author - would have
rejected **1.6%** of the Zenodo slice while destroying **32%** of legitimate
OpenAlex records that simply arrive without an abstract. The spam is well
formed. Metadata completeness is not a proxy for being research.

**So the rule is corroboration, not quality.** A deposit in a general-purpose
repository may *enrich* a paper the corpus already knows about - it is a real
location, often an open-access one, and its metadata is welcome - but it may not
*found* a new paper on its own. Something else has to have seen the work:
another source, or a DOI or title matching a paper already held.

Automated deposits are uncorroborated by construction. They exist nowhere but
the repository they were uploaded to, so they never pass. A genuine preprint
deposited to Zenodo *and* indexed by OpenAlex from anywhere else does pass,
because the other record founds the paper and the Zenodo record merges into it.

**What this deliberately costs.** A real paper deposited only to Zenodo and
indexed nowhere else is excluded. That is a real loss and it is the price of the
rule; it is bounded by how much genuine literature exists solely in a
general-purpose repository, and it is recoverable - the raw payload is kept, so
a later pass can readmit those records under a better rule without
re-harvesting.
"""

from __future__ import annotations

from academious.sources.base import PaperCandidate

#: Sources that vouch for what they carry. arXiv moderates, bioRxiv screens,
#: Europe PMC and PubMed index against editorial criteria - a record arriving
#: from any of them has already passed something, and is corroborated by the
#: fact of its own provenance.
#:
#: This matters more than it looks. A DOI prefix says where the *identifier*
#: was minted, not where the work was published: arXiv:2608.13351 in the
#: development corpus is a moderated arXiv submission whose author registered a
#: Zenodo DOI, and testing the prefix alone marked it for removal. The rule is
#: about the venue that accepted the work, so an aggregator's view of a
#: repository deposit is what it applies to.
SELF_VOUCHING_SOURCES: frozenset[str] = frozenset({"arxiv", "biorxiv", "europepmc", "pubmed"})

#: DOI registrant prefixes belonging to general-purpose repositories. A prefix
#: is the most reliable signal available: it is assigned by DataCite to one
#: registrant, it travels with the record through every source, and it does not
#: depend on how a venue happens to be spelled today.
GENERAL_REPOSITORY_DOI_PREFIXES: tuple[str, ...] = (
    "10.5281/",  # Zenodo
    "10.6084/",  # figshare
    "10.17605/",  # OSF
    "10.31219/",  # OSF Preprints
)

#: Venue types, as OpenAlex reports them in `primary_location.source.type`,
#: that vouch for what they carry. A journal has editors; a conference has a
#: programme committee; a book publisher has an acquisitions process. None of
#: them is a place anyone can upload to.
#:
#: This is the second half of the lesson the arXiv DOI taught. Small journals
#: routinely mint their DOIs through Zenodo, so the prefix condemns work that
#: was published in a journal: a live dry run over 116,390 papers flagged 458
#: papers in *Open MIND*, 24 in the World Journal of Pharmacy and 20 on arXiv,
#: all for having Zenodo-registered identifiers. The venue decides; the prefix
#: only speaks when the venue does not.
VOUCHING_VENUE_TYPES: frozenset[str] = frozenset(
    {"journal", "conference", "book series", "ebook platform"}
)

#: Venue-name fallback, for records that reach us without a DOI. Matched as a
#: case-folded substring, which is why the entries are distinctive words rather
#: than full names: Zenodo arrives as "Zenodo (CERN European Organization for
#: Nuclear Research)" through OpenAlex and as "Zenodo" elsewhere.
GENERAL_REPOSITORY_VENUE_TERMS: tuple[str, ...] = (
    "zenodo",
    "figshare",
    "open science framework",
)


def is_general_repository(candidate: PaperCandidate) -> bool:
    """Whether this record is a deposit in a repository that accepts anything.

    Not a judgement about the deposit. A great many Zenodo records are real
    research; this only says the venue vouches for nothing, so the record needs
    corroboration before it can found a paper.

    A record from a source that vouches for its own contents is never one of
    these, whatever DOI it carries, and neither is one published in a venue
    that vouches for its own contents.
    """
    if candidate.source_key in SELF_VOUCHING_SOURCES:
        return False

    venue_type = (candidate.venue.venue_type or "").casefold() if candidate.venue else ""
    if venue_type in VOUCHING_VENUE_TYPES:
        return False

    venue_name = (candidate.venue.name if candidate.venue else "").casefold()
    if any(term in venue_name for term in GENERAL_REPOSITORY_VENUE_TERMS):
        return True

    # The DOI prefix speaks last, and only about records whose venue said
    # nothing useful: a repository, or no venue at all.
    doi = (candidate.primary_doi or "").lower()
    return doi.startswith(GENERAL_REPOSITORY_DOI_PREFIXES)


def describe(candidate: PaperCandidate) -> str:
    """Why a record was held back, for the ingestion log."""
    doi = (candidate.primary_doi or "").lower()
    for prefix in GENERAL_REPOSITORY_DOI_PREFIXES:
        if doi.startswith(prefix):
            return f"general-purpose repository DOI prefix {prefix.rstrip('/')}"
    return "general-purpose repository venue"
