"""The embedding input builder: determinism, versioning and the missing-abstract path."""

from __future__ import annotations

import pytest

from academious.embeddings.text import (
    MIN_ABSTRACT_CHARS,
    SEP_TOKEN,
    InputMode,
    InputStrategy,
    build_embedding_input,
    usable_abstract,
)

ABSTRACT = (
    "Integrons are mobile genetic elements that capture and express gene cassettes, "
    "and we show here that cassettes integrate at attG sites."
)


def test_title_and_abstract_are_joined_with_the_separator_token():
    built = build_embedding_input("Integron cassettes", ABSTRACT)
    assert built.text == f"Integron cassettes{SEP_TOKEN}{ABSTRACT}"
    assert built.strategy is InputStrategy.TITLE_ABSTRACT


def test_missing_abstract_falls_back_to_title_with_no_trailing_separator():
    built = build_embedding_input("A paper with no abstract anywhere", None)
    assert built.text == "A paper with no abstract anywhere"
    assert SEP_TOKEN not in built.text
    assert built.strategy is InputStrategy.TITLE_ONLY


@pytest.mark.parametrize("abstract", [None, "", "   ", "n/a", "Abstract."])
def test_placeholder_abstracts_are_treated_as_absent(abstract):
    assert usable_abstract(abstract) is None
    built = build_embedding_input("Some title", abstract)
    assert built.strategy is InputStrategy.TITLE_ONLY


def test_an_abstract_just_over_the_threshold_is_used():
    abstract = "x" * MIN_ABSTRACT_CHARS
    assert usable_abstract(abstract) == abstract
    assert build_embedding_input("T", abstract).strategy is InputStrategy.TITLE_ABSTRACT


def test_title_only_mode_ignores_an_available_abstract():
    built = build_embedding_input("Integron cassettes", ABSTRACT, mode=InputMode.TITLE_ONLY)
    assert built.text == "Integron cassettes"
    assert built.strategy is InputStrategy.TITLE_ONLY


def test_retraction_prefix_is_stripped_from_the_embedded_text():
    """The prefix is editorial metadata; it is not what the paper is about."""
    plain = build_embedding_input("Effects of hydroxychloroquine", ABSTRACT)
    flagged = build_embedding_input("RETRACTED: Effects of hydroxychloroquine", ABSTRACT)
    assert flagged.text == plain.text
    assert flagged.text_hash == plain.text_hash


def test_html_and_entities_are_removed():
    built = build_embedding_input("A &amp; B <i>in vivo</i>", None)
    assert built.text == "A & B in vivo"


def test_the_same_input_always_hashes_the_same():
    first = build_embedding_input("Title", ABSTRACT)
    second = build_embedding_input("Title", ABSTRACT)
    assert first.text_hash == second.text_hash


def test_changing_the_abstract_changes_the_hash():
    with_abstract = build_embedding_input("Title", ABSTRACT)
    without = build_embedding_input("Title", None)
    assert with_abstract.text_hash != without.text_hash


def test_an_empty_title_and_no_abstract_produces_an_empty_input():
    built = build_embedding_input("", None)
    assert built.is_empty
