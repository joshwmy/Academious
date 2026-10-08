"""What the reader actually chose, before it becomes a recommender input.

**A draft is not an `InterestProfile`, and the distance between them is the
point.** A draft holds a reader's words and choices: *recommendation systems*,
*core interest*, *this paper*, *mostly newest*. A profile holds weights,
vectors, horizons and polarities. If HTTP request bodies were allowed to
construct profiles directly, every future change to the recommender's units
would become a breaking change to the public API, and every human-facing label
would have to be spelled the way the ranker spells it.

So the draft is the contract with the reader, `levels.py` owns the translation,
and `builder.py` performs it. The draft is also the thing the client keeps
between requests, which is what makes the whole workflow stateless: there is
nowhere on the server for an anonymous profile to live, and nothing here tries
to find one.

**Validation returns issues rather than raising.** A reader who typed one
interest too short and one field that does not exist should be told both, not
the first. `validate` therefore never throws: it returns a normalised draft and
a list of issues, and the caller decides what an error means. `builder.build` is
what refuses.

**Normalisation merges duplicates but never deletes a contradiction.** *machine
learning* and *Machine-Learning* are one interest and are merged silently,
because they are the same words. An interest that appears as both wanted and
unwanted is *not* resolved: no reading of that input is safe to guess at, so it
is reported and the profile is refused until the reader says which they meant.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum

from academious.core.text import normalise_title
from academious.ingest import taxonomy
from academious.onboarding.levels import (
    IMPORTANCE_ORDER,
    Avoidance,
    ExplorationLevel,
    FreshnessLevel,
    Importance,
    PublicationStage,
)
from academious.personalise.profile import MAX_INTERESTS, MIN_DESCRIPTION_CHARS, Horizon

#: Per-stage limits. Each exists to stop one request from costing an unbounded
#: amount of work: every text interest is an embedding to compute and a distance
#: expression in the candidate scan, and every example paper is a row to fetch.
#: `MAX_INTERESTS` in `profile.py` is the binding constraint on the total; these
#: give a reader a specific message about the stage they are on rather than an
#: arithmetic one about a number they never saw.
MAX_BROAD_FIELDS = 8
MAX_TEXT_INTERESTS = 12
MAX_EXAMPLE_PAPERS = 8
MAX_NEGATIVE_INTERESTS = 8
MAX_BLOCKED_TOPICS = 16

#: Longest free-text interest. Long enough for a sentence describing a research
#: area, short enough that it cannot become a way to post prose to the server.
#: SPECTER2 truncates at 512 tokens regardless, so anything beyond this would be
#: discarded by the model rather than used.
MAX_INTEREST_CHARS = 200


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True, slots=True)
class DraftIssue:
    """Something wrong with, or changed about, one part of the draft.

    `code` is for a client to branch on and `message` is for a person to read.
    `subject` names the specific interest or paper, so a form can put the
    message next to the input that caused it instead of at the top of a page.
    """

    code: str
    message: str
    severity: Severity = Severity.ERROR
    subject: str | None = None


@dataclass(frozen=True, slots=True)
class TextInterest:
    """Something the reader typed, in their own words."""

    text: str
    importance: Importance = Importance.INTERESTED
    #: Onboarding always produces long-term interests. Refinement is the only
    #: thing that sets SHORT, and `refine.py` says why.
    horizon: Horizon = Horizon.LONG
    #: What to call it in a summary or an explanation. Defaults to the text,
    #: which is already the reader's own phrasing.
    label: str | None = None

    @property
    def display(self) -> str:
        return self.label or self.text


@dataclass(frozen=True, slots=True)
class ExamplePaper:
    """A paper the reader picked as *more like this*.

    The paper id is kept rather than a text label taken from its title. A title
    re-encoded as free text is a worse representation of a paper than the
    paper's own embedding, which already exists, and it loses the provenance
    that lets an explanation say *similar to a paper you chose*.
    """

    paper_id: uuid.UUID
    importance: Importance = Importance.INTERESTED
    horizon: Horizon = Horizon.LONG
    #: The title, filled in by whatever resolved the paper. Absent is fine; the
    #: summary falls back to naming it as a chosen paper.
    label: str | None = None


@dataclass(frozen=True, slots=True)
class NegativeInterest:
    """Something the reader said they do not want, in their own words."""

    text: str
    strength: Avoidance = Avoidance.AVOID
    label: str | None = None

    @property
    def display(self) -> str:
        return self.label or self.text


@dataclass(frozen=True, slots=True)
class NegativePaper:
    """A paper the reader pushed away in the preview."""

    paper_id: uuid.UUID
    strength: Avoidance = Avoidance.AVOID
    label: str | None = None


@dataclass(frozen=True, slots=True)
class DiscoveryChoices:
    """How the reader wants discovery done. Three levels, no numbers."""

    freshness: FreshnessLevel = FreshnessLevel.BALANCED
    exploration: ExplorationLevel = ExplorationLevel.BALANCED
    publication: PublicationStage = PublicationStage.INCLUDE_PREPRINTS


@dataclass(frozen=True, slots=True)
class ProfileDraft:
    """Everything the reader chose, in the shape they chose it.

    Frozen, so a refinement produces a new draft rather than mutating one the
    caller still holds. That matters more than usual here: the client owns the
    draft between requests, and an in-place update on the server would be state
    the architecture claims not to have.
    """

    #: Broad areas, as `ingest.taxonomy` field slugs. Carries no importance:
    #: `field_affinity` is a binary feature and a field interest matches nothing
    #: semantically, so an importance level on a broad area would be a control
    #: connected to nothing. Stage 1 is orientation.
    fields: tuple[str, ...] = ()
    interests: tuple[TextInterest, ...] = ()
    example_papers: tuple[ExamplePaper, ...] = ()
    negatives: tuple[NegativeInterest, ...] = ()
    negative_papers: tuple[NegativePaper, ...] = ()
    #: Canonical topic ids to exclude outright. A hard filter, so only ids from
    #: the corpus vocabulary belong here - never free text.
    blocked_topics: tuple[str, ...] = ()
    discovery: DiscoveryChoices = field(default_factory=DiscoveryChoices)

    @property
    def positive_count(self) -> int:
        return len(self.fields) + len(self.interests) + len(self.example_papers)

    @property
    def total_interests(self) -> int:
        return self.positive_count + len(self.negatives) + len(self.negative_papers)

    def is_empty(self) -> bool:
        return self.total_interests == 0


def canonical(text: str) -> str:
    """The form two interests are compared in.

    `core.text.normalise_title` is the right fold and already exists: it strips
    markup and accents, casefolds, and turns every non-alphanumeric run into a
    space. So *Machine-Learning*, *machine learning* and *MACHINE  LEARNING*
    collapse to one string, and no dictionary is involved.

    What it deliberately does not do is expand abbreviations. *ML* stays
    distinct from *machine learning*, and *RAG* from *retrieval augmented
    generation*. A merge is irreversible and a false one silently deletes an
    interest the reader stated, while two similar interests cost one extra
    distance in the candidate scan. The asymmetry is the whole argument.
    """
    return normalise_title(text)


def validate(draft: ProfileDraft) -> tuple[ProfileDraft, tuple[DraftIssue, ...]]:
    """Normalise a draft and say everything wrong with it.

    Never raises. Returns the draft as it would be used - deduplicated, trimmed,
    with unknown values removed - together with the issues describing every
    change made and every refusal.
    """
    issues: list[DraftIssue] = []

    fields = _clean_fields(draft.fields, issues)
    interests = _clean_interests(draft.interests, issues)
    negatives = _clean_negatives(draft.negatives, issues)
    papers = _clean_papers(draft.example_papers, issues)
    negative_papers = _clean_negative_papers(draft.negative_papers, papers, issues)
    blocked = _clean_blocked_topics(draft.blocked_topics, issues)

    _check_contradictions(interests, negatives, issues)

    cleaned = replace(
        draft,
        fields=fields,
        interests=interests,
        example_papers=papers,
        negatives=negatives,
        negative_papers=negative_papers,
        blocked_topics=blocked,
    )
    _check_totals(cleaned, issues)
    return cleaned, tuple(issues)


def errors(issues: Iterable[DraftIssue]) -> tuple[DraftIssue, ...]:
    return tuple(issue for issue in issues if issue.severity is Severity.ERROR)


# --- per-stage cleaning -------------------------------------------------------


def _clean_fields(slugs: Sequence[str], issues: list[DraftIssue]) -> tuple[str, ...]:
    kept: list[str] = []
    for slug in dict.fromkeys(slug.strip() for slug in slugs):
        if not slug:
            continue
        if not taxonomy.is_field(slug):
            # Refused rather than ignored, exactly as `/papers` refuses an
            # unknown field filter: silently dropping it would answer a request
            # about biology with a profile that has never heard of it.
            issues.append(
                DraftIssue(
                    code="unknown_field",
                    message=f"{slug!r} is not a subject field. GET /fields lists the vocabulary.",
                    subject=slug,
                )
            )
            continue
        kept.append(slug)

    if len(kept) > MAX_BROAD_FIELDS:
        issues.append(
            DraftIssue(
                code="too_many_fields",
                message=f"Choose at most {MAX_BROAD_FIELDS} broad areas; you chose {len(kept)}.",
            )
        )
    return tuple(kept)


def _clean_interests(
    interests: Sequence[TextInterest], issues: list[DraftIssue]
) -> tuple[TextInterest, ...]:
    merged: dict[str, TextInterest] = {}
    for raw in interests:
        text = " ".join(raw.text.split())
        if not _check_text(text, issues):
            continue
        key = canonical(text)
        entry = replace(raw, text=text)
        if key in merged:
            # Keep the stronger claim. A reader who listed one subject twice,
            # once as core, meant core.
            issues.append(
                DraftIssue(
                    code="duplicate_interest",
                    message=f"{text!r} was listed more than once and has been merged.",
                    severity=Severity.WARNING,
                    subject=text,
                )
            )
            merged[key] = _stronger_interest(merged[key], entry)
        else:
            merged[key] = entry

    kept = tuple(merged.values())
    if len(kept) > MAX_TEXT_INTERESTS:
        issues.append(
            DraftIssue(
                code="too_many_interests",
                message=(
                    f"Add at most {MAX_TEXT_INTERESTS} specific interests; you added {len(kept)}."
                ),
            )
        )
    return kept


def _clean_negatives(
    negatives: Sequence[NegativeInterest], issues: list[DraftIssue]
) -> tuple[NegativeInterest, ...]:
    merged: dict[str, NegativeInterest] = {}
    for raw in negatives:
        text = " ".join(raw.text.split())
        if not _check_text(text, issues):
            continue
        key = canonical(text)
        entry = replace(raw, text=text)
        if key in merged:
            issues.append(
                DraftIssue(
                    code="duplicate_negative",
                    message=f"{text!r} was listed more than once and has been merged.",
                    severity=Severity.WARNING,
                    subject=text,
                )
            )
            if entry.strength is Avoidance.AVOID:
                merged[key] = entry
        else:
            merged[key] = entry

    kept = tuple(merged.values())
    if len(kept) > MAX_NEGATIVE_INTERESTS:
        issues.append(
            DraftIssue(
                code="too_many_negatives",
                message=(
                    f"Add at most {MAX_NEGATIVE_INTERESTS} things to avoid; you added {len(kept)}."
                ),
            )
        )
    return kept


def _clean_papers(
    papers: Sequence[ExamplePaper], issues: list[DraftIssue]
) -> tuple[ExamplePaper, ...]:
    merged: dict[uuid.UUID, ExamplePaper] = {}
    for raw in papers:
        if raw.paper_id in merged:
            issues.append(
                DraftIssue(
                    code="duplicate_example_paper",
                    message="The same paper was chosen twice and has been merged.",
                    severity=Severity.WARNING,
                    subject=str(raw.paper_id),
                )
            )
            merged[raw.paper_id] = _stronger_paper(merged[raw.paper_id], raw)
            continue
        merged[raw.paper_id] = raw

    kept = tuple(merged.values())
    if len(kept) > MAX_EXAMPLE_PAPERS:
        issues.append(
            DraftIssue(
                code="too_many_example_papers",
                message=(
                    f"Choose at most {MAX_EXAMPLE_PAPERS} example papers; you chose {len(kept)}."
                ),
            )
        )
    return kept


def _clean_negative_papers(
    papers: Sequence[NegativePaper],
    positives: Sequence[ExamplePaper],
    issues: list[DraftIssue],
) -> tuple[NegativePaper, ...]:
    chosen = {paper.paper_id for paper in positives}
    merged: dict[uuid.UUID, NegativePaper] = {}
    for raw in papers:
        if raw.paper_id in chosen:
            issues.append(
                DraftIssue(
                    code="contradictory_example_paper",
                    message=(
                        "The same paper is listed as an example to follow and as one to "
                        "avoid. Remove it from one of them."
                    ),
                    subject=str(raw.paper_id),
                )
            )
            continue
        merged[raw.paper_id] = raw
    return tuple(merged.values())


def _clean_blocked_topics(topics: Sequence[str], issues: list[DraftIssue]) -> tuple[str, ...]:
    kept = tuple(dict.fromkeys(topic.strip() for topic in topics if topic.strip()))
    if len(kept) > MAX_BLOCKED_TOPICS:
        issues.append(
            DraftIssue(
                code="too_many_blocked_topics",
                message=f"Block at most {MAX_BLOCKED_TOPICS} topics; you blocked {len(kept)}.",
            )
        )
    return kept


# --- cross-stage checks -------------------------------------------------------


def _check_text(text: str, issues: list[DraftIssue]) -> bool:
    if len(text) < MIN_DESCRIPTION_CHARS:
        issues.append(
            DraftIssue(
                code="interest_too_short",
                message=(
                    f"{text!r} is too short to match against. Describe it in at least "
                    f"{MIN_DESCRIPTION_CHARS} characters - 'RAG' finds far less than "
                    "'retrieval augmented generation'."
                ),
                subject=text,
            )
        )
        return False
    if len(text) > MAX_INTEREST_CHARS:
        issues.append(
            DraftIssue(
                code="interest_too_long",
                message=(
                    f"An interest may be at most {MAX_INTEREST_CHARS} characters; "
                    f"this one is {len(text)}."
                ),
                subject=text[:60],
            )
        )
        return False
    return True


def _check_contradictions(
    interests: Sequence[TextInterest],
    negatives: Sequence[NegativeInterest],
    issues: list[DraftIssue],
) -> None:
    """An interest stated as both wanted and unwanted is refused, not resolved.

    Either reading changes the feed materially and neither is recoverable from
    the input. Guessing would mean a reader who mistyped one screen quietly gets
    the opposite of what they asked for on the other.
    """
    wanted = {canonical(interest.text) for interest in interests}
    for negative in negatives:
        if canonical(negative.text) in wanted:
            issues.append(
                DraftIssue(
                    code="contradictory_interest",
                    message=(
                        f"{negative.text!r} is listed both as an interest and as something "
                        "to avoid. Remove it from one of them."
                    ),
                    subject=negative.text,
                )
            )


def _check_totals(draft: ProfileDraft, issues: list[DraftIssue]) -> None:
    if draft.positive_count == 0:
        issues.append(
            DraftIssue(
                code="no_positive_interest",
                message=(
                    "Choose at least one broad area, specific interest or example paper. "
                    "A profile of only dislikes has nothing to rank."
                ),
            )
        )
    if draft.total_interests > MAX_INTERESTS:
        issues.append(
            DraftIssue(
                code="too_many_total_interests",
                message=(
                    f"A profile holds at most {MAX_INTERESTS} interests in total, counting "
                    f"broad areas, specific interests, example papers and dislikes. "
                    f"This one has {draft.total_interests}."
                ),
            )
        )


def _stronger_interest(left: TextInterest, right: TextInterest) -> TextInterest:
    """The entry whose importance is higher, preferring the earlier on a tie."""
    if IMPORTANCE_ORDER.index(right.importance) > IMPORTANCE_ORDER.index(left.importance):
        return right
    return left


def _stronger_paper(left: ExamplePaper, right: ExamplePaper) -> ExamplePaper:
    if IMPORTANCE_ORDER.index(right.importance) > IMPORTANCE_ORDER.index(left.importance):
        return right
    return left
