# ADR 0011: Research profile creation is part of the recommender

**Status:** Accepted (Phase 3)

## Context

[ADR 0010](0010-recommendation-architecture.md) built the recommender and left
one thing unanswered: where the `InterestProfile` comes from. The benchmark
profiles are written in Python by hand. No person has ever produced one, and
until they can, the ranking is measurable only against readers we invented.

The tempting framing is *onboarding UI* — a form, four screens, a save button.
That framing is wrong in a way that shows up later and is expensive to fix: the
profile is the recommender's input, and no ranking recovers from an input that
never captured what the reader meant. A questionnaire bolted onto a recommender
produces a recommender that looks bad for reasons nobody can locate.

Two constraints, both from ADR 0010 and unchanged:

* **There are no accounts.** Nothing may be persisted about a person.
* **There is no interaction data.** Nothing may be learned from behaviour.

## Decision

**Profile creation is a stage of the recommendation pipeline, with its own
package, its own tests and its own evaluation.**

```
ProfileDraft --> validate --> ProfileBuilder --> InterestProfile --> build_feed --> preview
      ^                                                 |
      +---------------------- refine <------------------+
```

### 1. A draft is not a profile

`ProfileDraft` holds what a reader chose in the words they chose: *recommendation
systems*, *core interest*, *this paper*, *mostly newest*. `InterestProfile` holds
weights, vectors, horizons and polarities. They are separate types and the
translation is one function.

The alternative — HTTP request bodies constructing `InterestProfile` directly —
makes every future change to the recommender's units a breaking change to the
public API, and forces every human-facing label to be spelled the way the ranker
spells it. It also means a reader's stated choices stop existing the moment they
are converted, so nothing can be re-derived when the mapping improves.

### 2. Human levels, and one place that knows what they are worth

A reader chooses *core*, *interested* or *occasional*; never `weight=0.83`.
`onboarding/levels.py` is the only module permitted to write a profile number,
and it holds the inverse mappings too, so a summary describes the profile that
was built rather than the form that was filled in.

| Choice | Becomes | Where it acts |
|---|---|---|
| Core / Interested / Occasional | `Interest.weight` 1.0 / 0.7 / 0.4 | `interest_emphasis` |
| Less / Avoid | negative `Interest.weight` 0.6 / 1.0 | `negative_affinity` |
| Mostly newest / Balanced / Best match | `freshness_appetite` 1.0 / 0.5 / 0.0 | `ranking.weights_for` |
| Focused / Balanced / Adjacent | `exploration` 0.05 / 0.15 / 0.30 | exploration budget and cap |
| Preprints / Prefer reviewed / Reviewed only | `preprint_appetite` 1.0 / 0.4 / 0.0 | `preprint_fit`, plus a hard filter for *only* |

### 3. A control a reader can choose is one the pipeline can honour

This rule both removed and added work.

*Peer-reviewed only* could not be honoured: the pipeline had no publication
filter, and a preference expressed as a weight can always be out-competed. Since
the word *only* is a promise, `InterestProfile.require_peer_reviewed` was added
and `feed._apply_hard_filters` enforces it — beside blocked topics, for the same
reason blocks are hard.

*Exploration* was a control connected to nothing over the corpus: the feed caps
how many exploration-only items may appear, and no database source proposed any,
so the cap was never approached whatever the reader chose. `AdjacentInterestSource`
now generates them, at the cost of a second scan.

*Importance on a broad area* was removed. A field interest matches nothing
semantically and `field_affinity` is binary, so a level there would have been a
dial wired to nothing. Stage 1 is orientation.

### 4. Deduplicate by exact canonical form only

*machine learning*, *Machine-Learning* and *MACHINE  LEARNING* are one interest.
*ML* and *machine learning* are two.

Embedding-based merging was rejected. The asymmetry decides it: a false merge
silently deletes an interest a reader stated and is irreversible, while two
similar interests cost one additional distance expression in the candidate scan.
No LLM is involved, as none is anywhere in this codebase.

### 5. Preview is mandatory; refinement edits the draft

There is nobody to save a profile for, and a profile whose consequences the
reader has not seen is a guess. So the endpoint returns the feed, always.

Refinement returns a corrected **draft**, and the profile is rebuilt from it.
Editing the profile directly would put the reader's stated choices and the
system's representation of them permanently out of step, so the summary would
stop describing what they actually chose.

Each action is one stated rule with one visible effect. *More like this* adds the
paper as a **short-term** example interest — a reaction to one item is evidence
about this week, not about the year, and the two horizons exist so this does not
overwrite a standing interest. *Not interested* is stronger than *less like this*
in two ways at once: the dislike is recorded at full strength, and the interest
that produced the item loses one level.

### 6. Stateless, and not as a temporary compromise

The client holds the draft and sends it back. The server normalises, builds,
previews and forgets. There is no session, no anonymous id and no server-side
cache keyed by caller — an in-memory store would be state the architecture claims
not to have, and would break the moment a second worker existed.

When accounts arrive, what gets stored is the draft plus the profile derived from
it. `PROFILE_SCHEMA_VERSION` travels on every response so a draft a client stored
today is recognisable by a server later. Nothing in this package has to be
replaced for that to happen.

## Consequences

**A cold-start profile can now be encoded at all.** `EncodedProfile` required at
least one positive *semantic* interest, so the reader `eval/profiles.py` calls
rec-06 — someone who only ticked boxes — could be constructed but never run
through `build_feed`. That is exactly the reader onboarding must serve, and the
requirement is now one positive interest of any kind.

**Two additive fields on the core domain.** `Preferences.freshness_appetite` and
`InterestProfile.require_peer_reviewed`, both defaulted so every existing profile
behaves as it did. Freshness could not go anywhere else: `Ranker.rank` sees
features and not the profile, so a preference that must reach a weight has to be
translated before ranking, and `ranking.weights_for` is that translation.

**Interest suggestions are not built.** `paper.topics` is JSONB with no index; a
containment query per keystroke over 98,000 rows is not a facility. The 26-field
vocabulary is already served by `GET /fields`, so stage 1 needs nothing new, and
free-text suggestions wait for a topic table (backlog RETR-008).

**CORS now allows POST.** A draft is too large and too structured for a query
string. `allow_credentials` stays `False`, the origin list stays explicit, and
nothing the app accepts a POST for writes to the database, so a cross-origin POST
can do no more than ask for a feed the same caller could ask for directly.

**Still not measured against a person.** These are behavioural invariants — a
core interest outranks an occasional one, a dislike lowers what it matches, an
example paper pulls in work like it. They say the reader's choices survive into
the feed. They do not say the feed is good, and nothing here should be read as
saying so until someone has judged pooled results.
