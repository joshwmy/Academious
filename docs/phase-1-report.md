# Phase 1 Report — Ingestion Foundation

**Date:** 2026-08-28
**Status:** Complete. Stopping before Phase 2, as instructed.
**Scope:** the literature-data foundation only. No recommendations, no frontend
personalisation, no LLM anywhere in the codebase.

---

## 1. What was built

| # | Requirement | Where |
|---|---|---|
| 1 | Source connector abstraction | `sources/base.py`, `sources/registry.py` |
| 2 | OpenAlex ingestion | `sources/openalex/` |
| 3 | arXiv ingestion via OAI-PMH | `sources/arxiv/` |
| 4 | bioRxiv / medRxiv ingestion | `sources/biorxiv/` |
| 5 | Canonical Paper model | `db/models/paper.py` |
| 6 | Source identity records | `source_record` table, `db/models/support.py` |
| 7 | Normalisation | `core/ids.py`, `core/text.py`, per-source `normalise.py` |
| 8 | DOI/identifier deduplication | `ingest/canonicalise.py` |
| 9 | Preprint → publication relationships | `ingest/relations.py`, `paper_relation` |
| 10 | OA metadata capture | `ingest/oa.py`, `oa_location` table |
| 11 | Retraction Watch integration | `sources/retractionwatch/`, `ingest/retractions.py` |
| 12 | PostgreSQL migrations | `migrations/versions/0001_initial_schema.py` |
| 13 | `SKIP LOCKED` job framework | `jobs/queue.py` |
| 14 | Structured logging | `core/logging.py` (structlog, JSON) |
| 15 | Rate-limit handling | `core/ratelimit.py`, `core/http.py` |
| 16 | Deterministic tests with mocked APIs | `tests/`, 133 tests, no network |
| 17 | Ingestion metrics | `ingestion_run` table, `GET /metrics/ingestion` |

Eleven tables, one migration, three source connectors plus Retraction Watch, a
worker CLI, and a FastAPI app exposing health and metrics.

Scope was not expanded: there is no ranking, no user model, no embedding, no
summarisation and no frontend.

## 2. Verification

```
133 tests passed
83% statement coverage
ruff: All checks passed
alembic upgrade head: clean against PostgreSQL 17 + pgvector
scripts/demo_phase1.py: all acceptance checks passed
```

Coverage sits at 83%. The uncovered remainder is concentrated in thin wiring -
`api/main.py`, `db/session.py`, the three connector classes that only delegate -
rather than in logic. Normalisation, deduplication, merge precedence, rate
limiting and HTTP error handling are all well above the 80% bar; connector HTTP
glue is covered by recorded-fixture contract tests instead of line coverage,
which is the split argued for in the Phase 0 report.

**No test touches the internet.** Every external payload in `tests/fixtures/` was
captured from the real API during this phase and is replayed offline. Database
tests are marked `db` and skipped, not failed, when no PostgreSQL is configured,
so `pytest` is green on a bare checkout.

## 3. The demonstration

`python scripts/demo_phase1.py` runs the real pipeline against real captured
payloads and checks every acceptance criterion. Abridged output:

```
1. Ingest a paper
   title:   Integron cassettes integrate into bacterial genomes via widespread
   doi:     10.1038/s41564-023-01548-y
   authors: 14  first surname: loot
   [PASS] run status is succeeded / one paper created / canonical DOI stored

2. Ingest the same paper from a second source
   papers before: 1   after: 1
   identifier: doi       10.1038/s41564-023-01548-y
   identifier: openalex  W4390571678
   identifier: pmid      38172619
   abstract now present: True
   [PASS] no duplicate; identifiers from both sources on one canonical paper

3. Connect a preprint to its published version
   preprint : 10.1101/2022.09.11.507474  (A new route for integron cassette...)
   published: 10.1038/s41564-023-01548-y  (Integron cassettes integrate into...)
   relation : preprint_of (from biorxiv)
   [PASS] kept as separate records, linked by relation

4. Capture open-access metadata
   oa_status: bronze   fulltext_status: linked
    * [publisher/publishedVersion] https://doi.org/10.1016/s0140-6736(20)31180-6
      [repository/submittedVersion] https://www.ncbi.nlm.nih.gov/pmc/articles/7255293
      [repository/submittedVersion] https://www.ncbi.nlm.nih.gov/pmc/articles/7274621
   [PASS] 3 locations stored, exactly one best elected

5. Identify known retraction information
   2020-06-03  Expression of concern  -> concern
   2020-05-30  Correction             -> corrected
   2020-06-05  Retraction             -> retracted
   resolved status: retracted
   [PASS] most severe notice wins

6. Survive a source failure
   run status: failed   errors: 1
   papers before failure: 3   after: 4
   stored cursor after a failed run: None
   [PASS] ingested records kept; cursor not advanced, so the run is retried

7. Rerun ingestion idempotently
   papers: 4 -> 4      source records: 5 -> 5
   records skipped as unchanged: 3   papers created: 0
   [PASS] no duplicates on replay

RESULT: all acceptance checks passed
```

Every paper in that run is real: a *Nature Microbiology* article and its bioRxiv
preprint, the retracted *Lancet* hydroxychloroquine paper, and "Attention Is All
You Need" from arXiv.

## 4. What contact with the live APIs changed

Phase 0 was research; Phase 1 was the first time the design met real payloads.
Four assumptions did not survive, and all four are corrected in the code and docs.

### 4.1 Abstracts cannot be an ingestion requirement

The Phase 0 ingest filter said "has an abstract, or is a preprint". Live OpenAlex
records for published journal articles frequently have **no**
`abstract_inverted_index` at all - both integron fixtures show it. Enforcing that
filter would have silently discarded a large share of the biomedical corpus.

Abstract coverage is now a metric to watch, not a gate.

### 4.2 arXiv volume is roughly 3.5x the estimate

A single OAI-PMH request for `set=cs`, one day (2026-08-18), returned **1,300
records** - about 39,000/month for computer science alone, against the
11,000/month assumed in the cost model.

The OAI window filters on *datestamp*, so this includes metadata updates to
existing papers rather than only new submissions. It is nonetheless the volume
the pipeline processes. The cost model's volume figure should be re-derived from
`ingestion_run` counters after a week of real harvesting; every downstream number
scales linearly with it.

### 4.3 arXiv-to-OpenAlex matching is weaker than assumed

OpenAlex does not expose arXiv ids as identifiers. The only link is an
`arxiv.org` URL on a location record, which `ids.arxiv_id_from_url` now extracts.

Worse, papers predating arXiv's DOI assignment share no DOI either, and OpenAlex
has begun minting arXiv works under an opaque `10.65215/...` prefix that cannot
be derived from the arXiv id - unlike `10.48550/arXiv.*`, which can.

Cross-source matching for arXiv content therefore leans on the fuzzy
title-and-author path considerably more than planned. That path was already in
the design; this finding raises it from "safety net" to "load-bearing".

### 4.4 Preprint and published versions have different titles

Phase 0 asserted this; Phase 1 confirmed it with a concrete pair, now ADR 0004.
The bioRxiv preprint is titled *"A new route for integron cassette dissemination
among bacterial genomes"*; the *Nature Microbiology* version is *"Integron
cassettes integrate into bacterial genomes via widespread non-classical attG
sites"*. No similarity threshold links those, and they share no identifier.
Without the bioRxiv publication map, preprint linking would not work at all.

## 5. Bugs the tests found

Six defects were caught before any of this ran against a live source. Recording
them because each was a genuine production failure mode, not a test artefact.

1. **The rate limiter cancelled its own penalty.** `_refill_locked`
   unconditionally advanced its timestamp, so the first refill after a 429 wiped
   the `Retry-After` deadline. A `Retry-After: 60` would have been honoured for
   about 0.1 seconds.

2. **The rate limiter then busy-spun on floating-point error.** After that fix,
   accumulated float error left the token count at 0.999... indefinitely and the
   acquire loop spun on microsecond sleeps forever. Fixed with an epsilon
   comparison and a minimum sleep. It hung the test suite - which is exactly
   where you want to find it.

3. **The arXiv parser could silently return nothing.**
   `root.find(ListRecords) or root.find(GetRecord)` relies on an Element's truth
   value, which is `False` for an element with no children, so an empty result
   page fell through to a `None` container and yielded zero records with no error.

4. **bioRxiv pagination stopped early.** The loop treated any page shorter than
   the nominal page size as the end of results, ignoring the authoritative
   `total`, and would have dropped the remainder after a short page.

5. **A row-value `IN` clause never bound its parameters.** The identifier lookup
   was written as raw SQL with a tuple parameter; PostgreSQL rejected it outright
   once a real database was involved. Replaced with SQLAlchemy `tuple_().in_()`.

6. **The trigram operator collided with psycopg's parameter syntax.** A literal
   `%` in raw SQL had to be escaped as `%%`, which reached PostgreSQL as `%%` and
   failed. The fuzzy query is now built from expressions using `.op("%")`, which
   emits it correctly and still uses the GIN index.

## 6. Deliberate deviations from the approved design

| Deviation | Why |
|---|---|
| `title_norm` does not strip stopwords | Scientific titles are short; dropping `of`/`the`/`in` measurably degrades trigram similarity on exactly the short titles where deduplication is hardest. |
| `OPENALEX_FILTERS` is a `;`-separated list, not one expression | OpenAlex supports OR only *within* a filter key, so the two launch domains cannot be a single query. Each is harvested separately. |
| arXiv raw payloads stored as dicts, not XML | `source_record.payload` is JSONB. The XML-to-dict conversion is lossless for every field arXiv publishes. |
| No `paper_embedding` or `paper_summary` tables yet | Phase 1 does no embedding or summarisation; creating unused tables would be scope expansion. |

## 7. Known limitations

* **Fuzzy dedup is untuned at scale.** The thresholds (0.92 title similarity,
  0.50 author Jaccard) are reasoned, not measured against a large corpus. The
  `paper_merge` audit table exists precisely so tuning can be evaluated after the
  fact.
* **Rate-limit buckets are process-local.** Correct for one worker; a second
  worker process needs source partitioning or shared buckets.
* **No PubMed, Europe PMC or Unpaywall yet.** Phase 2, as planned. OA resolution
  currently uses only what OpenAlex supplies, plus preprint locations.
* **`link-publications` only links papers already ingested.** Incomplete pairs
  are picked up on a later run; nothing queues them explicitly.
* **No backup implementation.** Designed in `deployment.md` as required; building
  and drilling it is a Phase 6 exit criterion.
* **The API surface is health and metrics only.** Deliberate.

## 8. Cost-model follow-up

`docs/cost-model.md` answered the Phase 0 cost question from first principles:
the ceiling is **$219/month** to give a Tier 2 explanation to every one of
150,000 papers/month, using Haiku 4.5 at 820 input / 420 output tokens through
the Batch API, with no prompt-caching discount claimed - the stable prefix is too
short to cache.

Section 4.2 puts the volume assumption in doubt. Re-derive it from real
`ingestion_run` counters before Phase 5 commits to a budget.

The four-tier hierarchy was adopted, and the honest finding is recorded there:
**the demand gate defers the ceiling rather than avoiding it.** It saves 98% at
100 users and roughly nothing past 50,000, by which point the union of everyone's
interests covers the corpus. Its durable value is blast-radius control against a
mis-scoped source config, not marginal savings.

## 9. What Phase 2 needs

Nothing in Phase 1 blocks Phase 2. The work waiting is:

1. PubMed connector - registered `tool`/`email`, off-peak scheduling, MeSH terms.
2. Europe PMC connector - OA subset full text, within the bulk-download prohibition.
3. Unpaywall fallback in the OA resolver, plus the embargo re-check schedule.
4. Public read API - paper detail, field feed, full-text search over `tsvector`
   plus trigram.
5. React/Vite frontend with prerendered paper pages, canonical URLs and scholarly
   structured data, per decision 3.

## 10. Before running against live sources

1. **Register an OpenAlex API key** and set `ACADEMIOUS_OPENALEX_API_KEY`.
   Without it the quota is 100 credits/day, and the harvester logs a warning on
   every run.
2. **Set `ACADEMIOUS_CONTACT_EMAIL`.** It goes into every `User-Agent`. arXiv and
   NCBI ban by IP, and an unreachable contact address is how that starts.
3. **Start with `--max-records`.** A capped first run against a new filter costs
   little and shows what the filter actually matches.
4. **Register `tool`/`email` with NCBI** before Phase 2 adds PubMed - registering
   is a separate step from sending the parameters.
