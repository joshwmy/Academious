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

It then prints judgment coverage for each scored query and audits the top 10 —
the depth the headline metrics use — for papers that were never labelled:

```
Judgment coverage of the scored queries (top 10 audited)
  query       judged  pooled   unjudged in top ranks
  --------------------------------------------------
  bio-01          43      44   hybrid=0  lexical=0  semantic=0
  cs-02           25      29   hybrid=3  lexical=3  semantic=3  <-- INCOMPLETE

WARNING: cs-02 carry unjudged papers inside the ranks the metrics score.
```

This matters because an unjudged id scores zero, which is the correct
conservative assumption but is indistinguishable, in the metric alone, from a
paper a human looked at and rejected. A query whose best hits are merely
unlabelled reports a confidently wrong number, and it does not distribute that
error evenly between methods — the method that ranked the unlabelled papers
highest is punished hardest. The harness does not refuse to score such a query,
because a partly judged query is still informative; it refuses to let it be read
without the caveat.

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

## 8. Measured results

**128 judgments, covering 4 of 12 queries.** Two biomedical (`bio-01` 43/44,
`bio-02` 32/37) and two computing (`cs-02` 25/29, `cs-05` 28/28). The computing
pair was chosen deliberately as a control: both are queries where lexical search
should do well, so they are the strongest available test of the semantic result.

### Judgment coverage comes first

| query | judged / pooled | relevant (grade >= 2) | unjudged in the top 10 |
|---|---|---|---|
| `bio-01` | 43 / 44 | 24 | none |
| `bio-02` | 32 / 37 | 17 | lexical 1 |
| `cs-02` | 25 / 29 | 8 | **3 in every method** |
| `cs-05` | 28 / 28 | 5 | none |

The harness now prints this table and warns when a scored query has unjudged
papers inside the ranks the metrics score, because such a query reports a number
that is confidently wrong. `cs-02` is the case in point: its four unlabelled
pooled papers are `HC-RAG`, `RAGSieve`, `IterCOMP` and `HybridRAG-BN`, and they
sit at lexical ranks 1, 2 and 6. Scored as they stand, they count as *not
relevant*, and lexical records P@10 = 0.000 on the one query in the set that was
designed for it to win.

The sensitivity of `cs-02` to those four rows is total:

| assumed grade for the 4 unjudged | lexical MRR | semantic MRR | hybrid MRR |
|---|---|---|---|
| 0 (what is reported today) | 0.083 | 0.333 | 0.100 |
| 2 or 3 | **1.000** | **1.000** | **1.000** |

`cs-02` is therefore **not a usable measurement yet**, and no conclusion below
rests on it.

### Aggregate, all four judged queries

Reported for completeness; `cs-02` drags every method down and lexical hardest.

| method | P@5 | P@10 | R@10 | MRR | NDCG@10 |
|---|---|---|---|---|---|
| lexical | 0.350 | 0.325 | 0.276 | 0.604 | 0.365 |
| **semantic** | **0.450** | **0.425** | **0.342** | **0.708** | **0.422** |
| hybrid | 0.300 | 0.375 | 0.322 | 0.483 | 0.407 |

### Aggregate over the three queries whose top ranks are judged

| method | P@5 | P@10 | R@10 | MRR | NDCG@10 |
|---|---|---|---|---|---|
| lexical | 0.467 | 0.433 | 0.367 | 0.778 | 0.480 |
| **semantic** | **0.533** | **0.533** | **0.415** | **0.833** | **0.525** |
| hybrid | 0.400 | 0.467 | 0.387 | 0.611 | 0.512 |

Per query, with the winner by NDCG@10 in bold:

| query | lexical | semantic | hybrid |
|---|---|---|---|
| `bio-01` | 0.327 | **0.531** | 0.399 |
| `bio-02` | 0.360 | 0.457 | **0.496** |
| `cs-05` | **0.754** | 0.587 | 0.642 |
| `cs-02` (invalid) | 0.019 | 0.115 | 0.090 |

Three things stand out.

**Semantic still leads on aggregate, but the win is domain-shaped.** Semantic
takes every aggregate metric, as it did over two queries. It does not win every
query: on `cs-05` (*graph neural networks*, an exact architecture name) lexical
wins decisively, NDCG@10 0.754 against 0.587, which is exactly what that query
was put in the set to test. The claim the evidence supports is *semantic wins
where the query and the literature use different words*; the claim it does not
support is *semantic wins everywhere*.

**Both methods find the same first paper more often than the aggregate
suggests.** Rank of the first relevant hit: `bio-01` lexical 1 / semantic 1,
`bio-02` 3 / 2, `cs-05` 1 / 1. Semantic's MRR advantage over these three queries
comes from `bio-02` alone. The margin between them is thinner than the two-query
result implied.

**Hybrid is still the weakest at MRR and the mechanism is unchanged.** It never
wins MRR on any query and loses it outright on `bio-01` (0.500 against 1.000 for
both components). It does win one query on NDCG@10 (`bio-02`, 0.496), which is
the one query where the components agree most.

### Why fusion behaves this way

The components barely overlap, and RRF rewards consensus over conviction:

| query | overlap of the two top-20s | hybrid vs best component (NDCG@10) |
|---|---|---|
| `bio-01` | 2 of 20 | 0.399 vs 0.531 |
| `bio-02` | 5 of 20 | **0.496** vs 0.457 |
| `cs-05` | 7 of 20 | 0.642 vs 0.754 |

`bio-01` shows the failure directly. Hybrid's rank 1 is a *marginal* paper that
lexical ranked 16th and semantic 3rd: `1/76 + 1/63 = 0.0290`. Semantic's own
rank-1 paper, which lexical never returned, scores `1/61 = 0.0164` and loses.
Two mediocre placements outrank one confident one. Meanwhile the genuinely good
papers fusion *does* surface arrive late — `MatchMiner-AI` (grade 3) at rank 6
from lexical 79 / semantic 5, `OTRec` (grade 3) at rank 7 from lexical 97 /
semantic 4 — so fusion is recovering them from deep in the semantic pool only to
place them behind a consensus pick.

Where the components agree, fusion helps: on `bio-02` (5 of 20 overlap) hybrid
beats both. Where they disagree, it averages a right answer with a wrong one.

The two-query fusion sweep recorded below is retained as a diagnostic. It was
run over `bio-01` and `bio-02` only and has **not** been re-run or re-fitted:

| variant (2 queries: bio-01, bio-02) | P@5 | P@10 | MRR | NDCG@10 |
|---|---|---|---|---|
| lexical only | 0.400 | 0.500 | 0.667 | 0.344 |
| semantic only | 0.600 | 0.650 | **0.750** | 0.494 |
| RRF k=10 | 0.600 | 0.650 | 0.417 | 0.468 |
| RRF k=20 | 0.700 | 0.600 | 0.417 | 0.471 |
| RRF k=60 (default) | 0.400 | 0.550 | 0.417 | 0.448 |
| normalised weighted | 0.700 | 0.500 | 0.417 | 0.389 |
| RRF k=60, semantic x2 | 0.600 | 0.600 | 0.500 | 0.498 |
| RRF k=60, semantic x3 | 0.700 | 0.650 | 0.500 | 0.491 |

**Nothing has been retuned on the basis of any of this.** No default was
changed, no `k` was moved, no weight was introduced. Four queries — one of them
not yet valid — is a set to measure against, not to fit to. The open question is
unchanged and now sharper: *does fusion earn its place at all?* The queries that
will answer it are the ones designed to be hard for lexical search, because that
is where fusion either rescues a weak component or is dragged down by it.

---

## 9. What this cannot tell you

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
