"""Personalised discovery: what a reader cares about, and what deserves their
attention because of it.

The product's first layer (docs/product.md section 5), built as the multi-stage
pipeline ADR 0010 describes rather than as one scoring function:

    profile ─▶ candidates ─▶ features ─▶ ranking ─▶ rerank ─▶ feed

Each stage is a module and an interface. That is the whole design decision: a
collaborative model arrives as another `CandidateSource`, a trained ranker as
another `Ranker` over the same `FeatureVector`, and neither displaces what is
here. Building it as one blended score would have made every later model a
rewrite.

| module | question it answers |
|---|---|
| `profile` | what does this reader care about, positively and negatively |
| `candidates` | which few hundred papers might plausibly interest them |
| `sources` | in-memory generators, for tests and the benchmark |
| `pgvector` | the production semantic source - k interests, one scan |
| `features` | what is true about this paper, named and bounded |
| `ranking` | which of these deserve attention now |
| `rerank` | which *set* is worth showing, given the ones already chosen |
| `feedback` | what a reader did, and what that is allowed to mean |
| `feed` | the wiring, the hard filters, and the reason strings |

**Stateless in this phase.** A profile arrives in a request as a query string
does today. No accounts, no user tables, no personal data - so the obligations
accounts create (PROD-002, SEC-008, DEPLOY-006) stay deferred until there is
evidence the ranking is worth protecting. RETR-006 records the dependency as
*ranking needs an interest model, which needs accounts*; that holds for the
feedback loop and for nothing before it.
"""

from __future__ import annotations
