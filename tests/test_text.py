"""Title/author normalisation feeds fuzzy dedup; false equality here is dangerous."""

from __future__ import annotations

import pytest

from academious.core import text


def test_normalise_title_folds_case_punctuation_and_accents():
    left = text.normalise_title("Integron Cassettes: A New Route!")
    right = text.normalise_title("integron cassettes  a new route")
    assert left == right == "integron cassettes a new route"


def test_normalise_title_strips_html_and_entities():
    assert text.normalise_title("Effects of <i>E. coli</i> &amp; heat") == "effects of e coli heat"


def test_normalise_title_removes_retracted_prefix():
    retracted = text.normalise_title(
        "RETRACTED: Hydroxychloroquine or chloroquine for treatment of COVID-19"
    )
    plain = text.normalise_title("Hydroxychloroquine or chloroquine for treatment of COVID-19")
    assert retracted == plain


def test_normalise_title_handles_accents():
    assert text.normalise_title("Céline's Théorème") == text.normalise_title("Celine's Theoreme")


def test_normalise_title_of_empty_is_empty_string_not_none():
    assert text.normalise_title(None) == ""
    assert text.normalise_title("   ") == ""


def test_distinct_titles_do_not_collide():
    assert text.normalise_title("A new route for integron cassettes") != text.normalise_title(
        "Integron cassettes integrate via non-classical attG sites"
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Loot, C.", "loot"),
        ("Céline Loot", "loot"),
        ("Aidan N. Gomez", "gomez"),
        ("Vaswani", "vaswani"),
        ("", None),
        (None, None),
    ],
)
def test_surname(raw, expected):
    assert text.surname(raw) == expected


def test_surname_set_and_jaccard():
    left = text.surname_set(["Loot, C.", "Millot, G.", "Mazel, D."])
    right = text.surname_set(["Céline Loot", "Guillaume Millot", "Didier Mazel"])
    assert left == right
    assert text.jaccard(left, right) == 1.0


def test_jaccard_of_empty_is_zero_not_one():
    assert text.jaccard(set(), set()) == 0.0
    assert text.jaccard({"a"}, set()) == 0.0


def test_jaccard_partial_overlap():
    assert text.jaccard({"a", "b"}, {"b", "c"}) == pytest.approx(1 / 3)


def test_clean_display_text_preserves_wording():
    assert text.clean_display_text("  Integrons   are <b>genetic</b> elements ") == (
        "Integrons are genetic elements"
    )
