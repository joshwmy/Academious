# Cost Model

Answers the Phase 0 cost question in full, replaces the loose "$225/month ceiling"
claim in `phase-0-report.md` §9.3 with a derived figure and its sensitivities, and
adopts the four-tier processing hierarchy.

**Status:** approved inputs, Phase 0. Revisit at the end of Phase 1 — the volume
assumption is by far the largest source of error, and Phase 1 measures it.

---

## 1. The processing hierarchy

Adopted as specified, with each tier's gate made explicit.

| Tier | What | Applies to | Marginal cost | Cached |
|---|---|---|---|---|
| **0** | Metadata + abstract, stored verbatim | **every** ingested paper | storage only | n/a |
| **1** | Embedding + indexing (tsvector, trigram, vector) | **every** ingested paper in the active window | CPU only, $0 external | per paper, forever |
| **2** | Canonical short explanation (7 fields, abstract-based) | papers passing the demand gate (section 4) | $0.0015 batched | **globally**, per paper |
| **3** | Deep analysis (full text where legal, else extended abstract read) | on demand, or top-demand papers | $0.011-0.061 | **globally**, per paper |

Two properties make this work:

1. **Tiers 2 and 3 are paper-level, not user-level.** Two users opening the same
   paper share one generation. Only conversational Q&A (Phase 8) is per-user.
2. **Tier 2 is a ranked queue, not a filter.** Papers are ordered by demand and the
   queue drains until the monthly budget is spent. Cost is therefore a *configured
   input*, not an emergent output. That is the answer to "what if publication volume
   is significantly higher" — section 6.

---

## 2. Volume: how many papers per month

Scope is the two approved launch domains, not all of scholarship.

| Stream | Records/month | Basis |
|---|---|---|
| PubMed / MEDLINE-indexed biomedical | ~125,000 | ~1.5M records/year |
| arXiv `cs.*` + `stat.ML` | ~11,000 | ~24k/month arXiv total, CS approx 45% |
| bioRxiv | ~2,500 | |
| medRxiv | ~1,500 | |
| **Gross** | **~140,000** | |
| Less cross-source duplicates (preprint/published, PubMed and OpenAlex overlap) | -8% to -12% | measured in Phase 1 |
| **Net distinct papers/month** | **~125,000-130,000** | |

**Planning figure: 150,000/month** — deliberately ~15% above the estimate, so the
ceiling in section 5 is an upper bound rather than a central case.

> This is an estimate, not a measurement. Phase 1 produces the real figure from
> `ingestion_run` counters. Every number downstream scales linearly with it, so it
> is the first thing to re-derive once ingestion has run for a week.

### Which papers qualify for ingestion at all

Not everything PubMed indexes is worth storing. Filters applied at normalisation:

- has a title, and at least one resolvable identifier (DOI, PMID, PMCID, arXiv ID)
- publication type is research article, review, conference paper, or preprint —
  excludes editorials, letters, comments, news items, and errata-as-records
- has an abstract, **or** is a preprint (preprints occasionally lack one at posting)
- is not already a duplicate of a canonical paper

Applied to PubMed alone these typically remove 25-35% of raw records. That reduction
is **not** assumed in the 150,000 planning figure — it is headroom.

---

## 3. Unit costs, derived

### Tier 2 — canonical short explanation

Input is **the abstract only**, never full text. That is a deliberate constraint: it
bounds the token count, and it is the version whose provenance we can always honour
(`basis = 'abstract'`).

| Component | Tokens | Note |
|---|---|---|
| System prompt + JSON schema | ~350 | stable across all calls |
| Paper metadata (title, authors, venue, date, topics) | ~120 | |
| Abstract | ~350 | median abstract approx 250 words |
| **Total input** | **~820** | |
| Output (7 schema fields, ~300 words plus key terms) | **~420** | schema-constrained |

Model: **Claude Haiku 4.5** — $1.00/MTok input, $5.00/MTok output.

```
standard  = (820 / 1e6 * $1) + (420 / 1e6 * $5)
          = $0.00082 + $0.00210
          = $0.00292 per paper

batch API = $0.00292 * 0.50
          = $0.00146 per paper        <- planning figure
```

**Prompt caching does not help here.** The stable prefix is ~350 tokens, and the
minimum cacheable prefix is model-dependent (512-4096 tokens); a 350-token prefix
silently fails to cache. No caching discount is claimed anywhere in this document.
Revisit only if the system prompt later grows past the model's minimum.

### Tier 3 — deep analysis

| Basis | Input | Output | Haiku 4.5 | Sonnet 5 |
|---|---|---|---|---|
| Full text (OA article, trimmed) | ~18,000 | ~2,500 | $0.0305 | $0.0610 |
| Abstract only (no legal full text) | ~1,000 | ~2,000 | $0.0110 | $0.0220 |

Batched where not user-blocking; on-demand requests are synchronous and pay full
price. Globally cached, so the second reader of a paper pays nothing.

---

## 4. The Tier 2 demand gate

A paper qualifies when **any** of these holds:

1. It was **opened** by any user — generate synchronously (~2 s), then cache.
2. It ranks above the "strong match" threshold in **any** active user's feed.
3. It is in the top *N* by demand score for its field in the last 72 h, where demand
   = distinct users whose profile matches, weighted by recency.

Rule 1 guarantees nobody ever opens a paper with no explanation available. Rules 2-3
are pre-generation, run overnight on the batch API so the common case is already warm.

### What the gate actually saves

| Users | Distinct papers through the gate / month | Tier 2 cost | Saved vs. summarising everything |
|---|---|---|---|
| 100 | ~3,000 | $4 | 98% |
| 1,000 | ~20,000 | $29 | 87% |
| 10,000 | ~80,000 | $117 | 48% |
| 50,000+ | saturates at 150,000 | $219 | ~0% |

**Honest conclusion: the gate defers the ceiling, it does not avoid it.** Past roughly
30-50k users the union of everyone's interests covers essentially the whole corpus,
and gated cost converges on ungated cost. The gate is still worth building — it is the
difference between $4/month and $219/month in year one — but its value decays as the
product succeeds, and by the time it stops helping, $219/month is not the binding
constraint.

Its more durable job is **blast-radius control**: it is what stops a mis-scoped source
config (someone adds "all of chemistry") from becoming a 10x bill overnight.

---

## 5. The ceiling, restated precisely

> **If every ingested paper received a Tier 2 explanation:
> 150,000 * $0.00146 = $219/month, flat, independent of user count.**

That figure holds **only** under all of the following:

- 150,000 net distinct papers/month (section 2)
- abstract-only input, ~820 input / ~420 output tokens (section 3)
- Claude Haiku 4.5 at $1/$5 per MTok
- Batch API (-50%)
- no prompt-caching discount claimed
- Tier 3 excluded — it is demand-driven and counted separately

Tier 3 at 10,000 users, with a 10/user/month quota, ~20% of users using ~3/month and
a 60% global cache hit rate: ~2,400 uncached generations, approx **$146/month** on
Sonnet 5 or **$73/month** on Haiku 4.5.

---

## 6. Sensitivity — what breaks the number

| Change | Tier 2 monthly | Multiplier |
|---|---|---|
| **Baseline** — 150k papers, Haiku 4.5, batched, abstract | **$219** | 1.0x |
| Volume doubles (300k/month — two more domains added) | $438 | 2.0x |
| Volume x5 (universal coverage attempted) | $1,095 | 5.0x |
| Sonnet 5 instead of Haiku 4.5 | $438 | 2.0x |
| Batch API not used | $438 | 2.0x |
| Output grows to 800 tokens (looser schema) | $362 | 1.65x |
| **Full text instead of abstract at Tier 2** | **~$2,400** | **11x** |
| Ingest filters applied (section 2), -30% of records | $153 | 0.70x |
| Gate active at 1,000 users | $29 | 0.13x |

The two changes that hurt most are feeding full text into Tier 2 and attempting
universal domain coverage. Both are architecturally prevented: the Tier 2 prompt
builder accepts an abstract, not a document, and source scope is configuration that
goes through review.

### If publication volume is significantly higher than assumed

Cost does not rise, because Tier 2 is a budget-bounded ranked queue:

```
papers_summarised_this_month = min(
    papers_passing_gate,
    floor(monthly_budget_usd / unit_cost_usd)
)
```

At a $250 budget and $0.00146 unit cost that is ~171,000 papers/month — above the
planning volume, so under normal conditions the budget never binds. If volume tripled,
the queue would serve the highest-demand 171,000 and the remainder would stay at
Tier 0/1, where metadata, abstract, search and ranking all still work. Users never see
an error; they see a paper without a generated explanation, which is the honest default
state anyway.

---

## 7. Guardrails (build in Phase 5, not later)

1. `settings.llm_monthly_budget_usd` — the summariser refuses past it and logs at ERROR.
2. Alerts at 50% and 80% of budget.
3. `paper_summary.cost_usd`, `input_tokens`, `output_tokens` on every row — spend
   reporting is a `SUM()` over our own table, never a vendor console.
4. Per-user Tier 3 quota, enforced server-side.
5. Batch API by default; synchronous only when a user is waiting on screen.
6. A test that fails if any LLM client is reachable from a feed-serving code path.

---

## 8. Does SPECTER2 fit on the initial Hetzner box?

**Model facts**, verified against the model card: `allenai/specter2` is
`bert-base-uncased` plus adapters, fine-tuned from SciBERT. ~110M parameters,
768-dimensional output, 512-token maximum input, proximity adapter for retrieval.
Input is `title [SEP] abstract`, typically 150-300 tokens.

**Memory.** fp32 weights approx 440 MB; ONNX Runtime int8 approx 110 MB plus
400-600 MB of runtime and batch buffers. Working set approx **0.6-1.0 GB** — fits
beside Postgres on an 8 GB CX32, provided the embed worker runs as a single process.

**Throughput.** Published CPU int8 speedups over fp32 run 2.7-3.4x (3.23x on a
short-text benchmark; ~1.7-2x measured specifically on a 4-vCPU Azure E4ds_v4).
Applying the conservative end to a BERT-base fp32 baseline of ~8-12 docs/s at 256
tokens on 4 vCPU:

```
estimated throughput = 20-35 documents/second   (ONNX Runtime, int8, batch 32)
```

| Workload | Papers | At 25 docs/s | Verdict |
|---|---|---|---|
| **Daily delta** | ~5,000/day | **~3.5 minutes** | Comfortable — run nightly, off-peak |
| 6-month backfill | ~900,000 | ~10 hours | Acceptable as a one-off |
| **24-month backfill** | ~3.0-3.6M | **~33-40 hours** | **Does not fit comfortably** — two days contending with Postgres for CPU |

**Recommendation.**

- **Daily embedding stays on the Hetzner box.** A few minutes of CPU a night; a
  separate environment would be pure overhead.
- **The initial backfill does not.** Two acceptable options, decided at Phase 3:
  - **(a)** Spin a temporary Hetzner CCX33 (8 dedicated vCPU) for two days
    (approx EUR 4 prorated), embed the backlog into the production DB, destroy it.
  - **(b)** Start with a 6-month active window (~10 h, tolerable in place) and deepen
    to 24 months later using option (a).
- Recommended: **(b), then (a)** — a working product sooner, and the bigger job
  deferred until the schema has stopped moving.
- **These throughput figures are extrapolated from published benchmarks, not measured
  on our hardware.** `scripts/bench_embed.py` ships in Phase 3 and must run on the
  actual box before the backfill option is chosen.

None of this affects Phase 1, which performs no embedding.

---

## 9. Revised monthly totals

Same shape as `phase-0-report.md` section 9.2; the Tier 2 and Tier 3 lines are now derived.

| Line | 100 users | 1,000 users | 10,000 users |
|---|---|---|---|
| Hetzner compute (app + worker + Postgres) | $9 | $28 | $120 |
| Off-machine encrypted backups (B2 / R2) | $1 | $2 | $5 |
| Tier 1 embeddings (self-hosted) | $0 | $0 | $0 |
| Tier 2 explanations (gated) | $4 | $29 | $117 |
| Tier 3 deep analysis (quota + global cache) | $4 | $30 | $73-146 |
| Email | $0 | $0 | $20 |
| Monitoring, domain | $1 | $1 | $15 |
| **Total** | **~$19** | **~$90** | **~$350-380** |
| Per user / month | $0.19 | $0.09 | $0.035-0.038 |

Long-run worst case — all gates open, 10k+ users: $219 (Tier 2 ceiling) + ~$146
(Tier 3) + ~$160 (infrastructure) = **~$525/month**. That is the figure to plan
funding against, not the $350 central case.

---

## Sources

- Anthropic first-party pricing: Haiku 4.5 $1/$5 per MTok, Sonnet 5 $2/$10 per MTok, Batch API -50%
- [SPECTER2 model card](https://huggingface.co/allenai/specter2_base)
- [ONNX Runtime / OpenVINO BERT INT8 benchmarks](https://opensource.microsoft.com/blog/2023/01/25/improve-bert-inference-speed-by-combining-the-power-of-optimum-openvino-onnx-runtime-and-azure/)
- [Sentence Transformers efficiency guide](https://sbert.net/docs/sentence_transformer/usage/efficiency.html)
