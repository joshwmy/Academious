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

**208 judgments, covering 6 of 12 queries**, three per domain. Every one of the
six is judged deeply enough to score: the coverage audit reports **zero**
unjudged papers inside any method's top 10, so the harness aggregate and the
"clean" aggregate are the same number.

| query | judged / pooled | g0 | g1 | g2 | g3 | relevant (>= 2) | unjudged in any top 10 |
|---|---|---|---|---|---|---|---|
| `bio-01` | 43 / 44 | 13 | 6 | 11 | 13 | 24 | none |
| `bio-02` | 37 / 37 | 11 | 9 | 7 | 10 | 17 | none |
| `bio-05` | 43 / 43 | 26 | 10 | 5 | 2 | 7 | none |
| `cs-02` | 29 / 29 | 15 | 4 | 9 | 1 | 10 | none |
| `cs-05` | 28 / 28 | 19 | 4 | 3 | 2 | 5 | none |
| `cs-06` | 28 / 28 | 11 | 5 | 5 | 7 | 12 | none |

`bio-01`'s single unjudged pooled paper sits outside every top 10 and cannot
move a metric reported here.

### Aggregate over all six

| method | P@5 | P@10 | R@10 | MRR | NDCG@10 |
|---|---|---|---|---|---|
| lexical | 0.300 | 0.333 | 0.304 | 0.667 | 0.366 |
| **semantic** | **0.533** | **0.417** | 0.378 | **0.806** | **0.490** |
| hybrid | 0.400 | **0.417** | **0.382** | 0.639 | 0.472 |

Semantic takes P@5, MRR and NDCG@10. Hybrid takes recall and ties P@10. Lexical
leads nothing on aggregate.

### Per query

| query | lexical | semantic | hybrid | winner | first relevant (lex/sem/hyb) | top-20 overlap |
|---|---|---|---|---|---|---|
| `bio-01` | 0.327 | **0.531** | 0.399 | semantic | 1 / 1 / 2 | 2 |
| `bio-02` | 0.370 | 0.457 | **0.496** | hybrid | 3 / 2 / 3 | 5 |
| `bio-05` | 0.236 | **0.636** | 0.545 | semantic | 6 / 1 / 1 | 1 |
| `cs-02` | 0.188 | 0.180 | **0.192** | hybrid (a tie in practice) | 1 / 3 / 2 | 12 |
| `cs-05` | **0.754** | 0.587 | 0.642 | lexical | 1 / 1 / 1 | 7 |
| `cs-06` | 0.320 | 0.549 | **0.557** | hybrid (narrowly) | 2 / 1 / 2 | 2 |

NDCG@10 wins: semantic 2, hybrid 3, lexical 1.

### The lead is domain-shaped

| | method | P@5 | P@10 | R@10 | MRR | NDCG@10 |
|---|---|---|---|---|---|---|
| biomedical | lexical | 0.267 | 0.400 | 0.263 | 0.500 | 0.311 |
| (bio-01/02/05) | **semantic** | **0.600** | **0.567** | **0.405** | **0.833** | **0.541** |
| | hybrid | 0.467 | 0.467 | 0.330 | 0.611 | 0.480 |
| computing | lexical | 0.333 | 0.267 | 0.344 | **0.833** | 0.421 |
| (cs-02/05/06) | semantic | **0.467** | 0.267 | 0.350 | 0.778 | 0.439 |
| | **hybrid** | 0.333 | **0.367** | **0.433** | 0.667 | **0.464** |

Semantic's aggregate win is carried almost entirely by the biomedical half,
where it leads lexical by 0.230 NDCG@10. Across the three computing queries the
three methods sit within 0.043 of each other and lexical has the best MRR. Any
statement of the form "semantic is better" has to be qualified by domain until
the other six queries are judged.

### What `cs-02` says now that it is complete

The four papers that invalidated it are graded, and the result is not the one
the titles suggested:

| paper | grade | lexical | semantic | hybrid |
|---|---|---|---|---|
| RAGSieve | **2** | 1 | 4 | 2 |
| HybridRAG-BN | **2** | 17 | not in top 20 | 15 |
| HC-RAG | **0** | 2 | 1 | 1 |
| IterCOMP | **0** | 6 | 2 | 3 |

Both retrievers surfaced RAG-titled papers immediately; only lexical put a
*relevant* one first. Semantic's top two are both graded 0 — `HC-RAG` is
retrieval-augmented generation applied to financial filings and `IterCOMP` is
prompt compression for multi-hop QA, so both match the phrase without being
about the method. Lexical MRR is 1.000 against semantic's 0.333. All three
methods score badly in absolute terms (NDCG@10 0.180-0.192 with 10 relevant
papers in the pool), so `cs-02` separates the methods on MRR and on nothing else.

### `cs-06` is where fusion looks best

*AI safety evaluation*, the query written to be hardest for lexical search.
Lexical returns only 10 papers in total, but 4 of those 10 are relevant.
Semantic returns 20 with 3 relevant in its top 10, including its top two. The
two lists overlap on 2 of 20 papers - they are finding **different** relevant
literature - and fusion collects both: hybrid P@10 0.600 against semantic 0.300
and lexical 0.400, R@10 0.500 against 0.250 and 0.333.

This contradicts the overlap hypothesis recorded after four queries. Fusion did
not need consensus here; it needed both components to be independently
productive, and it lost nothing by their disagreeing.

### `bio-05` is where semantic looks best

*public health diabetes risk prediction*, three concepts that rarely co-occur in
one title. Lexical's top five contains no relevant paper and includes
*"Financial Dynamics and Interconnected Risk of Liquid Restaking"* - "risk" and
"prediction" match everywhere and discriminate nothing. Semantic leads with
*"From Prediction to Intervention: Personalized Meal-Level Glucose..."* (grade
3). NDCG@10 0.636 against 0.236, the widest margin in the set, and the two
top-20s overlap on a single paper.

### Fusion: both mechanisms are present in the same runs

RRF recovers relevant papers that one component buried:

| query | paper | grade | lex | sem | hybrid |
|---|---|---|---|---|---|
| `cs-06` | AI Guardrail Survival under Single-Cycle Agentic Self-Summarization | 3 | 8 | 12 | **2** |
| `bio-02` | Automating scientific annotations for open transcriptomic profiles | 3 | 18 | 6 | **5** |
| `bio-01` | Recent Advances in Deep Learning-Based Drug-Target Binding Affinity | 3 | 96 | 21 | **10** |

And RRF demotes a paper one component alone got right:

| query | paper | grade | lex | sem | hybrid |
|---|---|---|---|---|---|
| `bio-01` | PINT: Pathway-pathway interactions | 2 | not retrieved | **1** | 14 |
| `bio-05` | From Prediction to Intervention: Personalized Meal-Level Glucose | 3 | 41 | **1** | 5 |
| `cs-06` | Rules or Character? Scaling Laws for AI Safety Design | 3 | not retrieved | **1** | 8 |

Both effects appear in every query. Which one dominates decides whether hybrid
wins, and six queries do not identify a rule that predicts it: hybrid wins at
overlap 12 (`cs-02`), at 5 (`bio-02`) and at 2 (`cs-06`), and loses at 2
(`bio-01`), 1 (`bio-05`) and 7 (`cs-05`). Overlap does not explain the outcome.

What is consistent is the shape of the damage: **hybrid wins MRR on no query**,
ties the best component on two, and its aggregate MRR (0.639) is below both
lexical (0.667) and semantic (0.806). Fusion costs first-place accuracy and buys
recall.

**Nothing has been retuned on the basis of any of this.** No default, `k`,
weight, fusion algorithm, model setting, query or grade was changed. Six queries
is a set to measure against, not to fit to.

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
