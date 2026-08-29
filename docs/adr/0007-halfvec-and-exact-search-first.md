# ADR 0007: halfvec storage, and exact search before any ANN index

**Status:** Accepted (Phase 2)

## Context

768-dimensional vectors have to be stored and searched. pgvector offers `vector`
(float32, 3072 bytes per row) and `halfvec` (float16, 1536 bytes), and offers
HNSW and IVFFlat approximate indexes over either.

The reflexive build is `vector` plus an HNSW index on day one. Both halves of
that deserve scrutiny, because both trade something away and neither trade had
been measured.

## Decision

Two decisions, taken together because they interact.

**1. Store as `halfvec(768)`, with vectors L2-normalised before insertion.**

**2. Create no ANN index. Search exactly, and measure what that costs.** The
HNSW index is buildable on demand through `academious.embeddings.index`, but no
migration creates it.

## Consequences

### halfvec

* Storage halves: 1536 bytes instead of 3072 per vector, applying to the table,
  any index over it, the WAL, and every page read.
* Normalising first is what makes the precision loss safe to reason about. Every
  component then lies in `[-1, 1]`, where float16 carries about three decimal
  digits, so quantisation error is bounded uniformly rather than depending on
  the magnitude of a vector.
* Normalising also makes cosine distance and inner product rank identically, so
  the operator choice is a matter of clarity rather than correctness.
* The cost is measured, not assumed: `scripts/benchmark_phase2.py` compares
  top-k rankings from float32 arithmetic against the same vectors rounded to
  float16, and separately checks that what PostgreSQL returns matches that
  rounding. Numbers are in [performance.md](../performance.md).
* The width is fixed in the column type. A model with a different dimension is a
  schema change and should be visible as one.

### Exact search first

* Exact search is **correct by construction**. It reads every vector for the
  `model_key`, so recall is 1.0 and a filter can never cost a result.
* HNSW would give up both properties. It returns approximate neighbours, and —
  more insidiously — a selective filter applied alongside the index can silently
  drop relevant papers because the graph traversal never visited them. A
  date-filtered search returning fewer good results than an unfiltered one, with
  no error anywhere, is exactly the kind of failure that survives to production.
* Shipping the index by default would have made the Phase 2 measurement
  impossible: there would be no baseline to compare it against.
* The cost is a sequential scan proportional to corpus size. This is acceptable
  at Phase 2 scale and will not be acceptable indefinitely;
  [performance.md](../performance.md) records the measured latency, the measured
  HNSW recall against exact search, and the point at which the trade starts to
  pay.
* When the index does arrive it gets its own migration, so its introduction is a
  dated, reviewable event rather than an implicit default.
* The semantic query is written as `ORDER BY embedding <=> :vector` — distance
  ascending rather than similarity descending — even though the two are
  equivalent, because only the former is a shape HNSW can serve. Adding the
  index later requires no change to the query.
