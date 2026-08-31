# Performance

Everything on this page was measured by `scripts/benchmark_phase2.py` on the
machine described below. Raw output is in
[phase-2-benchmark.json](phase-2-benchmark.json).

Anything derived rather than observed is labelled **ESTIMATE** and shows the
arithmetic, so a reader can substitute their own inputs instead of trusting a
number whose provenance is invisible.

---

## 0. Read this first

**The measurement machine is not the deployment target.** It is a shared Windows
laptop with a 15 W mobile CPU, running Docker, PostgreSQL, a browser and the
benchmark at once, with under 0.5 GB of RAM free for most of the run. Every
throughput number here is therefore a *floor*, not a specification.

| | |
|---|---|
| CPU | Intel i5-1155G7, 4 cores / 8 threads, 2.5 GHz base |
| RAM | 7.7 GB total, ~0.4 GB free during the run |
| Runtime | PyTorch 2.9.1 CPU, fp32 — **not** ONNX, **not** int8 |
| PostgreSQL | 17.11 with pgvector 0.8.6, in Docker |
| Corpus | 2,455 real papers (1,300 arXiv CS, 1,155 bioRxiv/medRxiv) |

---

## 1. The model

| Property | Measured |
|---|---|
| Base | `allenai/specter2_base` |
| Dimension | **768** |
| Maximum sequence length | 512 tokens |
| Separator | `[SEP]` (asserted against the tokenizer at load) |
| Weights on disk | 846 MB for base + both adapters, all cached formats |
| Resident after load | 356 MB |
| Cold load (weights cached) | 20.1 s |
| Licence | Apache-2.0 |

**Input length on real papers.** Median 276 tokens, p95 409, and **0.67%
truncated** at the 512-token limit. The window is comfortable: truncation is a
rounding error, not a design problem, and there is no case for a longer-context
model on these inputs.

---

## 2. Embedding throughput

150 real paper texts, encoded once per batch size, measured twice under
different machine load.

| Batch | Run A papers/s | Run B papers/s | Cores used | Peak RSS |
|---|---|---|---|---|
| 8 | 1.34 | **1.29** | 3.3 | 683 MB |
| 16 | **1.41** | 1.07 | 3.0-3.6 | 860-869 MB |
| 32 | 0.98 | 0.96 | 2.7 | 1,108-1,212 MB |

**Both runs are reported because they disagree, and the disagreement is the
finding.** Run A had the machine mostly to itself; run B shared it with a test
suite and a type check. Batch 16 looks best in A and worst in B. What is stable
across both is the *ceiling* — roughly **1.0-1.4 papers/second** — and that
batch 32 is worse than batch 8 in both.

Batch 32 losing is not noise. Peak RSS reaches 1.2 GB, and on a machine with
0.4 GB free that is memory pressure, not arithmetic. **Batch size should be
tuned to available RAM rather than raised for its own sake**; the configured
default of 16 is a reasonable middle and 8 is safer on a constrained box.

CPU utilisation peaks at ~3.5 of 4 cores, so the work parallelises but not
perfectly.

Writing to PostgreSQL is not the bottleneck anywhere: end-to-end (encode plus
insert) came out at 1.13-1.22 papers/s against 1.29-1.41 for encoding alone, so
storage costs roughly 5-10% on top of inference.

---

## 3. Storage

Measured over 2,320 stored vectors.

| | Bytes |
|---|---|
| `halfvec(768)` payload | 1,536 |
| `vector(768)` payload, for comparison | 3,072 |
| **Actual, including row and index overhead** | **2,221** |

| Projection | Value |
|---|---|
| Per 10,000 vectors | 21.2 MB |
| Per 100,000 vectors | 0.21 GB |
| Per 1,000,000 vectors | ~2.1 GB |

For context, the `paper` table itself is 28 MB for 2,455 papers (~11 KB/paper,
dominated by abstracts and JSONB), and `ix_paper_search_tsv` is 6.5 MB.

**Vectors are not the expensive part of this system.** Metadata outweighs
embeddings by roughly 5:1. Choosing `halfvec` saved ~1.5 KB per paper, which is
worth having, but nobody should expect storage to be the binding constraint.

---

## 4. Half precision: what it actually costs

The reference is float32 arithmetic over the vectors the model produced;
rounding them to float16 and back is exactly what the `halfvec` column does. The
comparison therefore isolates storage precision and nothing else. A round-trip
check confirms PostgreSQL returns what that rounding predicts.

| Corpus | Top-10 overlap (mean) | Worst query | Top-1 agreement | Max component error |
|---|---|---|---|---|
| 1,120 vectors | 1.000 | 1.00 | 1.00 | 3.05e-05 |
| 2,320 vectors | **0.992** | **0.90** | **1.00** | 3.05e-05 |

**Verdict: halfvec is the right call, and the caveat is honest.** Component
error is ~3e-05, which is what float16 gives on values in `[-1, 1]`. Across 12
queries the first result never changed. At the larger corpus one query in twelve
had a single position differ inside its top ten — two papers separated by less
than the quantisation error swapping places.

That effect is real and will grow with corpus size, because more vectors means
more near-ties. It is also not worth 2x the storage: a swap between two papers
whose scores differ in the fourth decimal is not a quality regression any user
could perceive. **What it does mean is that halfvec should be re-checked when
the corpus grows by an order of magnitude**, not assumed to stay harmless.

---

## 5. Retrieval latency

Median per query over the 12-query benchmark set, 5 repeats.

| Method | 2,320 vectors / 2,455 papers |
|---|---|
| Lexical | **12.5 ms** |
| Semantic (exact) | **61.9 ms** |
| Hybrid (RRF over both, pool 100) | **87.1 ms** |

### The bottleneck was not the vector scan

`EXPLAIN ANALYZE` on the original semantic query, at 1,120 vectors:

```
Limit                                          31.6 ms
  Sort (top-N heapsort)                        31.6 ms
    Hash Join                                  30.9 ms
      Seq Scan on paper    (2,455 rows)        17.5 ms   <-- dominant
      Hash -> Seq Scan on paper_embedding       2.5 ms   <-- the vectors
```

**The join to `paper` cost seven times what the vector arithmetic did.** The
query was selecting title, DOI, dates, OA status, topics and venue for every
candidate it scored, so PostgreSQL materialised a wide row 1,120 times in order
to return 20.

Retrieval was restructured into two phases: rank on ids and a score alone, then
fetch display columns for the surviving page. Filters still apply in phase one,
so this is a projection change that cannot alter which papers are returned or in
what order — the 42 retrieval tests pass unchanged.

| Method | Before (1,120 vectors) | After (2,320 vectors) |
|---|---|---|
| Lexical | 17.5 ms | **12.5 ms** |
| Semantic | 60.1 ms | **61.9 ms** |

Lexical is the clean comparison — same corpus both times — and it improved 29%.
Semantic held roughly constant while the number of vectors **doubled**, which is
consistent with the fix but is not a controlled measurement, and is reported as
suggestive rather than proven.

### Hybrid costs what its components cost

87 ms is the two component queries at pool depth 100 plus fusion. Fusion itself
is arithmetic over at most 200 rows and is not measurable next to the queries.

---

## 6. Approximate search: measured, and not adopted

HNSW (`halfvec_cosine_ops`, m=16, ef_construction=64) built over the same 2,320
vectors.

| | Exact | HNSW |
|---|---|---|
| Median per query | **61.9 ms** | 68.2 ms |
| Recall@10 vs exact | 1.000 by definition | 1.000 |
| Build time | — | 1.5 s |
| Index size | — | 4.76 MB |

**The index made queries slower.** At this scale the vector scan is 2.5 ms of a
62 ms query, so an index that optimises only that part cannot win, and the graph
traversal adds overhead of its own. It also costs 4.76 MB against a 5.15 MB
table — an index nearly the size of the data it indexes.

Recall of 1.000 is not evidence that HNSW is safe. At 2,320 vectors the
traversal reaches essentially everything; recall degrades at scale, and it
degrades *silently*, which is the actual risk (see
[ADR 0007](adr/0007-halfvec-and-exact-search-first.md)).

**So no migration creates it.** `academious.embeddings.index` builds it on
demand, and the decision should be revisited from measurement when either of
these becomes true:

* exact search exceeds the latency budget — **ESTIMATE**: the scan is linear in
  vectors, at ~2.5 ms per 1,120, so it reaches ~220 ms of scan time at 100,000
  vectors and ~2.2 s at 1,000,000. Somewhere between those, exact stops being
  viable;
* or the two-phase query has been optimised as far as it goes and the vector
  scan is genuinely the dominant term. It is not yet.

---

## 7. Projections

**ESTIMATES.** Measured throughput applied to the Phase 0 volume assumption of
~5,000 net new papers/day ([cost-model.md](cost-model.md)). Substituting a
different rate is linear.

| | Value | Basis |
|---|---|---|
| Best measured throughput | 1.29-1.41 papers/s | measured |
| Daily delta, 5,000 papers | **~60-65 min** | ESTIMATE |
| 6-month backfill, 900,000 papers | **~194 h (8.1 days)** | ESTIMATE |
| Backfill storage | **1.86 GB** | ESTIMATE from measured bytes/vector |
| Annual growth, 1.83M papers | **3.77 GB/year** | ESTIMATE |

### What this means for the backfill

Phase 0 recommended a 6-month initial window with daily incremental embedding,
and a temporary high-CPU machine if a deeper backfill were wanted later. The
measurement **reinforces that shape and hardens the second half of it**:

* **Daily embedding stays in place.** An hour of off-peak CPU is fine, and the
  job is interruptible, so a night that runs long costs nothing.
* **The backfill does not.** Eight days of continuous inference contending with
  PostgreSQL is not a background task; it is an outage risk. The temporary
  instance stops being a convenience and becomes the plan.
* **ONNX int8 was the untested lever. It has now been tested, and it is not
  enough.** The measured speedup is 1.64x, not the published 2.7-3.4x, and it
  changes the ranking. Section 9 has the numbers. The temporary instance stays
  the plan.

The tooling supports this without further work: `--max-papers` bounds a run,
runs are resumable and idempotent, and a second machine can be pointed at the
same database to help drain the queue because claims go through `SKIP LOCKED`.

---

## 8. Reproducing

```bash
docker compose up -d db
python -m alembic upgrade head
python -m academious.workers harvest --source biorxiv --max-records 1200
python -m academious.workers harvest --source arxiv   --max-records 1300
python scripts/benchmark_phase2.py --papers 150 --corpus 1200
```

`--backend hashing` runs everything except the model sections with no torch
installed, which is enough to reproduce the storage and latency numbers.


---

## 9. ONNX int8: measured, and not adopted

Section 7 named ONNX int8 the largest untested lever and the first thing to try
before renting hardware. It has been implemented
(`embeddings/onnx_specter2.py`, `scripts/export_onnx.py`) and measured
(`scripts/benchmark_onnx.py`). It does not pay for itself.

**Setup.** 200 papers from the corpus, mean 1,460 characters, batch 16, one
process, same machine and same texts for all three backends. Graphs traced at
opset 17, fused with ONNX Runtime's bert transformer optimiser, then dynamically
quantised with per-tensor int8 weights.

| Backend | papers/s | vs torch | Resident | Graph on disk |
|---|---|---|---|---|
| PyTorch fp32 | 2.11 | 1.00x | 907 MB | — |
| ONNX fp32 | 1.38 | 0.65x | 506 MB | 441 MB |
| **ONNX int8** | **3.45** | **1.64x** | **349 MB** | 111 MB |

**Fidelity**, against the PyTorch vectors, and **retrieval agreement**, over the
twelve benchmark queries ranked against the same 200 papers:

| Backend | Mean cosine | Min cosine | Top-10 overlap | Identical top 10 |
|---|---|---|---|---|
| ONNX fp32 | 1.000000 | 1.000000 | 1.000 | 12/12 |
| ONNX int8 | 0.991132 | 0.988325 | 0.875 | **0/12** |

### What the numbers say

**The export is correct**, which is what makes the rest of the table
trustworthy. ONNX fp32 reproduces PyTorch exactly - identical top ten on every
query - so the int8 differences are quantisation and nothing else. A test
asserts this (`tests/test_onnx_backend.py`), along with the two adapters
remaining distinct graphs, which is the failure that would otherwise be
invisible in every measurement here.

**1.64x, not 2.7-3.4x.** Fusing the graph before quantising, which is what the
published figures assume, moved it from 1.62x to 1.64x. The gap is not a missing
optimisation; it is that the published numbers come from different hardware,
sequence lengths and batch shapes than this workload has.

**int8 changes the ranking, on every query.** Mean cosine of 0.991 sounds
harmless and is not: 12.5% of the top ten changes, and not one query kept its
ordering. Only the ordering is user-visible, which is why agreement is measured
rather than inferred from cosine.

**Against the decision it was meant to inform:** 1.64x takes the 6-month
backfill from 8.1 days to about 5. It still does not fit beside PostgreSQL on
the deployment box, so the temporary high-CPU instance is still the answer -
and that instance costs about EUR 4. Adopting int8 to avoid EUR 4 would mean
re-embedding the corpus under a second `model_key` and re-running the Phase 2
benchmark to find out whether NDCG@10 survived. That is a poor trade.

### What is worth keeping

**Memory, unexpectedly.** int8 is resident in 349 MB against PyTorch's 907 MB,
and needs no torch installed at all. On an 8 GB box shared with PostgreSQL that
is a real saving, and it is the one number here that might change a decision -
not for the backfill, but for daily embedding if memory pressure ever becomes
the binding constraint rather than time.

**ONNX fp32 is a slower way to get identical vectors.** 0.65x throughput for
44% less memory. Not useful today; recorded so nobody re-derives it.

The backend and both scripts stay. Re-measuring on the real deployment hardware
is a one-line run, and section 0's standing rule - that these numbers describe a
shared Windows laptop and not a dedicated vCPU - applies to this section more
than any other, because a ratio between two engines is exactly the kind of thing
that moves with the instruction set underneath it.

### Reproducing

```bash
pip install -e ".[embed,embed-onnx,embed-onnx-export]"
python scripts/export_onnx.py
python scripts/benchmark_onnx.py --limit 200 --json data/onnx-benchmark.json
```

`--reuse-fp32` re-fuses and re-quantises without re-tracing, which is the loop
worth having while trying quantisation settings.
