# Academious

A discovery layer over global scientific literature.

The product answers two questions, in order: *what new research came out that I
would probably care about?* and then *help me understand it.* Discovery is the
product; AI explanation is an enhancement on top of it.

**Status: Phase 1 (ingestion foundation).** There is no user interface, no
personalisation and no LLM anywhere in the codebase yet. What exists is the
literature-data foundation everything else depends on: source connectors,
normalisation, deduplication, preprint linking, open-access capture and
retraction flags, with metrics and tests.

---

## What Phase 1 does

```
OpenAlex ─┐
arXiv    ─┼─▶ harvest ─▶ normalise ─▶ canonicalise ─▶ enrich ─▶ PostgreSQL
bioRxiv  ─┤              (pure)       (dedup)         (OA,
medRxiv  ─┘                                            retractions)
```

* **OpenAlex** is the metadata spine - CC0, every discipline, with OA status,
  topics, venue and citation counts in one record.
* **arXiv** (OAI-PMH) and **bioRxiv/medRxiv** exist to fix OpenAlex's latency on
  brand-new preprints, and bioRxiv additionally provides the only authoritative
  preprint-to-published DOI map.
* **Retraction Watch** (via Crossref, CC-BY 4.0) supplies retraction, correction
  and expression-of-concern notices.

Launch scope is biomedicine/life sciences and computer science/AI/ML. The
architecture is domain-neutral; only the configured filters are not.

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
.venv/bin/pytest -m db        # deduplication and pipeline tests, needs PostgreSQL
```

No test touches the internet. Every external payload in `tests/fixtures/` was
captured from the real API and is replayed offline. Database tests need
PostgreSQL with `pg_trgm` because fuzzy deduplication is SQL; they are skipped,
not failed, when no database is configured.

## Acceptance demonstration

```bash
docker compose up -d db
.venv/bin/python scripts/demo_phase1.py
```

Walks every Phase 1 acceptance criterion end to end against real captured
payloads - ingesting a paper, recognising the same paper from a second source,
linking a preprint to its published version, capturing OA metadata, applying
retraction notices, surviving a source outage, and replaying idempotently.

## Documentation

| Document | Contents |
|---|---|
| [docs/phase-0-report.md](docs/phase-0-report.md) | API landscape, architecture, V1 scope, risks, disagreements |
| [docs/phase-1-report.md](docs/phase-1-report.md) | What Phase 1 built, what it proved, what it found |
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
