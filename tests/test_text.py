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


CJK = "基于量子计算的拓扑优化"  # a real title from the corpus
CYRILLIC = "Прогноз погоды"
KOREAN = "한국어 논문"
JAPANESE = "ディープラーニング"


@pytest.mark.parametrize("title", [CJK, CYRILLIC, KOREAN, JAPANESE])
def test_normalise_title_does_not_erase_non_latin_scripts(title):
    """A non-Latin title used to normalise to the empty string.

    `title_norm` is the dedup blocking key, so a title that folds to "" cannot
    match anything: 3,819 papers in the live corpus - every one of them Chinese
    - could only ever deduplicate by identifier. Nothing merged wrongly, because
    `find_fuzzy` refuses a key under 12 characters, but two records of one paper
    stayed two papers permanently.

    The assertion is a property rather than an exact string. The fold still
    applies NFKD and drops combining marks, which decomposes Hangul into jamo
    and strips Japanese voicing marks - the same treatment Latin accents get.
    That is lossy and symmetric, which is what a blocking key needs.
    """
    assert text.normalise_title(title) != ""


def test_the_same_non_latin_title_normalises_to_the_same_key():
    assert text.normalise_title(f"  {CJK}!  ") == text.normalise_title(CJK)


def test_different_non_latin_titles_do_not_collide():
    # The bug was every one of them colliding on "".
    assert text.normalise_title(CJK) != text.normalise_title(CYRILLIC)


def test_punctuation_is_stripped_from_non_latin_titles_too():
    quoted = "《" + CJK + "》：综述"

    normalised = text.normalise_title(quoted)

    assert "《" not in normalised
    assert "：" not in normalised
    assert normalised.startswith(text.normalise_title(CJK))


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


# ------------------------------------------------ dedup blocking-key weight


def test_a_short_latin_title_is_too_light_to_block_on():
    # "Errata" and "Reply" match half the corpus; the threshold exists for them.
    assert text.blocking_weight(text.normalise_title("Errata")) < 12
    assert text.blocking_weight(text.normalise_title("Reply")) < 12


def test_a_real_latin_title_is_heavy_enough():
    assert text.blocking_weight(text.normalise_title("Graph neural networks for molecules")) >= 12


def test_a_chinese_title_shorter_than_twelve_characters_still_counts():
    """A character count is a Latin character count.

    This title is eleven characters and names a paper precisely, so a bare
    `len() < 12` would have refused to deduplicate it - which is most Chinese
    titles in the corpus.
    """
    assert len(CJK) < 12
    assert text.blocking_weight(text.normalise_title(CJK)) >= 12


def test_a_two_ideograph_fragment_is_still_refused():
    # The weighting must not turn "quantum" into a blocking key.
    assert text.blocking_weight(text.normalise_title("量子")) < 12
