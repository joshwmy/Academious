# Phase 2 report: scientific embedding and retrieval foundation

**Status:** complete, pending review of retrieval quality.

Phase 2 was asked to answer one question before any interface gets built: *can
this system surface scientifically relevant papers from its corpus?* This report
says what was built, what was measured, what the measurements contradict, and —
importantly — what is still unknown.

No frontend, no authentication, no LLM summarisation and no per-user
recommendation tables were built. None were started.

---

## 1. What exists now

```
paper ─┬─▶ SPECTER2 (proximity adapter) ─▶ halfvec(768) in pgvector ─┐
       │                                                             ├─▶ hybrid
       └─▶ tsvector (title A, keywords B, abstract C) ───────────────┘    (RRF)
                                                                           │
research interest ─▶ SPECTER2 (ad-hoc query adapter) ──────────────────────┘
```

| Area | Module | What it does |
|---|---|---|
| Embedding input | `embeddings/text.py` | Deterministic, versioned text construction |
| Backends | `embeddings/specter2.py`, `hashing.py` | Real model; deterministic torch-free stand-in |
| Persistence | `embeddings/service.py` | Idempotent, resumable, crash-isolated |
| Jobs | `embeddings/jobs.py`, `workers/embed.py` | SKIP LOCKED queue, three-transaction worker |
| ANN | `embeddings/index.py` | HNSW, buildable on demand, not shipped |
| Lexical | `retrieval/lexical.py` | Weighted tsvector, strict then relaxed |
| Semantic | `retrieval/semantic.py` | Exact pgvector cosine |
| Hybrid | `retrieval/hybrid.py` | RRF and normalised weighted sum |
| Filters | `retrieval/filters.py` | Applied in SQL before ranking |
| Evaluation | `eval/` | Pooled benchmark, judgments, IR metrics |
| Labelling | `workers/label.py` | Interactive grading, saves after every answer |

Schema: migration `0002` adds `paper_embedding` (`halfvec(768)`, primary key
`(paper_id, model_key)`) and `paper.search_tsv` as a stored generated column.

Detail lives in [embeddings.md](embeddings.md), [retrieval.md](retrieval.md),
[evaluation.md](evaluation.md) and [performance.md](performance.md); decisions
in [ADR 0006](adr/0006-specter2-asymmetric-adapters.md) and
[ADR 0007](adr/0007-halfvec-and-exact-search-first.md).

---

## 2. Decisions that were not obvious

### SPECTER2 is two models, not one

Phase 0 chose "SPECTER2". Implementing it revealed the choice was
underspecified: SPECTER2 is a shared encoder plus task adapters, and the
proximity adapter (paper → related papers) is not the ad-hoc query adapter
(short query → papers). Academious queries are research-interest descriptions,
so **documents use proximity and queries use ad-hoc query**, over one shared set
of base weights. Encoding a query with the document adapter would have been a
silent mistake producing plausible-looking results.

### The lexical baseline had to be defended from itself

`websearch_to_tsquery` requires every term. *"public health diabetes risk
prediction"* as a conjunction matches almost nothing — so the naive baseline
would have returned zero results on exactly the multi-concept queries semantic
search is supposed to win, and the comparison would have been rigged in favour
of the thing being evaluated.

Lexical search therefore runs strict first and relaxes conjunctions to
disjunctions only when strict finds nothing, skipping the relaxation when a
negation would be inverted by it. `result.detail["query_mode"]` records which
pass answered.

### Keywords could not be indexed without a helper function

PostgreSQL marks `array_to_string()` STABLE, so a generated column cannot call
it; `keywords::text` and `to_jsonb(keywords)::text` fail for the same reason.
The fix is a one-line IMMUTABLE SQL wrapper, sound because `text[]` with a
constant separator genuinely is immutable. Without it, keywords would have been
silently absent from the lexical index. Topic labels needed no such workaround —
`jsonb_path_query_array(...)::text` is already immutable.

### Retracted papers are excluded by default

A retracted paper is not low quality; the literature has withdrawn the claim.
Ranking it beside standing work presents a repudiated result as current.
Corrections and expressions of concern are different — those papers stand with a
caveat, so they are returned and their status travels with every hit.

### No ANN index ships

See §4. This was a measurement, not a preference.

---

## 3. What was measured

Full numbers in [performance.md](performance.md); raw output in
[phase-2-benchmark.json](phase-2-benchmark.json). Measured on a shared 4-core
i5-1155G7 laptop with ~0.4 GB RAM free, PyTorch fp32 — **not** the deployment
target, so throughput figures are a floor.

| | Measured |
|---|---|
| Embedding dimension | 768, confirmed |
| Input length | median 276 tokens, p95 409, **0.67% truncated** |
| Throughput | **1.0-1.4 papers/s** (batch 8-16; batch 32 is worse) |
| Model resident | 356 MB after load; 683 MB-1.2 GB peak during inference |
| Storage | **2,221 bytes/vector** including all overhead → 21.2 MB per 10k |
| Lexical latency | 12.5 ms |
| Semantic latency (exact) | 61.9 ms at 2,320 vectors |
| Hybrid latency | 87.1 ms |

---

## 4. Findings that changed the design

### The bottleneck was the join, not the vectors

`EXPLAIN ANALYZE` on the original semantic query: sequential scan on `paper`
17.5 ms, sequential scan on `paper_embedding` 2.5 ms. **The metadata join cost
seven times the vector arithmetic.** The query was materialising a wide `paper`
row for every candidate it scored in order to return twenty.

Retrieval was restructured into two phases — rank on ids and score, then hydrate
the surviving page. Filters still apply in phase one, so results and ordering
are unchanged and all 42 retrieval tests passed without modification. Lexical
latency fell 17.5 → 12.5 ms on an identical corpus; semantic held constant while
the vector count doubled.

This matters beyond the 5 ms: **the obvious optimisation was the wrong one.**
Reaching for an ANN index first would have optimised 2.5 ms of a 62 ms query and
declared victory.

### HNSW made queries slower

| | Exact | HNSW |
|---|---|---|
| Median per query | **61.9 ms** | 68.2 ms |
| Recall@10 vs exact | 1.000 | 1.000 |
| Index size | — | 4.76 MB (table is 5.15 MB) |

At this scale an index over the cheap part of the query cannot win, and adds
traversal overhead of its own. Recall of 1.000 is *not* evidence HNSW is safe —
at 2,320 vectors the traversal reaches nearly everything. The risk it carries at
scale is that recall degrades **silently**, and that a filter applied alongside
the index can drop relevant papers the traversal never visited.

So exact search ships, no migration creates an index, and
`academious.embeddings.index` builds one on demand when measurement justifies
it. **ESTIMATE**: the scan is linear, so ~220 ms of scan time at 100k vectors
and ~2.2 s at 1M — the decision point sits between those.

### halfvec costs almost nothing, and the caveat is real

Comparing float32 arithmetic against the same vectors rounded to float16:

| Corpus | Mean top-10 overlap | Worst query | Top-1 agreement |
|---|---|---|---|
| 1,120 vectors | 1.000 | 1.00 | 1.00 |
| 2,320 vectors | 0.992 | 0.90 | 1.00 |

Half the storage, no change to any first result. At the larger corpus one query
in twelve had a single position move inside its top ten — two papers separated
by less than the quantisation error swapping places. **That effect grows with
corpus size and should be re-checked at an order of magnitude more data**, not
assumed to stay harmless.

---

## 5. What contradicts earlier assumptions

### Embedding throughput was overestimated by roughly an order of magnitude

[cost-model.md §8](cost-model.md) estimated 20-35 papers/second and a ~3.5
minute daily delta. Measured: **1.29-1.41 papers/second**.

| | Phase 0 estimate | Phase 2 measurement |
|---|---|---|
| Runtime | ONNX Runtime, int8, batch 32 | PyTorch, fp32, batch 8-16 |
| Hardware | 4 dedicated vCPU | shared 4-core laptop under load |
| Throughput | 20-35 papers/s | **1.29-1.41 papers/s** |
| Daily delta (5,000) | ~3.5 min | **~60-65 min** |
| 6-month backfill (900,000) | ~10 h | **~194 h (8.1 days)** |

Two caveats are owed, and neither closes the gap:

* **ONNX int8 was assumed and never implemented.** Phase 2 runs stock PyTorch
  fp32. The published 2.7-3.4x int8 speedup is the largest available lever and
  remains untested.
* **The measurement hardware is not the target.** A shared 15 W laptop chip is
  not a dedicated vCPU.

Even granting both, the fp32 baseline Phase 0 assumed (8-12 papers/s at 256
tokens on 4 vCPU) is itself 6-8x above what was measured, on inputs of the
expected length. **The honest reading is that the baseline was too generous and
every figure derived from it is an upper bound.** `cost-model.md` now carries a
§8a recording this.

What survives is the *shape* of the Phase 0 recommendation, now with sharper
edges: daily embedding stays on the box (an hour of off-peak CPU, and the job is
interruptible); the backfill does not, and at 8 days a temporary high-CPU
instance stops being a convenience and becomes the plan.

### Storage was cheaper than feared, and is not the constraint

2,221 bytes per vector: **1.86 GB** for a 6-month backfill, **3.77 GB/year**
after. For comparison the `paper` table is ~11 KB/paper. **Metadata outweighs
embeddings roughly 5:1** — vectors are not what will make this system expensive.

### Abstracts change retrieval far more than expected

The corpus was embedded twice — `title[SEP]abstract` and title alone — and the
top 10 compared for every benchmark query
([phase-2-input-strategy.json](phase-2-input-strategy.json)):

| | |
|---|---|
| Mean top-10 overlap | **0.417** |
| Worst query | 0.10 (`cs-01`, `cs-04`) |
| Queries agreeing on the top result | 7 of 12 |

Fewer than half the results are shared. **These are not two settings of one
system; they are close to two different systems.** The practical consequence is
that abstract coverage is a *retrieval-quality* problem rather than a
metadata-completeness one: a paper embedded from its title alone lands somewhere
materially different in vector space. Phase 2 records `input_strategy` per row
and exposes the split on `/metrics/embeddings` precisely so this stays visible.

The comparison deliberately stops short of saying which ranking is better. That
requires judgments.

### Batch size does not monotonically help

Batch 32 was slower than batch 8 in both runs, at 1.2 GB peak RSS on a machine
with 0.4 GB free. On constrained hardware, batch size is a memory decision, not
a throughput knob.

---

## 6. Testing

| | |
|---|---|
| Tests | 255 passing |
| Coverage | 83% (`--cov=academious`) |
| Lint | `ruff check` clean |
| Types | `mypy` clean, 78 source files, `strict` |
| Migrations | `alembic upgrade head` clean from empty |

No test touches the network, and **no test downloads the model.**
`HashingBackend` is a deterministic hashed bag-of-words that produces real
vectors with meaningful similarity structure, so retrieval and ranking are
exercised end to end without torch. It is not a semantic model and nothing
asserts semantic behaviour against it.

Database tests need PostgreSQL with `pg_trgm` and `pgvector`; they skip rather
than fail when none is configured.

Coverage gaps are concentrated in CLI entry points (`workers/__main__.py`,
`harvest.py`, `search.py`, `evaluate.py`), which are thin argument-parsing over
tested code.

**Phase 1 fixes made along the way:** `mypy` reported 7 pre-existing errors in
Phase 1 modules. They are fixed — a type gate that is red is not a gate. The
changes are annotations and one `cast`; no behaviour changed.

---

## 7. Acceptance

`scripts/demo_phase2.py` walks all twelve criteria against a real PostgreSQL,
with real SPECTER2 inference. All 33 checks pass.

| # | Criterion | Result |
|---|---|---|
| 1 | Unembedded paper is detected | PASS |
| 2 | SPECTER2 embedding generated | PASS |
| 3 | Vector persisted | PASS |
| 4 | Re-running does not duplicate work | PASS — zero inference on pass two |
| 5 | Missing-abstract paper still embedded | PASS — `title_only` recorded |
| 6 | Semantic query retrieves relevant papers | PASS |
| 7 | Lexical search retrieves results | PASS — including the relaxed pass |
| 8 | Hybrid retrieval works | PASS — with per-method attribution |
| 9 | Retracted papers handled | PASS — excluded by default, retrievable on request |
| 10 | Filters work | PASS — date, preprint, OA, field |
| 11 | Evaluation tooling produces comparisons | PASS — and reports no metrics |
| 12 | Worker interruption is safe | PASS — reaped, retried, no duplicate work |

---

## 8. Limitations, stated plainly

* **No relevance judgments exist yet, so no quality metrics are reported.** The
  harness runs, pools candidates and produces the file to judge. It reports
  rankings and explicitly *no* P@k, MRR or NDCG, because computing them from
  unjudged data would mean scoring the system against its own output. This is
  the single biggest open item, and it needs human time rather than more code.
* **Twelve queries is a small benchmark.** Once judged, differences of a few
  points will be noise.
* **One judge is one opinion.** No inter-annotator agreement is measured.
* **Pooled recall is not corpus recall.** A relevant paper no method retrieved
  was never judged and is invisible.
* **The corpus is 2,455 preprints from two sources**, all with abstracts. The
  title-only path is unit-tested but has not been exercised on real sparse
  metadata at volume, because bioRxiv and arXiv both supply abstracts. OpenAlex
  would provide that data and needs an API key.
* **Latency was measured at ~2,300 vectors.** Behaviour at 100k or 1M is
  extrapolation.
* **ONNX int8 is unimplemented** and is the largest known performance lever.
* **No re-ranking, no learning-to-rank, no personalisation.** Deliberately.

---

## 9. Recommended next steps

Before Phase 3 builds anything on top of this:

1. **Judge the pool.** It already exists: `data/eval/judgments.jsonl`, **382
   papers** across 12 queries, produced by a real run against the full corpus.
   `python -m academious.workers label --judge <name>` walks them one at a time
   and saves after every answer. Until this happens, no claim about retrieval
   quality is supportable.
2. **Decide the input strategy from the comparison** rather than from intuition
   — at 41.7% overlap, guessing means guessing on most of the results.
3. **Try ONNX int8** before provisioning hardware for a backfill.
4. **Get an OpenAlex API key** and ingest sparse-metadata records, so the
   title-only path is exercised on real data.

Only after (1) should a frontend be designed against these rankings.
