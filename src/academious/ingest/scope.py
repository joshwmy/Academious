"""What counts as part of the discovery corpus.

Academious answers one question: *what new research came out that I would
probably care about?* That makes it a discovery layer over primary and secondary
research literature, not a biomedical library catalogue. Reference works are
excellent - and they are somebody else's product.

This module owns that decision for **every** source. A connector's job is to map
its upstream vocabulary onto `WorkType`; the judgement about which of those types
belong in the corpus is made here, once, so that a later PubMed connector
inherits it instead of re-litigating it. Before this existed, OpenAlex and
Europe PMC each carried their own exclusion table and the two disagreed.

Three classes of decision:

* `ADMIT` - research literature. Journal articles, preprints, reviews and
  substantive conference papers. **Reviews stay in.** A systematic review or a
  meta-analysis is current research synthesis and is exactly what a researcher
  wants in a feed; only reference-work "reviews" are excluded, and they are
  identified structurally rather than by their publication type - see
  `sources/europepmc/normalise.py`, where MEDLINE types GeneReviews chapters as
  `review` and only the book metadata tells them apart.
* `TERTIARY` - reference material. Books, book chapters, encyclopedia and
  handbook entries, NCBI Bookshelf chapters such as StatPearls and GeneReviews.
  Written to summarise settled knowledge, revised continuously, and not news.
* `NON_SUBSTANTIVE` - records that are not a research work at all. Conference and
  meeting abstracts, editorials, letters, book reviews, corrections and
  retraction notices. A correction is bibliographic housekeeping that reaches the
  reader through `retraction_status` on the paper it corrects, never as a paper
  of its own.

**An unrecognised type is admitted.** Upstream vocabularies are large, uneven and
still growing, and the cost of the two errors is not symmetric: admitting an odd
record shows one unwanted row in a feed, while rejecting an unrecognised one
silently loses research that nothing else will surface. `is_recognised` exists so
an unknown type can be logged and the vocabulary extended from evidence, rather
than guessed at in advance.
"""

from __future__ import annotations

from enum import StrEnum


class WorkType(StrEnum):
    """The corpus-wide vocabulary every source normalises onto.

    Values follow OpenAlex's `type` field, which is Crossref's vocabulary, both
    because OpenAlex is the metadata spine and because it already draws the
    distinction that matters here - `reference-entry` against `article`.
    """

    ARTICLE = "article"
    REVIEW = "review"
    PREPRINT = "preprint"
    CONFERENCE_PAPER = "conference-paper"
    DISSERTATION = "dissertation"
    REPORT = "report"

    BOOK = "book"
    BOOK_CHAPTER = "book-chapter"
    #: Encyclopedia, handbook and reference-work entries. NCBI Bookshelf lands
    #: here: StatPearls and GeneReviews chapters are reference articles that
    #: MEDLINE happens to type as "review" or "study guide".
    REFERENCE_ENTRY = "reference-entry"

    #: A conference or meeting abstract: a paragraph in a supplement, typically
    #: with no DOI, no abstract text of its own and no author list.
    ABSTRACT = "abstract"
    EDITORIAL = "editorial"
    LETTER = "letter"
    COMMENT = "comment"
    BOOK_REVIEW = "book-review"
    CORRECTION = "correction"
    RETRACTION_NOTICE = "retraction-notice"
    PEER_REVIEW = "peer-review"
    DATASET = "dataset"
    GRANT = "grant"
    PARATEXT = "paratext"


class Admission(StrEnum):
    """Why a work is or is not part of the discovery corpus."""

    ADMIT = "admit"
    TERTIARY = "tertiary"
    NON_SUBSTANTIVE = "non_substantive"


DISCOVERY_TYPES = frozenset(
    {
        WorkType.ARTICLE,
        WorkType.REVIEW,
        WorkType.PREPRINT,
        WorkType.CONFERENCE_PAPER,
        WorkType.DISSERTATION,
        WorkType.REPORT,
    }
)

TERTIARY_TYPES = frozenset({WorkType.BOOK, WorkType.BOOK_CHAPTER, WorkType.REFERENCE_ENTRY})

NON_SUBSTANTIVE_TYPES = frozenset(
    {
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
    }
)


def classify(work_type: str | None) -> Admission:
    """Decide admission from a normalised work type.

    `None` and any unrecognised value are admitted; see the module docstring on
    why the fallback leans that way.
    """
    if work_type is None:
        return Admission.ADMIT
    try:
        known = WorkType(work_type.strip().lower())
    except ValueError:
        return Admission.ADMIT
    if known in TERTIARY_TYPES:
        return Admission.TERTIARY
    if known in NON_SUBSTANTIVE_TYPES:
        return Admission.NON_SUBSTANTIVE
    return Admission.ADMIT


def is_discovery_eligible(work_type: str | None) -> bool:
    """True when a work of this type belongs in the discovery corpus."""
    return classify(work_type) is Admission.ADMIT


def describe(work_type: str | None) -> str:
    """A stable reason string for logs and run counters."""
    admission = classify(work_type)
    if admission is Admission.ADMIT:
        return "admitted"
    return f"{admission.value}:{work_type}"


def is_recognised(work_type: str | None) -> bool:
    """False for a type outside the vocabulary - admitted, but worth logging."""
    if work_type is None:
        return False
    try:
        WorkType(work_type.strip().lower())
    except ValueError:
        return False
    return True
