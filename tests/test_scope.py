"""The corpus-admission policy: which work types Academious discovers.

These tests are deliberately source-agnostic. The policy exists so that a later
connector - PubMed first - inherits the product decision instead of restating
it, so everything here is expressed in the shared vocabulary and nothing here
knows what Europe PMC calls anything.
"""

from __future__ import annotations

import pytest

from academious.ingest.scope import (
    DISCOVERY_TYPES,
    NON_SUBSTANTIVE_TYPES,
    TERTIARY_TYPES,
    Admission,
    WorkType,
    classify,
    describe,
    is_discovery_eligible,
    is_recognised,
)


@pytest.mark.parametrize(
    "work_type",
    [
        WorkType.ARTICLE,
        WorkType.REVIEW,
        WorkType.PREPRINT,
        WorkType.CONFERENCE_PAPER,
        WorkType.DISSERTATION,
        WorkType.REPORT,
    ],
)
def test_research_literature_is_admitted(work_type):
    assert classify(work_type) is Admission.ADMIT
    assert is_discovery_eligible(work_type)


@pytest.mark.parametrize(
    "work_type", [WorkType.BOOK, WorkType.BOOK_CHAPTER, WorkType.REFERENCE_ENTRY]
)
def test_reference_material_is_tertiary(work_type):
    assert classify(work_type) is Admission.TERTIARY
    assert not is_discovery_eligible(work_type)


@pytest.mark.parametrize(
    "work_type",
    [
        WorkType.ABSTRACT,
        WorkType.EDITORIAL,
        WorkType.LETTER,
        WorkType.COMMENT,
        WorkType.BOOK_REVIEW,
        WorkType.CORRECTION,
        WorkType.RETRACTION_NOTICE,
        WorkType.PEER_REVIEW,
        WorkType.DATASET,
        WorkType.GRANT,
        WorkType.PARATEXT,
    ],
)
def test_non_works_are_not_substantive(work_type):
    assert classify(work_type) is Admission.NON_SUBSTANTIVE
    assert not is_discovery_eligible(work_type)


def test_reviews_are_research_not_reference():
    """The distinction the whole policy turns on.

    A review article is current research synthesis and belongs in a feed; a
    reference-work entry is settled knowledge and does not. Upstream sometimes
    types the second as the first, which is why sources decide `reference-entry`
    structurally before asking this module.
    """
    assert is_discovery_eligible(WorkType.REVIEW)
    assert not is_discovery_eligible(WorkType.REFERENCE_ENTRY)


def test_an_unknown_type_is_admitted_rather_than_silently_dropped():
    """Asymmetric costs: an odd row in a feed beats losing research."""
    assert classify("data-paper-v2") is Admission.ADMIT
    assert is_discovery_eligible("some-new-crossref-type")
    assert is_discovery_eligible(None)


def test_an_unknown_type_is_still_reported_as_unrecognised():
    """So the vocabulary grows from evidence, not from guesses."""
    assert is_recognised(WorkType.ARTICLE)
    assert not is_recognised("some-new-crossref-type")
    assert not is_recognised(None)


def test_classification_ignores_case_and_surrounding_space():
    assert classify(" Reference-Entry ") is Admission.TERTIARY
    assert classify("ARTICLE") is Admission.ADMIT


def test_describe_names_the_reason_a_record_was_refused():
    assert describe(WorkType.ARTICLE) == "admitted"
    assert describe(WorkType.REFERENCE_ENTRY) == "tertiary:reference-entry"
    assert describe(WorkType.ABSTRACT) == "non_substantive:abstract"


def test_a_new_source_needs_only_a_type_mapping_to_inherit_the_policy():
    """What a PubMed connector will do: map its vocabulary, then ask.

    MEDLINE publication types, mapped the way any connector would map them. No
    Europe PMC involvement, and no second copy of the product decision.
    """
    pubmed_like = {
        "Journal Article": WorkType.ARTICLE,
        "Systematic Review": WorkType.REVIEW,
        "Meta-Analysis": WorkType.REVIEW,
        "Randomized Controlled Trial": WorkType.ARTICLE,
        "Preprint": WorkType.PREPRINT,
        "Congresses": WorkType.ABSTRACT,
        "Published Erratum": WorkType.CORRECTION,
        "Webcasts": WorkType.PARATEXT,
    }
    admitted = {name for name, mapped in pubmed_like.items() if is_discovery_eligible(mapped)}
    assert admitted == {
        "Journal Article",
        "Systematic Review",
        "Meta-Analysis",
        "Randomized Controlled Trial",
        "Preprint",
    }


def test_every_vocabulary_member_has_exactly_one_classification():
    """No member may be forgotten, and none may sit in two buckets."""
    buckets = [DISCOVERY_TYPES, TERTIARY_TYPES, NON_SUBSTANTIVE_TYPES]
    assert set(WorkType) == set().union(*buckets)
    for left in range(len(buckets)):
        for right in range(left + 1, len(buckets)):
            assert not buckets[left] & buckets[right]
