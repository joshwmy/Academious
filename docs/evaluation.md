# Evaluation

How retrieval quality is measured, and what the numbers are allowed to claim.

---

## 1. The rule

**Nothing fabricates ground truth.**

There is no user feedback yet, so relevance has to come from a person reading
papers and deciding. Until that happens, the harness reports rankings and *no*
quality metrics — not zeros, and not a number derived from treating "retrieved"
as "relevant", which would be measuring the system against itself.

Running the benchmark is therefore useful on day one, and the metrics appear the
moment there is something to compute them from.

---

## 2. The query set

Twelve research-interest descriptions, six per launch domain, in
`academious/eval/queries.py`. Each carries an `intent` recording what it is meant
to expose, so a surprising result can be checked against what the query was for.

**Biomedical and life science**

| id | Query | What it probes |
|---|---|---|
| `bio-01` | cancer genomics machine learning | Cross-disciplinary vocabulary |
| `bio-02` | transcriptomic biomarkers in breast cancer | Precision on a narrow topic |
| `bio-03` | Alzheimer's disease genetics | Ranking when thousands match |
| `bio-04` | deep learning medical imaging | Method-led query, clinical corpus |
| `bio-05` | public health diabetes risk prediction | Concepts that rarely co-occur |
| `bio-06` | computational drug discovery | Many surface terms for one field |

**Computer science and AI**

| id | Query | What it probes |
|---|---|---|
| `cs-01` | large language model code generation | Whether recent preprints surface |
| `cs-02` | retrieval augmented generation | Established term of art — a control |
| `cs-03` | reinforcement learning robotics | Intersection of two broad fields |
| `cs-04` | efficient transformer inference | Weak lexical, strong semantic signal |
| `cs-05` | graph neural networks | Exact architecture name |
| `cs-06` | AI safety evaluation | Unsettled vocabulary — hardest case |

The set is deliberately small. Every query has to be judged by a human, and
twelve queries at pool depth twenty is already several hundred judgments. A
larger set that nobody labels measures nothing.

`cs-02` and `cs-05` are controls where lexical search should do well. If the
semantic path loses badly on those, something is wrong with it rather than
interesting about the corpus.

---

## 3. Pooling

For each query, all three methods run and their results are **unioned** into one
set of papers to judge. Judging each ranking separately would penalise a method
for surfacing a good paper the others missed — its unique find would go unjudged
and score zero.

Each pooled row records `retrieved_by`, so pool bias is visible in the file
rather than hidden in the averages.

```bash
python -m academious.workers evaluate --depth 20
python -m academious.workers evaluate --domain biomedical --show-hits 10
```

---

## 4. The judgment file

`data/eval/judgments.jsonl`, one JSON object per `(query, paper)`:

```json
{"canonical_doi": "10.1101/2026.08.20.000000", "grade": null, "judge": null,
 "judged_at": null, "note": "", "paper_id": "0f5e0000-0000-0000-0000-000000000000",
 "query_id": "bio-01", "retrieved_by": ["hybrid", "lexical"],
 "title": "Deep learning for pan-cancer mutation calling"}
```

Line-oriented so a diff shows exactly which judgments changed. Sorted by
`(query_id, title, paper_id)` so regenerating the pool does not reshuffle the
file. Carrying `title` and `canonical_doi` so a judge can label without a second
window open.

### The scale

| Grade | Meaning |
|---|---|
| `0` | not relevant |
| `1` | marginal — touches the topic but is not what was asked for |
| `2` | relevant |
| `3` | highly relevant — a top result any expert would name |

Graded rather than binary because NDCG needs the grades, and because the
difference between *on topic* and *exactly what I meant* is the distinction
personalised discovery lives or dies on. Binary metrics threshold at `2`.

`null` means **not yet judged** and is distinct from `0`, which means *judged,
not relevant*. Metrics are computed only over judged rows.

### Judgments are never overwritten

Judging is the expensive input here, so `judgments.merge` guarantees:

* an existing grade survives pool regeneration;
* a paper that dropped out of the pool **keeps** its judgment — a judgment is a
  fact about a `(query, paper)` pair and does not stop being true because a
  ranking changed, and keeping it makes a later re-pool cheaper;
* only provenance and display fields are refreshed.

A run that silently discarded yesterday's labels because the ranking shifted
would make the whole exercise unrepeatable.

---

## 5. Metrics

`academious/eval/metrics.py` — pure functions over ranked id lists and graded
relevance. No database, no configuration, so the arithmetic is tested against
worked examples rather than against whatever the system happened to return.

| Metric | Definition |
|---|---|
| **P@5**, **P@10** | Fraction of the top *k* graded ≥ 2 |
| **Recall@10** | Fraction of known-relevant papers found in the top 10 |
| **MRR** | `1 / rank` of the first relevant result |
| **NDCG@10** | Exponential-gain DCG over the ideal ordering |

Three deliberate choices:

* **Precision divides by `k`, not by results returned.** A method that returned
  three results when ten were asked for has not achieved perfect precision by
  being quiet.
* **Recall is within the judged pool.** A relevant paper that no method
  retrieved was never judged and is invisible here. It is comparable between
  methods evaluated over the same pool, and it is *not* an estimate of true
  corpus recall. Reporting it as one would be the single easiest way to lie with
  this harness.
* **Unjudged results score zero gain in NDCG.** The standard pooled-evaluation
  assumption. It is conservative — it can only understate a method, never
  flatter one.

---

## 6. Reading a report

```
==============================================================================
Retrieval benchmark: 12 queries, pool depth 20
Judgments: 0 of 340 pooled papers judged
==============================================================================

[bio-01] cancer genomics machine learning
    intent: cross-disciplinary: method vocabulary from computing, subject ...
  lexical    20 hits    18.4 ms
       1.  0.4210  Deep learning models for pan-cancer mutation calling
  ...
```

With no judgments the report ends by saying so and pointing at the pool file.
With judgments it ends with a per-method table, `queries_scored` making clear how
much of the set the numbers rest on.

---

## 7. Ablations the harness is built to answer

The registry and the backend flags exist so that design choices can be measured
instead of argued about. Each of these is a full corpus re-embed under a second
`model_key`, then the same benchmark:

| Question | How |
|---|---|
| Do abstracts help? | `specter2-proximity@v1` vs `specter2-title-only@v1` |
| Does the query adapter help? | `Specter2Backend(use_query_adapter=False)` |
| Is hybrid better than either half? | Already reported per method every run |
| RRF or weighted fusion? | `hybrid.fuse(method=FusionMethod.WEIGHTED)` |
| Does halfvec cost quality? | `scripts/benchmark_phase2.py`, section 6 |

Because both vector sets live under different `model_key`s at the same time, an
ablation is a second run against the same database rather than a rebuild.

### Measured: do abstracts help?

`scripts/compare_input_strategies.py` embedded all 2,455 papers twice and
compared the top 10 for every benchmark query. Raw output in
[phase-2-input-strategy.json](phase-2-input-strategy.json).

| | |
|---|---|
| Mean top-10 overlap | **0.417** |
| Worst query | **0.10** (`cs-01`, `cs-04`) |
| Queries agreeing on the top result | **7 of 12** |

**The two strategies are close to different systems.** Fewer than half the
results are shared, and five of twelve queries disagree about the single best
paper. This is not a refinement, it is a different ranking.

Two consequences follow immediately, and neither depends on having labels:

* **The title-only fallback is a material degradation, not an equivalent.** A
  paper embedded from its title alone sits somewhere quite different in vector
  space from where it would sit with its abstract. That makes abstract coverage
  a retrieval-quality issue, not just a metadata-completeness one, and it is why
  `input_strategy` is recorded per row and surfaced in `/metrics/embeddings`.
* **The ablation must be judged, not assumed.** With 41.7% overlap, picking a
  strategy on intuition means picking blind on more than half the results.

What this does **not** say is which ranking is better. That needs the pool
judged.

---

## 8. First measured results

**75 judgments, covering 2 of 12 queries** (`bio-01` 43/44, `bio-02` 32/37).
Both are biomedical; no CS query is judged yet. Everything below rests on two
queries and is directional, not conclusive.

| method | P@5 | P@10 | R@10 | MRR | NDCG@10 |
|---|---|---|---|---|---|
| lexical | 0.400 | 0.500 | 0.251 | 0.667 | 0.344 |
| **semantic** | **0.600** | **0.650** | **0.322** | **0.750** | **0.494** |
| hybrid | 0.400 | 0.550 | 0.281 | 0.417 | 0.448 |

Two things stand out.

**Semantic beats lexical on every metric.** That is the first evidence that
SPECTER2 earns its CPU cost rather than merely returning plausible-looking
papers. It is two queries, so it is evidence, not proof.

**Hybrid is worse than either component at MRR, and the mechanism is
understood.** On `bio-01` both lexical and semantic placed a relevant paper at
rank 1 (MRR 1.0 each); fusion demoted them and led with a *marginal* paper,
taking P@5 from 0.80 to 0.20.

This is reciprocal rank fusion rewarding **consensus over conviction**. At
`k = 60`, rank 1 in one method contributes `1/61 = 0.0164`, while rank 4 in
*both* contributes `2/64 = 0.0313` — so two mediocre placements outrank one
perfect one. That is RRF working as designed, and the design is a poor fit when
one method is decisively right and the other has not heard of the paper.

A sensitivity sweep confirms the effect is not a `k` artefact:

| variant | P@5 | P@10 | MRR | NDCG@10 |
|---|---|---|---|---|
| lexical only | 0.400 | 0.500 | 0.667 | 0.344 |
| semantic only | 0.600 | 0.650 | **0.750** | 0.494 |
| RRF k=10 | 0.600 | 0.650 | 0.417 | 0.468 |
| RRF k=20 | 0.700 | 0.600 | 0.417 | 0.471 |
| RRF k=60 (default) | 0.400 | 0.550 | 0.417 | 0.448 |
| normalised weighted | 0.700 | 0.500 | 0.417 | 0.389 |
| RRF k=60, semantic x2 | 0.600 | 0.600 | 0.500 | 0.498 |
| RRF k=60, semantic x3 | 0.700 | 0.650 | 0.500 | 0.491 |

Every fusion variant lands at MRR <= 0.50 against semantic-only 0.750, and the
best hybrid NDCG (0.498) only ties semantic (0.494).

**Nothing has been retuned on the basis of this.** Choosing `k` or a weighting
to maximise a score over two queries is fitting noise, and the sweep is recorded
as a diagnostic precisely so that temptation is visible rather than acted on.
What it does justify is a question for the remaining judgments: *does fusion
earn its place at all, or is semantic-alone the right default?* `cs-02` and
`cs-05` are the queries most likely to answer it, because they are where lexical
should be strongest.

---

## 8. What this cannot tell you

Stated plainly, because a benchmark that overstates its reach is worse than none:

* **Twelve queries is small.** Differences of a few points are noise.
* **One judge is one opinion.** No inter-annotator agreement is measured, so
  systematic bias in the labelling is invisible.
* **Pooled recall is not corpus recall**, as above.
* **The corpus is a sample.** Retrieval behaviour at 2,000 papers is not
  behaviour at 2,000,000; a method that looks good on a small corpus may simply
  be exploiting the absence of near-duplicates.
* **This measures retrieval, not the product.** Whether a person finds the
  result *useful* is a different question, and the answer to it comes from real
  users, not from this harness.
