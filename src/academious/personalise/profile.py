"""What a reader cares about: several things at once, some of them negative.

**One representation per coherent interest, never an average.** A reader who
follows computer vision, distributed systems and cancer genomics has a mean
vector pointing at nothing - mildly close to all three, relevant to none, and a
feed full of mush. Interests stay separate here and are combined at scoring
time by `max`, so a paper is judged by the interest it actually answers. The
`argmax` names that interest, which is why *why am I seeing this* needs no LLM:
an explanation that falls out of the ranking cannot drift from it.

**Negatives are first-class, not subtracted.** "Not image-generation papers"
describes a region of the embedding space, not a small correction to a positive
interest. Representing it as negative weight on a positive centroid would move
that centroid somewhere the reader never asked for. It lives in the same
structure with `polarity=NEGATIVE` and is applied as its own feature.

**Two horizons.** A long-term interest is what a reader stably cares about; a
short-term one is what they are doing this week. Someone who follows ML systems
may spend a fortnight on diffusion models, and the feed should notice without
overwriting the year of systems interest behind it. They are held apart and
weighted at scoring time (`features.py`), not merged - merging is irreversible
and this has to be reversible. The framing is LSTUR's long- and short-term user
representation (recommenders-team, MIT); the idea, not the model.

**Nothing here is a user.** No account id, no persistence. A profile is
constructed from a request body exactly as a query string is today, which keeps
the ranker measurable before any personal data exists and makes the eventual
account work a table that stores one of these rather than a redesign of what
ranking consumes. Interests carry timestamps and provenance anyway, because
Stage B will derive them from behaviour and "where did this interest come from"
is unanswerable if it was not recorded when it was cheap.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import StrEnum

import numpy as np

#: A weight is relative emphasis, not a probability: weights need not sum to
#: anything. 1.0 is "as important as any other interest". Bounded only so a
#: typo cannot silently turn one interest into the whole profile.
MIN_WEIGHT = 0.0
MAX_WEIGHT = 10.0

#: Enough characters to be a research interest rather than a keyword. SPECTER2
#: reads sentences; "cancer" encodes to far less than "tumour evolution under
#: chemotherapy". A floor, not advice - the API layer should say the better
#: thing to a reader.
MIN_DESCRIPTION_CHARS = 12

#: Interests per profile. Each semantic one is a distance expression in the
#: candidate scan, so this bounds the cost of a feed request as much as the
#: shape of a profile. Measured in docs/performance.md.
MAX_INTERESTS = 16

_WHITESPACE = re.compile(r"\s+")


class ProfileError(ValueError):
    """A profile that cannot be scored against. Raised at construction."""


class InterestKind(StrEnum):
    """Where an interest came from, which decides how it is matched.

    `STATED` and `PAPER` are semantic: they carry a vector and match by cosine.
    `TOPIC`, `FIELD`, `AUTHOR` and `VENUE` are exact: they carry a `value` and
    match by set membership. `DERIVED` is Stage B - inferred from behaviour,
    semantic, and marked so it can be aged out or explained differently.
    """

    STATED = "stated"
    PAPER = "paper"
    TOPIC = "topic"
    FIELD = "field"
    AUTHOR = "author"
    VENUE = "venue"
    DERIVED = "derived"


#: Kinds matched by embedding rather than by identifier.
SEMANTIC_KINDS = frozenset({InterestKind.STATED, InterestKind.PAPER, InterestKind.DERIVED})


class Horizon(StrEnum):
    LONG = "long"
    SHORT = "short"


class Polarity(StrEnum):
    POSITIVE = "positive"
    NEGATIVE = "negative"


@dataclass(frozen=True, slots=True)
class Interest:
    """One thing a reader cares about, or has said they do not.

    `key` is identity and must be stable across profile updates: Stage B
    strengthens an existing interest by key rather than appending a near
    duplicate. `label` is what a reader calls it and what an explanation quotes
    back, so it is theirs. `text` is what gets encoded; `value` is what gets
    matched exactly. Exactly one of them is required, decided by `kind`.
    """

    key: str
    kind: InterestKind
    label: str
    #: Encodable description, for semantic kinds.
    text: str | None = None
    #: Exact identifier - topic id, field slug, author id, venue name.
    value: str | None = None
    #: A vector supplied directly, for a PAPER interest seeded from an existing
    #: paper embedding rather than from text.
    vector: np.ndarray | None = None
    weight: float = 1.0
    #: How sure we are this is an interest at all. Stated interests are 1.0;
    #: Stage B will derive interests at less. Kept separate from `weight`,
    #: which is how much the reader wants of it - a confident read of a mild
    #: preference is not the same as a guess about a strong one.
    confidence: float = 1.0
    horizon: Horizon = Horizon.LONG
    polarity: Polarity = Polarity.POSITIVE
    #: Free text saying what produced this. "stated at signup", "derived from
    #: 12 saves", "followed from feed item".
    provenance: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        key = _tidy(self.key)
        label = _tidy(self.label) or key
        if not key:
            raise ProfileError("an interest needs a key")
        if not MIN_WEIGHT <= self.weight <= MAX_WEIGHT:
            raise ProfileError(
                f"interest {key!r}: weight {self.weight} outside [{MIN_WEIGHT}, {MAX_WEIGHT}]"
            )
        if not 0.0 <= self.confidence <= 1.0:
            raise ProfileError(f"interest {key!r}: confidence {self.confidence} outside [0, 1]")

        if self.is_semantic:
            text = _tidy(self.text or "")
            if self.vector is None and len(text) < MIN_DESCRIPTION_CHARS:
                raise ProfileError(
                    f"interest {key!r}: describe it in at least "
                    f"{MIN_DESCRIPTION_CHARS} characters, or supply a vector"
                )
            object.__setattr__(self, "text", text or None)
        elif not _tidy(self.value or ""):
            raise ProfileError(f"interest {key!r}: kind {self.kind} needs a value")
        else:
            object.__setattr__(self, "value", _tidy(self.value or ""))

        object.__setattr__(self, "key", key)
        object.__setattr__(self, "label", label)

    @property
    def is_semantic(self) -> bool:
        return self.kind in SEMANTIC_KINDS

    @property
    def effective_weight(self) -> float:
        """Weight discounted by how sure we are the interest is real."""
        return self.weight * self.confidence

    def needs_encoding(self) -> bool:
        return self.is_semantic and self.vector is None and bool(self.text)

    def with_vector(self, vector: Sequence[float]) -> Interest:
        return replace(self, vector=np.asarray(vector, dtype=np.float32))


@dataclass(frozen=True, slots=True)
class Preferences:
    """Standing choices that shape a feed without being interests.

    Separate from `Interest` because they are not things to match against -
    they are how the reader wants matching done, and a ranker consumes them
    differently.
    """

    #: 0.0 keeps the feed to established interests; 1.0 spends the full
    #: exploration budget on adjacent work. A dial the reader owns, because
    #: appetite for surprise is a preference and not something to infer.
    exploration: float = 0.15
    #: Emphasis on short-term interests relative to long-term ones. 0.5 is
    #: even. Higher makes this week's reading dominate.
    recency_of_interest: float = 0.5
    #: >1 favours preprints, <1 favours peer-reviewed work, 1.0 is neutral.
    preprint_appetite: float = 1.0

    def __post_init__(self) -> None:
        for name in ("exploration", "recency_of_interest"):
            value = getattr(self, name)
            if not 0.0 <= value <= 1.0:
                raise ProfileError(f"{name} must be in [0, 1], got {value}")
        if not 0.0 <= self.preprint_appetite <= 2.0:
            raise ProfileError(f"preprint_appetite must be in [0, 2], got {self.preprint_appetite}")


@dataclass(frozen=True, slots=True)
class InterestProfile:
    """A reader's interests and standing preferences, before encoding."""

    interests: tuple[Interest, ...] = ()
    preferences: Preferences = field(default_factory=Preferences)
    #: Topics whose papers must not appear at all. A hard filter rather than a
    #: penalty: a reader who said *not this* did not ask to see it ranked
    #: politely, and a penalty can always be out-competed by a large enough
    #: bonus somewhere else.
    blocked_topics: frozenset[str] = frozenset()
    blocked_authors: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if not self.interests:
            raise ProfileError("a profile needs at least one interest")
        if len(self.interests) > MAX_INTERESTS:
            raise ProfileError(
                f"{len(self.interests)} interests: at most {MAX_INTERESTS}, because each "
                "semantic one costs a distance expression per feed request"
            )
        duplicate = _first_duplicate(interest.key for interest in self.interests)
        if duplicate is not None:
            raise ProfileError(f"two interests share the key {duplicate!r}")
        if not self.positive:
            raise ProfileError("a profile needs at least one positive interest")
        if sum(i.effective_weight for i in self.positive) <= 0:
            raise ProfileError("every positive interest has zero weight, so nothing can rank")

    # -- views ---------------------------------------------------------------

    @property
    def positive(self) -> tuple[Interest, ...]:
        return tuple(i for i in self.interests if i.polarity is Polarity.POSITIVE)

    @property
    def negative(self) -> tuple[Interest, ...]:
        return tuple(i for i in self.interests if i.polarity is Polarity.NEGATIVE)

    def semantic(self, polarity: Polarity = Polarity.POSITIVE) -> tuple[Interest, ...]:
        return tuple(i for i in self.interests if i.polarity is polarity and i.is_semantic)

    def values_of(
        self, kind: InterestKind, polarity: Polarity = Polarity.POSITIVE
    ) -> frozenset[str]:
        """Exact-match identifiers for one kind - followed topics, authors, venues."""
        return frozenset(
            i.value
            for i in self.interests
            if i.kind is kind and i.polarity is polarity and i.value is not None
        )

    def pending_encoding(self) -> tuple[Interest, ...]:
        """Semantic interests that still need a vector, in a stable order."""
        return tuple(i for i in self.interests if i.needs_encoding())

    def with_vectors(self, vectors: Sequence[Sequence[float]]) -> InterestProfile:
        """Attach vectors to `pending_encoding()`, in that same order."""
        pending = self.pending_encoding()
        if len(vectors) != len(pending):
            raise ProfileError(f"{len(vectors)} vectors for {len(pending)} unencoded interests")
        filled = dict(zip((i.key for i in pending), vectors, strict=True))
        return replace(
            self,
            interests=tuple(
                i.with_vector(filled[i.key]) if i.key in filled else i for i in self.interests
            ),
        )


@dataclass(frozen=True, slots=True)
class EncodedProfile:
    """A profile whose semantic interests all carry vectors, under one model.

    `model_key` travels with the vectors because a profile encoded under one
    model says nothing about a corpus embedded under another, and the mismatch
    produces plausible nonsense rather than an error.

    Positive and negative vectors are held as separate matrices so that scoring
    is two `max` operations rather than one with sign bookkeeping - and so that
    a profile with no negatives costs nothing for the feature it does not use.
    """

    profile: InterestProfile
    model_key: str
    positive: tuple[Interest, ...] = field(init=False)
    negative: tuple[Interest, ...] = field(init=False)
    positive_vectors: np.ndarray = field(init=False)
    negative_vectors: np.ndarray = field(init=False)
    positive_weights: np.ndarray = field(init=False)

    def __post_init__(self) -> None:
        unencoded = [i.key for i in self.profile.interests if i.needs_encoding()]
        if unencoded:
            raise ProfileError(f"interests still need vectors: {sorted(unencoded)}")

        positive = self.profile.semantic(Polarity.POSITIVE)
        negative = self.profile.semantic(Polarity.NEGATIVE)
        if not positive:
            raise ProfileError("a profile needs at least one positive semantic interest")

        object.__setattr__(self, "positive", positive)
        object.__setattr__(self, "negative", negative)
        object.__setattr__(self, "positive_vectors", _stack(positive))
        object.__setattr__(self, "negative_vectors", _stack(negative))
        object.__setattr__(
            self,
            "positive_weights",
            np.asarray([i.effective_weight for i in positive], dtype=np.float32),
        )

    @property
    def preferences(self) -> Preferences:
        return self.profile.preferences

    def __len__(self) -> int:
        return len(self.profile.interests)


def encode(
    profile: InterestProfile, vectors: Sequence[Sequence[float]], *, model_key: str
) -> EncodedProfile:
    """Fill in the missing vectors and freeze the profile for scoring."""
    return EncodedProfile(profile=profile.with_vectors(vectors), model_key=model_key)


def _stack(interests: Sequence[Interest]) -> np.ndarray:
    if not interests:
        return np.zeros((0, 0), dtype=np.float32)
    return np.vstack([np.asarray(i.vector, dtype=np.float32) for i in interests])


def _tidy(value: str) -> str:
    return _WHITESPACE.sub(" ", (value or "").strip())


def _first_duplicate(values: Iterable[str]) -> str | None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            return value
        seen.add(value)
    return None
