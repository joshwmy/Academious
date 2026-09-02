"""Text normalisation for titles, author names and abstracts.

`normalise_title` produces the blocking/comparison key used by fuzzy
deduplication. Its contract: two renderings of the same title by different
sources must produce the same string. Sources differ in casing, punctuation,
accents, HTML entities, LaTeX fragments and whitespace, so all of those are
removed.

Stopwords are deliberately NOT removed. Scientific titles are short, and
dropping 'of'/'the'/'in' measurably degrades trigram similarity on the short
titles where dedup is hardest. This is a deliberate deviation from the sketch in
phase-0-report.md section 4.1.
"""

from __future__ import annotations

import html
import re
import unicodedata

_TAG = re.compile(r"<[^>]+>")
_LATEX_CMD = re.compile(r"\[a-zA-Z]+\s*")
# `[\W_]+` and not `[^a-z0-9]+`. The ASCII-only class deleted every character
# outside a-z0-9, which for a Chinese, Japanese, Korean, Cyrillic, Arabic,
# Hebrew or Greek title means deleting the entire title: it normalised to "".
# 3,819 papers in the live corpus sat at title_norm = '' on 2026-09-03, all of
# them Chinese-titled.
#
# Nothing was wrongly merged - `find_fuzzy` refuses to match a key shorter than
# 12 characters - but the mirror failure was silent and permanent: a paper with
# a non-Latin title could only ever deduplicate by identifier, so two records of
# it from two sources stayed two papers forever.
#
# `\W` is Unicode-aware in Python 3, so this keeps letters and digits in every
# script and strips punctuation and separators. `_` is added because `\w`
# counts it as a word character and it is punctuation for this purpose. ASCII
# titles normalise byte-identically to before.
_NON_ALNUM = re.compile(r"[\W_]+", re.UNICODE)
_WS = re.compile(r"\s+")

# Publishers prefix retracted articles in the title itself; it is metadata, not
# part of the work's name, and it would otherwise defeat matching against a
# source that has not applied the prefix. Verified against live OpenAlex data.
_STATUS_PREFIX = re.compile(
    r"^\s*(retracted(\s+article)?|withdrawn|expression\s+of\s+concern|erratum|corrigendum)\s*[:.\-]\s*",
    re.IGNORECASE,
)


def strip_status_prefix(title: str) -> str:
    """Remove a leading 'RETRACTED:' style editorial prefix."""
    previous = None
    current = title
    while previous != current:
        previous = current
        current = _STATUS_PREFIX.sub("", current).strip()
    return current


def normalise_title(title: str | None) -> str:
    """Aggressive fold used as the dedup blocking key. Never returns None."""
    if not title:
        return ""
    text = html.unescape(title)
    text = _TAG.sub(" ", text)
    text = _LATEX_CMD.sub(" ", text)
    text = strip_status_prefix(text)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.casefold()
    text = _NON_ALNUM.sub(" ", text)
    return _WS.sub(" ", text).strip()


#: Scripts where one character carries roughly what a short word carries in an
#: alphabetic script: CJK ideographs, kana, and Hangul syllables.
_DENSE_SCRIPT_RANGES = (
    (0x3040, 0x30FF),  # hiragana, katakana
    (0x3400, 0x4DBF),  # CJK extension A
    (0x4E00, 0x9FFF),  # CJK unified ideographs
    (0xAC00, 0xD7AF),  # Hangul syllables
    (0xF900, 0xFAFF),  # CJK compatibility ideographs
)


def is_dense_script(char: str) -> bool:
    code = ord(char)
    return any(low <= code <= high for low, high in _DENSE_SCRIPT_RANGES)


def blocking_weight(title_norm: str) -> int:
    """How much a blocking key is worth, in alphabetic-character equivalents.

    Deduplication refuses to fuzzy-match on a key that is too short, because
    "Errata" and "Reply" match everything. That threshold is a character count,
    which silently means *a Latin character count*: a Chinese title of ten
    ideographs is a full, specific title and would fail a limit written for
    English. `基于量子计算的拓扑优化` is eleven characters and names a paper.

    So a dense-script character counts for three. The multiplier is a judgement,
    not a measurement - it is roughly the ratio of characters to information
    between the scripts, and it is deliberately conservative: it lets a real
    four-ideograph title through while still rejecting one or two characters.
    """
    return sum(3 if is_dense_script(char) else 1 for char in title_norm)


def clean_display_text(text: str | None) -> str | None:
    """Light cleanup for text shown to users: entities and tags out, wording kept."""
    if not text:
        return None
    cleaned = _TAG.sub(" ", html.unescape(text))
    cleaned = _WS.sub(" ", cleaned).strip()
    return cleaned or None


def surname(full_name: str | None) -> str | None:
    """Best-effort surname, folded for comparison.

    Sources give 'Celine Loot', 'Loot, C.' and separate keyname/forenames. The
    comma form is authoritative when present; otherwise the last token is used.
    Compound surnames ('van der Waals') are not resolved - that is acceptable
    because this feeds a Jaccard overlap check, not an exact match.
    """
    if not full_name or not full_name.strip():
        return None
    name = clean_display_text(full_name) or ""
    if "," in name:
        candidate = name.split(",", 1)[0]
    else:
        parts = name.split()
        if not parts:
            return None
        candidate = parts[-1]
    folded = normalise_title(candidate)
    return folded or None


def surname_set(names: list[str]) -> set[str]:
    """Surnames of an author list, for overlap comparison."""
    return {s for s in (surname(n) for n in names) if s}


def jaccard(left: set[str], right: set[str]) -> float:
    """Jaccard similarity. Empty on either side scores 0.0, never 1.0."""
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)
