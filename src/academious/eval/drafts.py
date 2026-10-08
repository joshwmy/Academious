"""Benchmark drafts: what real readers would actually type at signup.

`profiles.py` holds six `InterestProfile`s written directly, to evaluate the
*ranker*. These are the stage before: what a person chooses on the onboarding
screens, from which a profile has to be built. The two are deliberately not one
set of fixtures, because they answer different questions - *does the feed serve
this reader* against *does profile construction produce the reader we meant*.

Three shapes, chosen for what they can disagree about:

* **A specialist within one field.** Several close interests plus a dislike
  inside the same area, which is the hard case for a negative: a dislike about
  something the reader never sees is untested.
* **A reader in a different discipline entirely**, so nothing about the
  vocabulary of the first can be load-bearing.
* **An interdisciplinary reader**, whose interests span two broad areas and
  whose feed has to represent both.

Every one of them is buildable without a database, a model or a network: a test
supplies an encoder and a paper resolver. Ground truth about *papers* is not
here and is not implied - these say who is asking, and `eval/recommend.py` is
explicit that what counts as a good answer needs a person.
"""

from __future__ import annotations

from dataclasses import dataclass

from academious.onboarding.draft import (
    DiscoveryChoices,
    NegativeInterest,
    ProfileDraft,
    TextInterest,
)
from academious.onboarding.levels import (
    Avoidance,
    ExplorationLevel,
    FreshnessLevel,
    Importance,
    PublicationStage,
)


@dataclass(frozen=True, slots=True)
class BenchmarkDraft:
    """One onboarding session, and what building it is meant to demonstrate."""

    id: str
    intent: str
    draft: ProfileDraft
    #: Interest texts that must survive into the built profile as separate
    #: interests. A statement about construction, checkable with no judgments.
    expect_distinct: tuple[str, ...] = ()
    notes: str = ""


DRAFTS: tuple[BenchmarkDraft, ...] = (
    BenchmarkDraft(
        id="draft-a",
        intent="An AI systems researcher: three close core interests, one "
        "secondary, one dislike adjacent to all of them.",
        draft=ProfileDraft(
            fields=("computer-science",),
            interests=(
                TextInterest("recommendation systems and personalised ranking", Importance.CORE),
                TextInterest(
                    "information retrieval, search ranking and evaluation", Importance.CORE
                ),
                TextInterest(
                    "distributed training and serving of machine learning models",
                    Importance.CORE,
                ),
                TextInterest(
                    "retrieval augmented generation for language models",
                    Importance.INTERESTED,
                ),
            ),
            negatives=(
                NegativeInterest(
                    "diffusion models and generative image synthesis",
                    strength=Avoidance.AVOID,
                ),
            ),
            discovery=DiscoveryChoices(
                freshness=FreshnessLevel.NEWEST_FIRST,
                exploration=ExplorationLevel.BALANCED,
                publication=PublicationStage.INCLUDE_PREPRINTS,
            ),
        ),
        expect_distinct=(
            "recommendation systems and personalised ranking",
            "information retrieval, search ranking and evaluation",
            "distributed training and serving of machine learning models",
            "retrieval augmented generation for language models",
        ),
        notes="The draft that fails loudest if close interests are merged by an "
        "over-eager deduplicator.",
    ),
    BenchmarkDraft(
        id="draft-b",
        intent="A computational biologist. Nothing in draft-a's vocabulary "
        "should be doing any work here.",
        draft=ProfileDraft(
            fields=("biochemistry-genetics-and-molecular-biology",),
            interests=(
                TextInterest("computational genomics and variant calling", Importance.CORE),
                TextInterest("protein structure prediction and folding", Importance.CORE),
                TextInterest(
                    "machine learning applied to biological sequence data",
                    Importance.INTERESTED,
                ),
            ),
            discovery=DiscoveryChoices(
                freshness=FreshnessLevel.BALANCED,
                exploration=ExplorationLevel.FOCUSED,
                publication=PublicationStage.PREFER_PEER_REVIEWED,
            ),
        ),
        expect_distinct=(
            "computational genomics and variant calling",
            "protein structure prediction and folding",
            "machine learning applied to biological sequence data",
        ),
    ),
    BenchmarkDraft(
        id="draft-c",
        intent="Interdisciplinary: two core interests in different fields, and "
        "a feed that has to represent both rather than collapsing to one.",
        draft=ProfileDraft(
            fields=("computer-science", "medicine"),
            interests=(
                TextInterest("machine learning methods and theory", Importance.CORE),
                TextInterest("cancer genomics and tumour evolution", Importance.CORE),
                TextInterest(
                    "systems that help scientists make discoveries", Importance.OCCASIONAL
                ),
            ),
            discovery=DiscoveryChoices(
                freshness=FreshnessLevel.BALANCED,
                exploration=ExplorationLevel.ADVENTUROUS,
                publication=PublicationStage.INCLUDE_PREPRINTS,
            ),
        ),
        expect_distinct=(
            "machine learning methods and theory",
            "cancer genomics and tumour evolution",
            "systems that help scientists make discoveries",
        ),
        notes="The only draft carrying an OCCASIONAL interest, so the importance "
        "mapping has something to be wrong about.",
    ),
)

_BY_ID = {draft.id: draft for draft in DRAFTS}


def get(draft_id: str) -> BenchmarkDraft:
    if draft_id not in _BY_ID:
        raise KeyError(f"unknown benchmark draft {draft_id!r}")
    return _BY_ID[draft_id]
