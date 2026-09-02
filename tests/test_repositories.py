"""Which venues vouch for nothing, and therefore need corroboration.

The rule is about the *venue*, never about the deposit. A Zenodo record with a
perfect abstract, five authors and a DOI is still uncorroborated, because the
measurement that produced this rule showed exactly that: 98.4% of the Zenodo
slice had abstracts and 100% had authors, while 32% of legitimate OpenAlex
records elsewhere had no abstract at all. Well-formedness is not evidence.
"""

from __future__ import annotations

import pytest

from academious.core.ids import IdType
from academious.ingest.repositories import describe, is_general_repository
from academious.sources.base import CandidateIdentifier, CandidateVenue, PaperCandidate


def candidate(*, doi: str | None = None, **kwargs) -> PaperCandidate:
    """`primary_doi` is derived from the identifier list, so set it that way."""
    identifiers = [CandidateIdentifier(IdType.DOI, doi)] if doi else []
    return PaperCandidate(
        source_key="openalex",
        source_id="W1",
        title="A paper",
        identifiers=identifiers,
        **kwargs,
    )


@pytest.mark.parametrize(
    "doi",
    [
        "10.5281/zenodo.19407789",
        "10.5281/ZENODO.19542109",  # registrant prefixes are case-insensitive
        "10.6084/m9.figshare.12345",
        "10.17605/OSF.IO/ABCDE",
        "10.31219/osf.io/abcde",
    ],
)
def test_repository_doi_prefixes_are_recognised(doi):
    assert is_general_repository(candidate(doi=doi))


@pytest.mark.parametrize(
    "doi",
    [
        "10.1101/2026.08.21.000000",  # bioRxiv
        "10.48550/arXiv.1706.03762",  # arXiv
        "10.1038/s41586-024-00001-0",  # Nature
        "10.5282/something",  # a prefix that merely starts similarly
    ],
)
def test_ordinary_dois_are_not_repositories(doi):
    assert not is_general_repository(candidate(doi=doi))


def test_the_venue_name_catches_a_record_with_no_doi():
    # OpenAlex spells it "Zenodo (CERN European Organization for Nuclear
    # Research)"; other sources say "Zenodo". Substring match, case-folded.
    venue = CandidateVenue(name="Zenodo (CERN European Organization for Nuclear Research)")

    assert is_general_repository(candidate(venue=venue))


def test_a_journal_venue_is_not_a_repository():
    assert not is_general_repository(candidate(venue=CandidateVenue(name="Nature Methods")))


def test_a_record_with_neither_doi_nor_venue_is_not_a_repository():
    # Absence of evidence is not evidence: an unknown venue is treated as an
    # ordinary one, because the alternative rejects every sparse record.
    assert not is_general_repository(candidate())


def test_a_well_formed_deposit_is_still_a_deposit():
    """The measured reason this rule is about venue rather than content."""
    polished = candidate(
        doi="10.5281/zenodo.19407789",
        abstract="A complete and plausible abstract.",
    )

    assert is_general_repository(polished)


def test_describe_names_the_prefix_that_matched():
    reason = describe(candidate(doi="10.5281/zenodo.1"))

    assert "10.5281" in reason


def test_describe_falls_back_to_the_venue():
    reason = describe(candidate(venue=CandidateVenue(name="figshare")))

    assert "venue" in reason


# ------------------------------------------------- provenance beats prefix


def test_a_moderated_source_vouches_for_its_own_records():
    """arXiv:2608.13351 is why this exists.

    A real, moderated arXiv submission whose author registered a Zenodo DOI for
    it. Testing the prefix alone marked it for removal from the development
    corpus. A DOI prefix says where the identifier was minted; it does not say
    where the work was published.
    """
    on_arxiv = PaperCandidate(
        source_key="arxiv",
        source_id="2608.13351",
        title="The Use of Learning Management Systems for Self-paced Learning",
        identifiers=[CandidateIdentifier(IdType.DOI, "10.5281/zenodo.20645724")],
    )

    assert not is_general_repository(on_arxiv)


@pytest.mark.parametrize("source_key", ["arxiv", "biorxiv", "europepmc", "pubmed"])
def test_every_curated_source_vouches_for_itself(source_key):
    record = PaperCandidate(
        source_key=source_key,
        source_id="x",
        title="A paper",
        identifiers=[CandidateIdentifier(IdType.DOI, "10.5281/zenodo.1")],
        venue=CandidateVenue(name="Zenodo"),
    )

    assert not is_general_repository(record)


def test_an_aggregators_view_of_a_deposit_is_still_a_deposit():
    # OpenAlex indexes everything and vouches for nothing, which is the whole
    # asymmetry: it is how the 25,399 Zenodo papers arrived.
    via_openalex = PaperCandidate(
        source_key="openalex",
        source_id="W1",
        title="A paper",
        identifiers=[CandidateIdentifier(IdType.DOI, "10.5281/zenodo.1")],
    )

    assert is_general_repository(via_openalex)
