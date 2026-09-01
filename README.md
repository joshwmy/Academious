# Academious

**A personalised discovery layer over scientific literature.**

Academious is being built to answer one question:

> **What new research came out that I would probably care about?**

Then *why should I care about it?*, and only then *help me understand it.* That
order is the product. Discovery comes first; explanation and summarisation are
how a recommendation becomes useful, not what the product is.

Recommendation and discovery features already exist in academic tooling —
Academious is not claiming to invent them. The bet is on **hierarchy**: those
capabilities usually sit inside a search engine, citation graph, reference
manager or literature-review workflow, whereas Academious is being designed
around the personalised feed itself, with search and reading tools serving it
rather than the other way round.

Think of what recommendation did to how people find music or video, applied to
research literature: you should not have to know what you want before you open
it.

[docs/product.md](docs/product.md) is the canonical statement of that direction.

## Where this actually is

**Phase 2, public web.** What runs today is the foundation discovery needs, not
discovery itself:

| | Today | Direction |
|---|---|---|
| **Corpus** | Five sources harvested, normalised, deduplicated into one corpus | Broader coverage, scheduled freshness |
| **Retrieval** | Semantic, lexical and hybrid search over a research-interest description | Candidate generation for a feed |
| **Feed** | `/papers` is newest-first and identical for every visitor | Personalised ranking |
| **Personalisation** | None. No accounts, no interest model, no feedback signals | Multi-centroid interest profiles |
| **Explanation** | None | Why this paper, for this reader |
| **Understanding** | None. No LLM anywhere in the codebase | Summaries, after discovery works |

Phase 1 built the literature-data foundation. Phase 2 built the layer that makes
it searchable — SPECTER2 embeddings in pgvector, semantic, lexical and hybrid
retrieval, and a reproducible way to measure whether any of it is any good —
then put a public API and a React frontend on top of it. **Personalised ranking
is the next product layer, and none of it exists yet.**

```bash
# API
uvicorn academious.api.main:app --port 8000        # docs at /docs

# Frontend
cd web && npm install && npm run dev               # http://localhost:5173
```

See [docs/api.md](docs/api.md) for the HTTP contract,
[docs/frontend.md](docs/frontend.md) for the web application, and
[docs/security.md](docs/security.md) for the threat model.

---

## What Phase 1 does

```
OpenAlex   ─┐
arXiv      ─┤
bioRxiv    ─┼─▶ harvest ─▶ normalise ─▶ canonicalise ─▶ enrich ─▶ PostgreSQL
medRxiv    ─┤              (pure)       (dedup)         (OA,
Europe PMC ─┘                                            retractions)
```

* **OpenAlex** is the metadata spine - CC0, every discipline, with OA status,
  topics, venue and citation counts in one record.
* **arXiv** (OAI-PMH) and **bioRxiv/medRxiv** exist to fix OpenAlex's latency on
  brand-new preprints, and bioRxiv additionally provides the only authoritative
  preprint-to-published DOI map.
* **Europe PMC** (added in Phase 2, over the same pipeline) brings
  peer-reviewed biomedical records, MeSH descriptors and author affiliations,
  harvested over its open-access subset - the only content its terms permit an
  automated process to take in bulk.
* **Retraction Watch** (via Crossref, CC-BY 4.0) supplies retraction, correction
  and expression-of-concern notices.

Launch scope is biomedicine/life sciences and computer science/AI/ML. The
architecture is domain-neutral; only the configured filters are not.

## What Phase 2 adds

```
paper ─┬─▶ SPECTER2 (proximity adapter) ─▶ halfvec(768) in pgvector ─┐
       │                                                             ├─▶ hybrid
       └─▶ tsvector (title A, keywords B, abstract C) ───────────────┘    (RRF)
                                                                           │
research interest ─▶ SPECTER2 (ad-hoc query adapter) ──────────────────────┘
```

* **Embeddings.** SPECTER2 vectors, one row per canonical paper per
  model version, stored at half precision. Embedding runs are idempotent,
  resumable and crash-safe, and a failure cannot damage ingestion.
* **Retrieval.** Semantic (exact pgvector cosine), lexical (weighted PostgreSQL
  full-text search) and a transparent reciprocal-rank-fusion hybrid, with
  filters applied in SQL before ranking.
* **Evaluation.** A pooled benchmark over twelve research-interest queries that
  reports rankings always and quality metrics only once a human has judged
  something.

Papers do **not** need abstracts: a title-only paper is embedded from its title
and the fallback is recorded on the row. Retracted papers are excluded from
ordinary discovery by default; corrections and expressions of concern are
returned with their status attached.

## Quick start

```bash
cp .env.example .env          # then set ACADEMIOUS_CONTACT_EMAIL at minimum
docker compose up -d db
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/alembic upgrade head

# Harvest the last 7 days from every configured source
.venv/bin/python -m academious.workers harvest --source all

# Retraction notices, and the preprint publication map
.venv/bin/python -m academious.workers retractions
.venv/bin/python -m academious.workers link-publications

# Embed anything that needs it (needs the `embed` extra; downloads ~440 MB once)
.venv/bin/pip install -e ".[dev,embed]"
.venv/bin/python -m academious.workers embed --pending
.venv/bin/python -m academious.workers embed

# Search, and run the retrieval benchmark
.venv/bin/python -m academious.workers search "machine learning for cancer genomics"
.venv/bin/python -m academious.workers evaluate --depth 20
```

The API (health and ingestion metrics only in Phase 1):

```bash
docker compose up -d api
curl localhost:8000/health
curl localhost:8000/metrics/ingestion
```

### Configuration

Everything comes from the environment; see `.env.example`. Two values matter
most before running against live APIs:

| Variable | Why |
|---|---|
| `ACADEMIOUS_CONTACT_EMAIL` | Sent in every outbound `User-Agent`. arXiv, NCBI, Crossref and Unpaywall all require a reachable address, and several ban anonymous traffic. |
| `ACADEMIOUS_OPENALEX_API_KEY` | Free, but **required since 2026-02-13**. Without one the quota is 100 credits/day, which is demo-only; with one it is 100,000/day. |

## Tests

```bash
.venv/bin/pytest              # pure tests; no network, no database
docker compose up -d db
.venv/bin/pytest -m db        # database tests, needs PostgreSQL with pgvector
```

No test touches the internet, and **no test downloads the model**. Every
external payload in `tests/fixtures/` was captured from the real API and is
replayed offline; embedding tests use `HashingBackend`, a deterministic
dependency-free stand-in that produces real vectors without loading SPECTER2.
Database tests need PostgreSQL with `pg_trgm` and `pgvector`; they are skipped,
not failed, when no database is configured.

## Acceptance demonstration

```bash
docker compose up -d db
.venv/bin/python scripts/demo_phase1.py
.venv/bin/python scripts/demo_phase2.py            # --backend hashing to skip the model
```

`demo_phase1.py` walks every Phase 1 acceptance criterion against real captured
payloads - ingesting a paper, recognising the same paper from a second source,
linking a preprint to its published version, capturing OA metadata, applying
retraction notices, surviving a source outage, and replaying idempotently.

`demo_phase2.py` walks every Phase 2 criterion - detecting an unembedded paper,
generating and persisting the vector, proving a re-run does no inference,
embedding a paper that has no abstract, running all three retrieval methods,
excluding retracted papers by default, applying filters, producing an
inspectable evaluation comparison, and surviving a worker killed mid-job.

Measurements are reproduced by:

```bash
.venv/bin/python scripts/benchmark_phase2.py --papers 150 --corpus 800
```

## Documentation

| Document | Contents |
|---|---|
| [docs/product.md](docs/product.md) | **What Academious is for — positioning, hierarchy, current state vs direction** |
| [docs/phase-0-report.md](docs/phase-0-report.md) | API landscape, architecture, V1 scope, risks, disagreements |
| [docs/phase-1-report.md](docs/phase-1-report.md) | What Phase 1 built, what it proved, what it found |
| [docs/phase-2-report.md](docs/phase-2-report.md) | What Phase 2 built, measured, and what contradicted earlier assumptions |
| [docs/backlog.md](docs/backlog.md) | **Deferred and open engineering work - the canonical register** |
| [docs/embeddings.md](docs/embeddings.md) | SPECTER2, input construction, halfvec storage, embedding jobs |
| [docs/retrieval.md](docs/retrieval.md) | Lexical, semantic and hybrid retrieval; filters and retraction policy |
| [docs/evaluation.md](docs/evaluation.md) | Benchmark queries, pooling, judgments, metrics, limitations |
| [docs/performance.md](docs/performance.md) | Measured throughput, storage, latency, and labelled projections |
| [docs/cost-model.md](docs/cost-model.md) | Derived unit economics and the processing tiers |
| [docs/architecture.md](docs/architecture.md) | Modules, pipeline, job queue, deployment |
| [docs/data-model.md](docs/data-model.md) | Schema, deduplication rules, field precedence |
| [docs/sources.md](docs/sources.md) | Per-source endpoints, limits, quirks |
| [docs/ingestion.md](docs/ingestion.md) | Pipeline stages, cursors, idempotency, replay |
| [docs/open-access.md](docs/open-access.md) | Resolution chain, licence policy, what we may store |
| [docs/adr/](docs/adr/) | One file per architectural decision |

## Licence and conduct

This project links to legal copies of research; it never bypasses paywalls,
never re-hosts publisher PDFs, and never scrapes publisher pages. See
[docs/open-access.md](docs/open-access.md).
