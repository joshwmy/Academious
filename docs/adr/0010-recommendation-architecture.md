# ADR 0010: Multi-stage recommendation architecture

**Status:** Accepted (Phase 3)

## Context

`product.md` says Academious is a personalised research discovery feed, and that
discovery — not search — is the product. Today `/papers` is reverse-chronological
and identical for everyone, and `retrieval/` answers a query it was handed. The
gap between those two sentences is the whole remaining product.

Phase 0 sketched a recommendation engine (§6): multi-centroid interest profiles,
a weighted score over seven components, `argmax` as the explanation. That sketch
is sound and this ADR keeps its substance. What it did not settle is the
**shape** of the system, and shipping the sketch literally would produce one
function that scores a paper against a profile — a scorer, not an architecture,
which every later model would have to displace by rewriting whatever calls it.

The constraint dominating every decision here: **there are no users, and so no
interaction data.** Zero impressions, zero clicks, zero saves. Any design that
needs behavioural data to function is not buildable now, and any design that
cannot absorb behavioural data later will have to be replaced.

## Decision

Adopt the multi-stage pattern industrial recommenders converge on, with each
stage a separate interface:

```
InterestProfile ─▶ CandidateSource(s) ─▶ CandidatePool
                                             │
                                             ▼
                                      FeatureExtractor
                                             │
                                             ▼
                                          Ranker            (swappable)
                                             │
                                             ▼
                                         ReRanker           (diversity)
                                             │
                                             ▼
                                        list[FeedItem]
```

**Candidate generation and ranking are different problems and get different
interfaces.** Generation asks *which few hundred papers might plausibly interest
this reader*: recall-oriented, cheap per item, allowed to be sloppy. Ranking asks
*which ten deserve attention now*: precision-oriented, expensive per item,
allowed to be slow because it sees hundreds rather than 98,000. Collapsing them
is exactly what forces a redesign later — a collaborative or sequential model
should enter as a new `CandidateSource` and change nothing downstream.

**The ranker is an interface with one implementation today.**
`DeterministicRanker` consumes named features and a weight table. A trained
ranker — logistic, GBDT, LambdaMART — becomes a second implementation over the
*same* `FeatureVector`. That is precisely why feature extraction is its own
stage rather than inlined into scoring: features are the stable contract across
the transition from hand-set weights to learned ones.

**Features are named, bounded and documented; raw engine scores never reach the
scorer.** `retrieval/types.py` refuses to rescale cosine, `ts_rank_cd` and RRF
onto a common number, because they do not measure the same thing. That refusal
is right for reporting a search result and cannot survive ranking a feed, where
choosing an order *is* committing to a trade. The resolution is not to abandon
the principle but to move the normalisation somewhere visible: every feature
declares its range, direction, missing-data behaviour and transform in
`features.py`, and the scorer only ever sees `[0, 1]`.

**Profiles carry several interests, positive and negative, long- and
short-term.** A mean vector over oncology, distributed systems and climate
policy points at nothing. Interests stay separate; a paper scores `max` over
them, and `argmax` names the interest that earned the position — an explanation
that is a by-product of ranking cannot drift from it, while one generated
separately eventually will. Negatives are explicit rather than subtracted
invisibly, because "I don't want image-generation papers" describes a region of
the space, not a small correction to a positive interest.

**Two horizons, not one.** A long-term profile holds what a reader stably cares
about; a short-term profile holds what they are doing this week. They are
combined at scoring time with a configurable emphasis rather than merged into
storage, so a fortnight spent reading diffusion papers can influence the feed
without overwriting a year of systems interest. The framing is taken from
LSTUR's long- and short-term user representation (recommenders-team, MIT) — the
idea, not the model.

**Exploration exists as a concept and a budget, not as a bandit.** A contextual
bandit needs a reward stream to learn from and an online experiment to be judged
by; Academious has neither. What exists now is an explicit share of the feed
that adjacent-topic candidates may occupy, subject to a relevance floor. A random
paper is noise, not serendipity.

**Feedback events are typed now and persisted later.** `impression` in
particular is defined from the start: without knowing what a reader was *shown*,
a missing click is uninterpretable, and a dataset lacking impressions cannot
train a ranker however many clicks it has. This is the one part of the future
system that is expensive to retrofit and nearly free to define early.

**The feed is stateless in this phase.** A profile arrives in a request the way
a query string does today. No accounts, no user tables, no personal data — so
PROD-002, SEC-008 and DEPLOY-006 stay deferred until there is evidence the
ranking is worth protecting.

### Evolution stages

| Stage | Needs | Enters as |
|---|---|---|
| **A** Content cold start | Nothing. Built now. | `SemanticInterestSource`, `TopicSource`, `DeterministicRanker` |
| **B** Behavioural profile | Interaction logging | Derived interests appended to the profile; seen/fatigue features |
| **C** Collaborative | User-item density | A new `CandidateSource` (ALS/BPR) |
| **D** Sequential | Ordered histories | A new `CandidateSource` plus a session-derived short-term profile |
| **E** Learned ranker | Impressions with outcomes | A second `Ranker` over the same `FeatureVector` |
| **F** Exploration policy | Online reward stream | A policy replacing the fixed exploration budget |

Each stage adds an implementation of an interface defined here. None requires
replacing the stage before it.

## Open-source projects evaluated

Inspected for architecture, reusable concepts, licence, maintenance and
dependency weight. **No new runtime dependency is added by this ADR.**

| Project | Licence | Verdict |
|---|---|---|
| [recommenders-team/recommenders](https://github.com/recommenders-team/recommenders) | MIT | **Concept adopted, no dependency.** Its MIND news-recommendation work is the closest published analogue to Academious: a corpus that turns over continuously, freshness that matters, content-based cold start, impression-level feedback. LSTUR's long-/short-term user representation is the direct source of the two-horizon profile above. The package pulls TensorFlow, PyTorch, PySpark and LightGBM — untenable for a modular monolith on one VPS. |
| [RUCAIBox/RecBole](https://github.com/RUCAIBox/RecBole) | MIT | **Reference and future benchmarking only.** 94 algorithms including SASRec and BERT4Rec; actively maintained (v1.2.1, Feb 2025); requires torch. Valuable when Stage D needs a baseline to beat, not as a production dependency. |
| [benfred/implicit](https://github.com/benfred/implicit) | MIT | **Deferred to Stage C, and a good fit there.** ALS, BPR, item-item; Cython/OpenMP; CPU-first with optional GPU; small dependency surface (SciPy). Useless today — it needs a user-item matrix and every cell is empty. |
| [PreferredAI/cornac](https://github.com/PreferredAI/cornac) | Apache-2.0 | **Adopted as an offline benchmark only.** Ships a `citeulike` loader — a real paper-recommendation dataset with user-paper interactions — the one honest way to sanity-check a collaborative model before Academious has data of its own. Its loaders download over the network, so it can never appear in the test suite; it belongs in an experiment script. |
| [NVIDIA-Merlin/Transformers4Rec](https://github.com/NVIDIA-Merlin/Transformers4Rec) | Apache-2.0 | **Rejected now; re-read at Stage D.** Its session modelling and interest-drift treatment is the reference material. Its dependency path is NVTabular, RAPIDS cuDF, Triton and a Merlin container — a GPU platform adopted to serve a feed with no users. |
| [lyst/lightfm](https://github.com/lyst/lightfm) | Apache-2.0 | **Rejected on maintenance.** Last release 1.17, March 2024; open issue #709 is that it does not install on Python 3.12, and this project requires `>=3.12`. The hybrid content-plus-collaborative idea is right, and `implicit` plus our own features covers it. |
| [spotify/voyager](https://github.com/spotify/voyager) | Apache-2.0 | **Rejected: no measured need.** In-process HNSW, good software. ADR 0007 chose exact pgvector search deliberately, and semantic search measures 61.9 ms on the live corpus. A second index — with its own build, persistence and staleness — adopted before a measurement says pgvector is the bottleneck would be duplicating infrastructure on a guess. Revisit when candidate generation measures over budget. |

Nothing above contributes code. Concepts adopted come from published papers and
project documentation, which carry no licence obligation; where an idea is
traceable to a project it is named at its point of use.

## Consequences

* Seven small modules instead of one scorer: an indirection cost paid now to
  avoid a rewrite later. Justified because the sequence of models above is a
  near-certainty for this product rather than a hypothetical.
* The deterministic weights are a **stated prior fitted to nothing**. They will
  be wrong. They are centralised in one table so that being wrong is a
  measurable, changeable fact rather than a diffuse property of the code.
* Recommendation gets its own evaluation, separate from retrieval's. A profile
  is not a query, and scoring a feed with the query benchmark would measure the
  wrong thing while looking rigorous.
* Impression logging must exist before any learned ranker is attempted.
  Recorded here so its absence is a known blocker rather than a later surprise.
