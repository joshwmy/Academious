# Phase 0 — Research, Architecture & V1 Scope

**Working name:** Academious
**Status:** Accepted 2026-08-28. See section 16 for the decisions taken and
section 17 for corrections found once Phase 1 met the live APIs.
**Date:** 2026-08-28

---

## 0. Executive summary

The product is viable and cheap to run, but only if three decisions hold:

1. **OpenAlex is the spine, not one source among many.** It is CC0, covers every discipline, carries OA status, topics, venue metadata and citation counts in one record, and offers a free bulk snapshot. Everything else (PubMed, arXiv, bioRxiv/medRxiv, Unpaywall, Crossref) is a *freshness* or *enrichment* connector layered on top. Building six equal-weight connectors in V1 is the fastest way to drown in dedup work.
2. **Almost nothing is per-user.** Fetching, normalising, deduplicating, embedding, OA-resolving and summarising are all paper-level and globally cached. Even the "deep explanation" is paper-level. The only genuinely per-user computation in V1 is a similarity score over a few thousand candidate rows — pure Postgres, no LLM. This is what makes a free tier possible.
3. **Cost scales with papers published, not users.** There is a hard ceiling on LLM spend (~150k new in-scope papers/month), and once you hit it, adding users costs nothing extra. Estimated all-in: **~$25/mo at 100 users, ~$110/mo at 1,000, ~$300–550/mo at 10,000.**

Biggest risks, in order: relevance quality on day 1 (cold start), the Feb 2026 OpenAlex API-key/credit change, deduplication errors being user-visible, and a solo maintainer facing a spec with ~20 subsystems in it.

The spec is good. I disagree with it in seven specific places — §11.

---

## 1. API landscape (verified August 2026)

### 1.1 OpenAlex — primary metadata spine

| Property | Value |
|---|---|
| Auth | **Free API key required since 2026-02-13.** Keyless = 100 credits/day (demo only). |
| Free tier | 100,000 credits/day; hard cap 100 req/s |
| Credit cost | singleton (`/works/W123`) = 1; list (`/works?filter=…`) = 10; content download = 100; vector search = 1,000 |
| Polite pool | Being retired — `mailto` no longer the mechanism |
| Licence | Data is **CC0** |
| Bulk | Full snapshot on S3, free |
| Paid | Premium tiers exist (no public pricing); academic researchers can request elevated free limits |

**Implication:** 100k credits/day = **10,000 list calls/day**. At 200 results/page that is 2M work-records/day — roughly 100× more than we need for daily incremental ingest. Credits are not a constraint at our scale *provided* we never do naive per-paper singleton lookups in a loop. Use `filter=…|…|…` OR-syntax to batch up to 50 IDs into one list call.

**Caveat:** abstracts arrive as `abstract_inverted_index`, not plain text — a deliberate licensing decision on OpenAlex's part. We reconstruct locally. Cheap, but it means abstract fidelity is imperfect (whitespace/punctuation artefacts) and some records have no abstract at all.

### 1.2 Crossref — DOI truth + retractions

- **New limits effective 2025-12-01.** Public pool: 5 req/s singleton, 1 req/s list, 1 concurrent. Polite pool (send `mailto`): 10 req/s singleton, 3 req/s list, 3 concurrent.
- Metadata Plus is the paid tier; unchanged.
- Rate limits are advertised in `x-rate-limit-limit` / `x-rate-limit-interval` headers — read them, don't hardcode.

Crossref is ~90% redundant with OpenAlex for our purposes. **Keep it for two things only:** DOI resolution/validation, and the Retraction Watch data.

### 1.3 Retraction Watch — free, and we should use it

Crossref acquired the database in 2023 and released it openly under **CC-BY 4.0** (commercial use permitted with attribution). Three access paths: Crossref REST API, a CSV at `https://api.labs.crossref.org/data/retractionwatch?mailto=you@example.com`, or `git clone https://gitlab.com/crossref/retraction-watch-data`.

Clone the git repo nightly. It's small, it's free, and showing a retraction badge is a genuine differentiator against every "AI reads papers" competitor — and a safety requirement for the clinician audience.

### 1.4 PubMed / NCBI E-utilities — biomedical freshness

- 3 req/s without a key; **10 req/s with a free API key**.
- `tool` and `email` params must be *registered* with NCBI, not merely sent.
- NCBI asks that large jobs run weekends or 21:00–05:00 US Eastern on weekdays.
- Batch via `EPost` + `EFetch` (hundreds of records per call), never one request per PMID.

**Implication:** schedule the PubMed backfill worker on an off-peak cron. This is a real operational constraint, not a nicety — IP bans are how NCBI enforces it.

### 1.5 Europe PMC — the best free full-text source

- Free RESTful Articles API, no key required for normal use.
- ~3.2M **open-access** full-text articles; full text available as XML.
- Annotations API over OA articles (gene/disease/chemical entities) — useful later for topic tagging without an LLM.
- **Hard constraint, quoted:** *"It is not permissible to use any kind of automated process to bulk download other content from Europe PMC."* Bulk = OA subset only.

This is the primary Tier-2 full-text supply for biomedicine, and it is legally clean.

### 1.6 arXiv — CS/physics/maths freshness

- **1 request per 3 seconds, single connection, across all your machines.** This is the tightest limit of any source.
- Explicitly permitted: metadata retrieval, discovery tools, search interfaces, citation graphs, linking users to arXiv.org.
- Explicitly prohibited: redistributing e-prints, **serving PDFs or source files from our own servers unless licensed**, circumventing rate limits.
- Bulk alternatives: OAI-PMH, and S3 (requester-pays).

**Implication:** do not poll the arXiv REST API for volume. Use **OAI-PMH incremental harvest** for daily new records, and treat the REST API as a lookup of last resort. Note that most arXiv papers carry arXiv's non-exclusive licence, *not* a CC licence — check `license` per record before touching full text.

### 1.7 bioRxiv / medRxiv — preprints, and the dedup key

- Free, no key. `/details/{server}/{interval}/{cursor}` returns 30 records/call.
- **`/pubs/{server}/…` returns 100/call and maps preprint DOI → published DOI.**

That second endpoint is worth more than it looks: it is a free, authoritative preprint→published linkage feed, which is the single hardest part of scholarly deduplication. Harvest it nightly regardless of whether we ingested the preprint.

### 1.8 Unpaywall — OA resolution

- Free REST, **100,000 calls/day**, no key; requires `?email=you@example.com`.
- 120M+ DOIs, with OA colour (gold/hybrid/bronze/green), host type (publisher/repository), version, and licence.
- Full database snapshot available for bulk use.

100k/day is ample, but we mostly won't need it: OpenAlex already carries `best_oa_location` and `open_access.oa_status`. Use Unpaywall as the **fallback** resolver when OpenAlex reports closed or unknown, and as a periodic re-check for papers that go OA after publication (common — embargoes expire).

### 1.9 Semantic Scholar — enrichment only, do not depend on it

Reported limits are inconsistent across sources (5,000 req/5min shared unauthenticated pool in one place, 1 req/s per key in another). An individual API key grants roughly **1 request/second**, and unauthenticated traffic shares a single pool with everyone else on the internet. Exponential backoff is required.

Verdict: excellent data (TLDRs, influential-citation counts, embeddings), unacceptable as a critical-path dependency at 1 req/s. Defer to Phase 8 as an optional enricher.

### 1.10 Source strategy — recommendation

| Tier | Source | Role | Phase |
|---|---|---|---|
| **Spine** | OpenAlex | canonical metadata, topics, venue, OA status, citations, all disciplines | 1 |
| **Freshness** | arXiv (OAI-PMH) | CS/physics/maths, same-day | 1 |
| **Freshness** | bioRxiv + medRxiv | life-science preprints + preprint→published map | 1 |
| **Freshness** | PubMed (E-utilities) | biomedicine, MeSH terms | 2 |
| **Full text** | Europe PMC | legal OA full text (XML) | 2 |
| **Resolver** | Unpaywall | OA fallback + embargo re-check | 2 |
| **Integrity** | Retraction Watch (Crossref) | retraction/correction flags | 2 |
| **Enrichment** | Crossref | DOI validation, reference lists | 3 |
| **Optional** | Semantic Scholar | TLDRs, citation context | 8 |

Rationale for starting with only three: OpenAlex alone gives global coverage; arXiv and bioRxiv/medRxiv exist to fix OpenAlex's **latency** (it can lag days on brand-new preprints), which matters because the product's core claim is "what came out *today*". Adding PubMed in Phase 2 rather than Phase 1 is deliberate — it is the connector with the most ceremony (registration, off-peak scheduling, XML parsing, MeSH) and the least marginal coverage given OpenAlex indexes PubMed anyway.

---

## 2. Legal & open-access constraints

### 2.1 What we may store

| Content | Store? | Basis |
|---|---|---|
| Metadata (title, authors, DOI, venue, dates, topics) | **Yes** | OpenAlex CC0; Crossref metadata openly reusable; facts |
| Abstract | **Yes, with attribution + source link** | Reconstructed from OpenAlex CC0 index; Europe PMC/PubMed abstracts displayed with provenance |
| Full text — CC-BY / CC-BY-SA / CC0 | **Yes, may store and process** | Licence permits, attribution required |
| Full text — CC-BY-NC | **Store + process; flag NC** | Permitted non-commercially; revisit if monetising |
| Full text — PMC OA Subset | **Yes** | That is the subset's purpose |
| Full text — everything else | **No** | Includes most arXiv papers (arXiv non-exclusive licence ≠ CC) |
| Publisher PDFs | **Never re-host** | arXiv ToU explicitly prohibits; publishers likewise |
| Paywalled content | **Never** | No Sci-Hub, no paywall bypass, no scraping publisher HTML |

### 2.2 The OA resolution chain

Resolve once at ingest, re-check on a decaying schedule (day 7, day 30, day 90, then quarterly — embargoes lift):

1. OpenAlex `best_oa_location` / `open_access` block (free, already in hand)
2. PMC ID → `https://www.ncbi.nlm.nih.gov/pmc/articles/PMC…`
3. Europe PMC `fullTextUrlList`
4. Unpaywall `best_oa_location` (fallback)
5. Preprint version (arXiv / bioRxiv / medRxiv) via identifier or `/pubs/` reverse map
6. Repository links present in metadata (`locations[]` in OpenAlex includes institutional repositories)
7. Publisher OA landing page

Store **every** discovered location as an `oa_location` row (url, host_type, version, licence, source_of_discovery, verified_at), and pick a `best_oa_location_id` by policy: published-version > accepted-manuscript > preprint; publisher-hosted > repository; permissive licence > restrictive.

When nothing is found, the UI must say **"No legal free version found"** and offer the DOI link. Not "unavailable", not a dead-end — a link out plus the abstract is a complete, honest experience.

### 2.3 Rate-limit compliance as an architectural requirement

Every connector goes through a shared **token-bucket limiter keyed by source**, enforced in one process (or in Redis once there are multiple workers). Per-source config: rate, concurrency, retry/backoff policy, allowed hours, `User-Agent` with contact email. This is not optional politeness — arXiv and NCBI both ban by IP, and a ban is an outage with no support ticket.

### 2.4 Liability

The clinician/doctor audience raises the stakes on AI summaries. Requirements, not suggestions:

- Every AI-generated block is visibly labelled as machine-generated.
- Provenance line on every summary: *"Based on the abstract only"* / *"Based on the full text"*.
- No clinical-advice framing anywhere. "What this paper reports", never "what you should do".
- Retraction/correction flags surfaced prominently, above the summary.
- A published takedown/correction contact and process.

---

## 3. Architecture

### 3.1 Shape: modular monolith + workers

Agreed with the spec — one FastAPI application, one Postgres, background workers in the same codebase, one deployable image. Microservices here would be pure cost.

```
academious/
  apps/
    api/            FastAPI: routers, dependencies, schemas
    web/            React + TS + Vite
  packages/
    core/           config, logging, errors, ids, clock
    sources/        connector protocol + one module per source
    ingest/         harvest, normalise, canonicalise, upsert, enrich
    oa/             open-access resolver
    embed/          embedding providers + batching
    rank/           candidate generation, scoring, explanations
    summarise/      tier policy, prompt assembly, schemas, provenance
    search/         full-text + (later) semantic search
    db/             SQLAlchemy models, Alembic migrations, repositories
  workers/          scheduled jobs (harvest, enrich, embed, summarise)
  tests/
  docs/
```

Hard rule from the spec, kept: files stay under ~400 lines; a connector that grows past that splits into `client.py` / `normalise.py`.

### 3.2 Pipeline

```
                    ┌──────────────────────────────────────────┐
  cron/scheduler ──▶│ 1. HARVEST   per-source, rate-limited     │
                    │    → source_record (raw JSONB, immutable) │
                    └────────────────┬─────────────────────────┘
                                     ▼
                    ┌──────────────────────────────────────────┐
                    │ 2. NORMALISE  raw → PaperCandidate        │
                    │    ids, title, abstract, authors, dates   │
                    └────────────────┬─────────────────────────┘
                                     ▼
                    ┌──────────────────────────────────────────┐
                    │ 3. CANONICALISE  identifier match →       │
                    │    fuzzy match → merge or insert          │
                    └────────────────┬─────────────────────────┘
                                     ▼
                    ┌──────────────────────────────────────────┐
                    │ 4. ENRICH  OA resolve, retraction check,  │
                    │    topic tags, venue link                 │
                    └────────────────┬─────────────────────────┘
                                     ▼
                    ┌──────────────────────────────────────────┐
                    │ 5. EMBED  title+abstract → vector (once)  │
                    └────────────────┬─────────────────────────┘
                                     ▼
                    ┌──────────────────────────────────────────┐
                    │ 6. INDEX  tsvector, trigram, HNSW         │
                    └──────────────────────────────────────────┘

  request time:  CANDIDATES → SCORE → EXPLAIN → serve   (no LLM)
  on demand:     SUMMARISE (tiered, cached, provenance-tagged)
```

Steps 1–6 are **global**. Nothing in that pipeline runs per user, ever.

### 3.3 Job queue: Postgres, not Celery

Use a `jobs` table with `SELECT … FOR UPDATE SKIP LOCKED`. Rationale: at our volume (~5k papers/day = ~30k jobs/day) Postgres handles this trivially, and it removes Redis, a broker, a result backend, and Celery's operational surface from V1. Add Redis in Phase 5, when it earns its place as a *cache* (feed candidates, hot paper pages, rate-limit buckets) rather than as a broker.

Scheduling: systemd timers or cron invoking `python -m workers.<job>`. Explicit, greppable, restart-safe. APScheduler-in-process is the alternative but hides failures.

### 3.4 Connector contract

```python
class SourceConnector(Protocol):
    key: str                      # "openalex", "arxiv", …
    def harvest(self, since: datetime, cursor: str | None
                ) -> Iterator[tuple[RawRecord, str]]: ...   # record, next_cursor
    def normalise(self, raw: RawRecord) -> PaperCandidate: ...
```

Two methods, cleanly separable, both independently testable against recorded fixtures. Harvest is the only place that touches the network; normalise is a pure function. That split is what makes the "no internet in tests" requirement achievable.

### 3.5 Prompt-injection defence

Papers are untrusted input. The defence is structural, not lexical — do not attempt to regex-filter "ignore previous instructions".

1. **The summarisation call has no tools and no network.** This is the load-bearing control: an injected instruction has nothing to actuate. Even a fully successful injection can only produce a bad summary, never an action.
2. Document text goes in a **user** message inside explicit delimiters, never in the system prompt.
3. The system prompt states that delimited content is data to be analysed, and that any instructions inside it are content to be reported on, not obeyed.
4. **Structured output with a strict JSON schema.** A hijacked completion fails schema validation and is discarded rather than rendered.
5. Post-validation: reject summaries containing URLs not present in the source, or exceeding length bounds.
6. Log `prompt_version` with every summary so a bad prompt generation can be invalidated in one query.

---

## 4. Data model

Deliberately smaller than the spec proposes. Reasoning in §11.1.

### 4.1 Core

```
paper
  id                    uuid pk
  canonical_doi         text unique null      -- normalised: lowercase, bare "10.x/y"
  title                 text not null
  title_norm            text not null         -- lowercased, unpunctuated, stopword-stripped
  abstract              text null
  abstract_source       text null             -- openalex | pubmed | europepmc | crossref
  authors               jsonb not null        -- [{name, orcid, openalex_id, affiliation, position}]
  first_author_surname  text null             -- extracted, for dedup blocking
  venue_id              uuid fk null
  published_date        date null
  first_seen_online     date null
  is_preprint           bool not null
  is_peer_reviewed      bool not null
  type                  text                  -- article | review | preprint | conference | dataset
  language              text null
  topics                jsonb                 -- [{id, label, score, scheme}] scheme=openalex|mesh
  keywords              text[]
  citation_count        int null
  citation_count_at     timestamptz null
  oa_status             text                  -- gold|hybrid|bronze|green|closed|unknown
  best_oa_location_id   uuid fk null
  fulltext_status       text                  -- none|abstract_only|stored|linked
  fulltext_licence      text null
  retraction_status     text                  -- none|retracted|corrected|concern
  retraction_notice_url text null
  quality_prior         real                  -- precomputed, see §6.3
  search_vector         tsvector generated
  created_at, updated_at
```

```
paper_identifier                      -- the merge substrate
  paper_id uuid fk, type text, value text
  primary key (type, value)           -- type ∈ doi|pmid|pmcid|arxiv|openalex|mag|biorxiv

paper_relation
  from_paper_id, to_paper_id, type    -- preprint_of | version_of | corrects | retracts
  source                              -- where the link came from
  primary key (from_paper_id, to_paper_id, type)

source_record                         -- immutable raw audit trail
  id, source_key, source_id, paper_id fk null,
  payload jsonb, fetched_at, ingestion_run_id

oa_location
  id, paper_id fk, url, host_type,    -- publisher|repository|preprint
  version,                            -- published|accepted|submitted
  licence text null, discovered_via text, verified_at, is_best bool

venue
  id, openalex_id, issn_l, name, publisher,
  type,                               -- journal|conference|repository|preprint_server
  is_oa bool, mean_citedness_2y real null

paper_embedding
  paper_id pk fk, model text, dim int,
  vector halfvec(768), created_at

paper_summary
  id, paper_id fk, tier smallint,     -- 1 | 2
  content jsonb,                      -- schema-validated sections
  basis text,                         -- metadata | abstract | fulltext
  basis_chars int, model text, prompt_version text,
  input_tokens int, output_tokens int, cost_usd numeric,
  created_at
  unique (paper_id, tier, prompt_version)

ingestion_run
  id, source_key, started_at, finished_at, status,
  records_fetched, papers_created, papers_merged,
  errors int, cursor_start, cursor_end
```

### 4.2 User side

```
app_user
  id, email citext unique, password_hash, email_verified_at,
  display_name, created_at, last_active_at

interest_profile
  id, user_id fk unique, updated_at, vector_updated_at

interest_centroid                     -- MULTI-centroid; see §6.2
  id, profile_id fk, label text,      -- "cancer genomics"
  kind text,                          -- topic | keyword | learned
  vector halfvec(768), weight real, source_terms text[]

followed_author   (profile_id, openalex_author_id, display_name)
followed_venue    (profile_id, venue_id)
excluded_topic    (profile_id, term text, openalex_topic_id null)

user_paper_interaction
  id, user_id, paper_id, kind, created_at
  -- kind ∈ impression|open|save|unsave|highly_relevant|relevant
  --        |not_relevant|too_technical|too_basic|already_known
  index (user_id, paper_id, kind)

saved_paper       (user_id, paper_id, saved_at, note null)
search_query      (id, user_id null, q, filters jsonb, results int, created_at)
```

**Deliberately absent:** `Recommendation`, `Author`, `PaperAuthor`, `ResearchField`, `PaperField`, `Source`, `PaperSource`, `PaperVersion`, `CitationRelationship`. See §11.1.

### 4.3 Deduplication algorithm

Runs at step 3 of the pipeline.

```
1. IDENTIFIER MATCH (exact, cheap, ~95% of cases)
   normalise each id → lookup paper_identifier
     doi   : strip scheme/host, lowercase, strip trailing punctuation
     pmid  : digits only
     pmcid : "PMC" + digits
     arxiv : strip version suffix (2401.12345v3 → 2401.12345), lowercase old-style
   any hit → merge into that paper

2. FUZZY MATCH (only when step 1 finds nothing)
   blocking key = first_author_surname + published_year (±1)
                  AND trigram similarity(title_norm) > 0.6      -- pg_trgm GIN index
   confirm with: title similarity ≥ 0.92
                 AND author-surname Jaccard ≥ 0.5
                 AND (no conflicting DOIs)
   → merge; else insert new

3. PREPRINT LINKAGE (does not merge — relates)
   sources: bioRxiv/medRxiv /pubs/ endpoint, OpenAlex locations,
            Crossref relation "is-preprint-of"
   → paper_relation(preprint_of)
   → feed shows ONE row: the published version, badged
     "Published version of a preprint you may have seen"

4. AUDIT
   every merge writes paper_merge(winner_id, loser_id, rule, confidence, at)
   merges are reversible; nothing is hard-deleted
```

Field-precedence on merge (which source wins per field) is declared in a table, not in code branches: abstract prefers PubMed > Europe PMC > OpenAlex; citation counts prefer OpenAlex; dates prefer the *earliest* credible `first_seen_online`.

---

## 5. Semantic representation

### 5.1 Model recommendation: SPECTER2, self-hosted

**SPECTER2** (AllenAI) is pre-trained on scientific literature with citation-based contrastive learning and task adapters. On SciRepEval it beats general-purpose embeddings including OpenAI's — and the general models (E5, Instructor, MPNet) fall behind further still. 768 dimensions, runs on CPU, free.

Alternatives priced for comparison:

| Option | Cost | Notes |
|---|---|---|
| **SPECTER2 self-hosted** | $0 (uses existing CPU) | Best fit for scientific text; ~5–10 min/day for 5k papers with ONNX + batching |
| Google `text-embedding-005` | $0.00625/M tokens | Cheapest hosted |
| Voyage `voyage-3-lite` | $0.010/M | |
| OpenAI `text-embedding-3-small` | $0.020/M ($0.010 batch) | |
| OpenAI `text-embedding-3-large` | $0.130/M | Overkill |

Even the most expensive hosted option costs under $5/month at our volume, so this is a **quality** decision, not a cost one — and the quality answer is SPECTER2. Anthropic does not offer an embeddings endpoint, so this is third-party or self-hosted regardless.

Design the `embed/` package around a provider interface with the model name recorded per row (`paper_embedding.model`), so a model swap is a backfill job, not a migration crisis.

### 5.2 pgvector is sufficient — with one twist

Under ~5M vectors, pgvector HNSW answers in single-digit milliseconds; below ~10M it is faster end-to-end and operationally simpler than a dedicated vector database. We will hold ~1.8M papers/year in scope. **No separate vector database in V1, or plausibly ever.**

Storage arithmetic (768 dims):
- `vector` (float32): 3.0 KB/paper → 5.4 GB per 1.8M papers
- **`halfvec` (float16): 1.5 KB/paper → 2.7 GB per 1.8M papers** ← use this
- HNSW graph adds roughly 15–25% on top

Published RAM figures for pgvector vary wildly between sources; trust the arithmetic above over any blog benchmark, and measure on real data before sizing a machine.

**The twist:** the personalised feed should *not* use ANN at all in V1.

```sql
-- candidate generation is a cheap relational filter, not a vector search
WHERE published_date > now() - interval '21 days'
  AND topics ?| :user_topic_ids
  AND NOT (topics ?| :excluded_topic_ids)
  AND id NOT IN (recently seen)
```

That leaves 2k–50k rows. Exact cosine against ≤5 user centroids over 50k halfvecs is a few tens of milliseconds in Postgres — faster than an ANN probe, exact rather than approximate, and it composes with SQL filters without the recall cliff that filtered-ANN suffers.

Reserve the HNSW index for **semantic search over the whole corpus** (Phase 5+), where the query genuinely is "nearest neighbours across everything".

---

## 6. Recommendation engine

### 6.1 Explicitly not machine learning

V1 is a weighted linear blend with human-readable weights in config. It must be debuggable by reading a row.

### 6.2 Multi-centroid interest profiles

A single averaged interest vector is the standard mistake. A user who follows *oncology*, *machine learning*, and *climate policy* gets a centroid pointing at nothing, and the feed fills with mush that is mildly close to all three and relevant to none.

Instead: one centroid per coherent interest (from each selected topic, each keyword cluster, and later each learned cluster of liked papers).

```
semantic_similarity(paper) = max over centroids c of ( cos(paper.vec, c.vec) * c.weight )
matched_centroid          = argmax   → this is the explanation string
```

Free bonus: `argmax` *is* the "why recommended" reason. No LLM call needed to explain a recommendation, ever.

### 6.3 Score components

| Component | Range | Weight (initial) | Source |
|---|---|---|---|
| `semantic_similarity` | 0–1 | 0.35 | max-over-centroids cosine |
| `topic_overlap` | 0–1 | 0.20 | OpenAlex topic id ∩ followed topics |
| `keyword_match` | 0–1 | 0.10 | tsvector match on user keywords |
| `author_follow` | 0/1 | 0.10 | any author in followed set |
| `venue_follow` | 0/1 | 0.05 | venue in followed set |
| `freshness` | 0–1 | 0.15 | `exp(-age_days / 14)` |
| `quality_prior` | 0–1 | 0.05 | see below |
| **Penalties** | | | |
| excluded topic hit | | `× 0.0` | hard filter, applied before scoring |
| already seen (impression) | | `× 0.6` | decays over 7 days |
| disliked nearest centroid | | `× 0.5` | from `not_relevant` feedback |
| retracted | | `× 0.2` + badge | never hidden entirely |

`quality_prior` is deliberately weak (0.05) and transparent: venue 2-year mean citedness (from OpenAlex `sources`), peer-reviewed vs preprint, and whether the record has a complete abstract. **It is not an impact-factor ranking**, and the weight stays low on purpose — a good preprint should outrank a dull *Nature* paper for the right user.

### 6.4 Presenting relevance

No numbers. Three buckets, thresholded on the blended score, with reasons:

> **Strong match** — matches your interest in *cancer genomics*; uses deep learning; posted 14 hours ago

Rendered from templates keyed on which components contributed most. Deterministic, free, and honest — an LLM-written "why recommended" would be a per-impression cost for strictly worse fidelity.

### 6.5 Feedback → weights, slowly

Store every interaction. In V1 use it in three narrow ways:
1. `not_relevant` on a paper → decrement the weight of its `matched_centroid`.
2. `save` / `highly_relevant` → add the paper's vector as a new learned centroid (or nudge the matched one).
3. `too_technical` / `too_basic` → shift the default summary tier for that user; **do not** touch ranking (there is no reliable paper-difficulty signal yet — pretending otherwise creates a random walk).

Learning-to-rank waits until there are ≥100k labelled interactions. Say so in the docs so future-you doesn't get tempted.

---

## 7. Summarisation & cost control

### 7.1 Tiers

| Tier | Content | Trigger | Model | Cached |
|---|---|---|---|---|
| **0** | Metadata + abstract verbatim | Always, free | none | n/a |
| **1** | 5-question quick summary | First time a paper crosses a relevance threshold in *anyone's* feed, or on first open | Claude Haiku 4.5, batch API | Globally, forever |
| **2** | Deep research-tutor analysis | User clicks "Explain in depth" | Claude Sonnet 5 | **Globally** — see below |

**The critical realisation: Tier 2 is also paper-level, not user-level.** A deep explanation of a given paper is the same for every reader. Cache it globally and the 10,000-user cost collapses to roughly the 1,000-user cost. Only conversational Q&A about a paper (Phase 8) is genuinely per-user.

Tier-1 uses the **Batch API for a flat 50% discount** — summaries are not latency-critical if generated on a trailing schedule (papers ingested at 03:00 get summarised by 05:00, long before anyone opens the app).

### 7.2 Provenance is a schema field, not a UI afterthought

Every `paper_summary` row records `basis ∈ {metadata, abstract, fulltext}` and `basis_chars`. The UI renders it unconditionally:

- *"Summary based on the abstract only. The full text was not available."*
- *"Summary based on the full text (open access, CC-BY)."*

The system must never imply it read a paper it did not read. This is the single most important trust property of the product, and the reason it deserves a NOT NULL column rather than a convention.

### 7.3 Tier-1 schema (structured output)

```json
{
  "what_is_this_about": "string",
  "what_did_they_find": "string",
  "why_it_matters": "string",
  "methods_used": "string",
  "before_you_read": "string",
  "key_terms": [{"term": "string", "plain_meaning": "string"}],
  "confidence_notes": "string"
}
```

Tier-2 extends this with `research_question`, `background`, `data`, `statistics`, `limitations`, `confounders`, `supported_conclusions`, `unsupported_conclusions`, `questions_while_reading`. Every critique field is rendered under a heading that attributes it to the model — *"Points a reader might question"*, never *"Flaws in this paper"*.

---

## 8. V1 scope — exact

### In

- Ingestion from **OpenAlex, arXiv, bioRxiv, medRxiv**; PubMed + Europe PMC land in Phase 2
- Rolling **24-month** corpus, ~1.8M papers/year in covered fields
- Canonicalisation + dedup + preprint linkage
- OA resolution with all locations stored
- Retraction flags
- Public: feed by field, paper detail page, full-text search (title/author/DOI/keyword), OA links
- Accounts: email + password, verification, password reset
- Interest onboarding: topics, keywords, authors, venues, exclusions
- Personalised feed with explainable ranking, sort/filter
- Save, and the six feedback verbs
- Tier-0 always; Tier-1 on threshold; Tier-2 on demand with a per-user monthly quota
- Responsive web UI, light theme
- Observability: ingestion metrics, API error rates, OA hit rate, LLM spend, interaction events

### Out of V1 (build later, design for now)

Email digests · notifications · mobile apps · citation graphs · researcher profiles · collections · collaborative lists · annotations · learning paths · conversational tutor · OAuth login · payments · dark mode · SSR/SEO · semantic search · learning-to-rank · Semantic Scholar · institutional integration

### Explicitly killed for V1: "Trending"

With no users there is no engagement signal, and citation velocity does not exist for a three-day-old paper. Shipping a *Trending* tab means inventing a metric — which the spec itself forbids. Ship instead:

- **New this week in {field}** — pure recency, honest
- **Most-cited open access in {field}** — from OpenAlex `cited_by_count` over a 12-month window, labelled *"most cited in the past year"*, not "trending"

Add real trending in Phase 6, defined as *app opens + saves per paper in 72h, normalised by field volume*, once that signal exists.

---

## 9. Cost model

### 9.1 Assumptions

- In-scope new papers: **~5,000/day ≈ 150,000/month ≈ 1.8M/year**
  (PubMed ~4,100/day · arXiv cs+stat ~400/day · bioRxiv+medRxiv ~165/day · other fields on demand)
- Storage: ~8 KB/paper with indexes → **~14 GB/year**; embeddings (halfvec 768) **~2.7 GB/year**
- Tier-1: 800 input + 450 output tokens. Haiku 4.5 at $1/$5 per MTok = **$0.0031**, or **$0.0015 batched**
- Tier-2: 18k input + 2.5k output. Sonnet 5 at $2/$10 per MTok = **$0.061** (cached globally)
- Embeddings: ~300 tokens/paper → 45M tokens/month → **$0.28–0.90/month hosted, $0 self-hosted**

### 9.2 Monthly totals

| | **100 users** | **1,000 users** | **10,000 users** |
|---|---|---|---|
| Compute (app + workers) | Hetzner CX32 ~$9 | Hetzner CPX41 ~$28 | 2× app + dedicated DB ~$120 |
| Postgres | same box | same box | included above (64 GB box) |
| Object storage + backups | $1 | $2 | $5 |
| Embeddings | $0 (self-hosted) | $0 | $0 |
| Tier-1 summaries | ~3k papers → **$5** | ~20k papers → **$30** | ~80k papers → **$120** |
| Tier-2 deep reads | 60 → **$4** | 500 → **$30** | 3,000 (60% cache hit) → **$75** |
| Email (Resend free → paid) | $0 | $0 | $20 |
| Monitoring (Sentry free tier) | $0 | $0 | $0–26 |
| Domain (amortised) | $1 | $1 | $1 |
| **Total** | **≈ $20–25/mo** | **≈ $90–110/mo** | **≈ $340–370/mo** |
| **Per user/month** | $0.22 | $0.10 | $0.036 |

### 9.3 The ceiling, and why it matters

If *every* in-scope paper got a Tier-1 summary: 150k × $0.0015 = **$225/month, flat, regardless of user count**. That is the absolute worst case for the dominant LLM line item, and it does not grow with users. The same is true of ingestion, embeddings, and storage.

This is the single most important economic property of the design: **beyond ~10k users, marginal cost per user approaches the cost of serving a web page.** A free tier is genuinely sustainable. What is *not* free is the fixed ~$300–400/month floor at scale — plan for donations, a grant, or a paid tier before crossing it, not after.

### 9.4 Cost controls to build in from day one

1. Hard monthly LLM spend cap in config; the summariser refuses past it and logs loudly.
2. Per-user Tier-2 quota (suggest 10/month free), enforced server-side.
3. Every LLM call writes `cost_usd` to `paper_summary` — the spend dashboard is a `SUM()`, not a vendor console.
4. Batch API by default for anything not user-blocking.
5. Prompt caching on the shared system prompt + schema (stable prefix, volatile paper text last).
6. Never call an LLM in a feed-serving code path. Not once. Enforce with a test.

---

## 10. Hosting & deployment

### 10.1 Recommendation: Hetzner + Docker Compose + Cloudflare

| Layer | Choice | Cost | Why |
|---|---|---|---|
| App + workers + DB | **Hetzner Cloud CX32** (4 vCPU / 8 GB / 80 GB) | ~€8/mo | Best price/performance available; NVMe; EU jurisdiction |
| Postgres | Self-managed 17 + pgvector, in Compose | included | Free tiers (Neon 0.5 GB, Supabase 500 MB) are ~30× too small — we hit 14 GB in year one |
| Reverse proxy / TLS | Caddy | $0 | Automatic certificates |
| Frontend | **Cloudflare Pages** | $0 | Free static hosting + global CDN |
| DNS / WAF | Cloudflare | $0 | |
| Backups | `pg_dump` + WAL archive → Backblaze B2 or Cloudflare R2 | ~$1–5/mo | R2 has no egress fees |
| Email | Resend (3k/mo free) | $0 → $20 | |
| Errors | Sentry free tier | $0 | |
| CI/CD | GitHub Actions → GHCR → SSH `compose pull && up -d` | $0 | |

**Scale path:** CX32 → CPX41 (vertical, ~5 min downtime) → split DB onto a Hetzner dedicated AX41/AX52 (64 GB RAM, ~€55/mo) with app nodes behind a load balancer. Equivalent AWS RDS compute runs $800+/month, which is the whole argument.

### 10.2 Alternatives considered

- **Fly.io / Railway / Render** — genuinely less ops, and a fair choice if you would rather write features than run a box. Expect 3–5× the cost at equivalent resources, and managed Postgres with 50 GB gets expensive fast.
- **Supabase** — attractive because it bundles Postgres + Auth + storage. Rejected as the primary DB: the free tier is 500 MB, and paid plans price disk in a way that fights a 14 GB/year corpus. Still a reasonable choice for **Auth alone** if you do not want to own that.
- **Neon** — genuinely always-free tier, scale-to-zero, and storage dropped to $0.35/GB-month post-acquisition. Good for a staging environment; wrong for a workload with a continuously-running ingestion worker (scale-to-zero never triggers).

### 10.3 Authentication: `fastapi-users`, self-hosted

The spec says "do not build authentication insecurely from scratch". Correct — but "don't hand-roll" and "buy a SaaS" are not the only two options.

| Option | Cost at 10k MAU | Cost at 100k MAU | Verdict |
|---|---|---|---|
| **`fastapi-users` self-hosted** | $0 | $0 | **Recommended** |
| Supabase Auth | $0 | ~$187/mo | Good fallback |
| Clerk | $0 (under 50k MRU) | ~$1,025–1,825/mo | Free-tier trap |

`fastapi-users` is a mature library handling registration, verification, password reset, JWT/cookie sessions, and OAuth — with Argon2 hashing and SQLAlchemy integration. It is not "from scratch"; it is the FastAPI-native equivalent of Devise or Django's auth.

Clerk is specifically wrong for this product: a **free public app accumulates a large population of low-value accounts**, which is exactly the shape that per-MAU pricing punishes, and it puts user data in a vendor's US database. Supabase Auth's $0.00325/MAU is far gentler if you want to outsource, but self-hosting costs nothing and keeps the data in your Postgres next to `interest_profile`.

Non-negotiables either way: Argon2id, email verification before personalisation, rate-limited login, short-lived access tokens with rotating refresh tokens, secrets from environment only, and no PII beyond email + display name.

---

## 11. Where I disagree with the specification

Asked for directly, so — directly:

### 11.1 The data model is over-normalised, and one table is a trap

- **`Recommendation` as a stored table is the trap.** Persisting a row per (user × paper) recommendation means 10,000 users × 100 feed items/day = **1M rows/day** of write amplification, for data that is stale within hours. Compute the feed at request time (it is a filtered scan plus a dot product — tens of milliseconds) and persist only the *impressions you will actually analyse*, sampled.
- **`Author` + `PaperAuthor` in V1 is a large hidden project.** Author name disambiguation is a research problem in its own right. V1 should store authors as JSONB on `paper` (fast to render, no joins) and keep a real author table **only for authors somebody follows**, keyed on OpenAlex author IDs, which are already disambiguated for free. Full author entities can come in Phase 8 with researcher profiles.
- **`Source` / `PaperSource` / `ResearchField` / `PaperField` are premature.** Source provenance lives in `source_record` (which you want anyway, as a raw audit trail). Fields/topics are OpenAlex topic IDs in a JSONB array with a GIN index — a join table buys nothing when the taxonomy is externally owned and read-only.
- **`PaperVersion` and `CitationRelationship` should wait.** `paper_relation` covers versioning for V1; citation graphs are Phase 8 and would multiply row counts by ~40×.

Net: ~14 tables instead of ~22, and the difference is entirely in things that would have been maintained but unused.

### 11.2 Open-access resolution belongs in Phase 1, not Phase 4

OA status arrives *free, in the same JSON payload*, from OpenAlex at ingest time. Deferring the resolver to Phase 4 means either re-running ingestion over the whole corpus later, or shipping Phases 2–3 with a feed that cannot answer "can I actually read this?" — which is a top-three user question and one of the product's clearest differentiators. Move the resolver into Phase 1 (OpenAlex fields) and Phase 2 (Unpaywall/Europe PMC fallbacks).

### 11.3 "Trending" should not ship in V1 at all

Covered in §8. The spec correctly says not to invent a metric, then lists four trending sections. Those are inconsistent. Ship honest recency and honest citation counts under honest labels.

### 11.4 Domain-neutral architecture, domain-focused launch

"Do not hardcode any one scientific domain" is right as an *architectural* constraint and wrong as a *launch* strategy. Being equally mediocre across 30 fields on day one produces a feed nobody trusts. Biomedicine and CS/ML have by far the richest free infrastructure (PMC open-access full text, MeSH, Europe PMC annotations, arXiv same-day, bioRxiv/medRxiv), which means those two fields can have genuinely good summaries and full-text coverage while everything else gets abstracts.

Recommendation: schema and connectors stay domain-general; **marketing, onboarding defaults, and quality investment focus on biomedicine + CS/ML for V1.** No hardcoding — a user can still follow economics on day one, they just get a thinner experience, honestly labelled.

### 11.5 "Why recommended" must not be LLM-generated

The spec puts an AI explanation on every feed card. Even at Haiku prices, an LLM call per impression is the one thing that makes cost scale linearly with users — precisely what the spec elsewhere forbids. Template it from the winning score components (§6.4). Deterministic, free, more accurate, and instantly debuggable.

### 11.6 The relevance score should not be shown as a number at all

The spec says avoid fake precision like "93.427%" — agreed, and I would go further: **show no number.** Any numeric score invites users to compare values that are not calibrated and not comparable across profiles. Three labelled buckets plus reasons convey everything actionable and promise nothing false.

### 11.7 SPA vs SEO is a decision that must be made consciously now

The spec says "SEO may matter later" and picks a Vite SPA. Those are in tension: an SPA gets essentially zero organic traffic on paper pages, and paper pages are the only content with long-tail search demand. Two honest options:

- **(a) SPA now, prerender later.** Keep `GET /papers/{id}` returning everything needed for a full page render, then add a prerender worker or a thin SSR shell for `/papers/*` in Phase 2.5. Costs a few days later.
- **(b) SSR framework from the start.** More scaffolding, slower V1.

**Recommendation: (a)** — but decide it now and write the constraint into the API design, because retrofitting SSR onto an API that assumes an authenticated client is the expensive version of this.

**One more, minor:** the standing 80% coverage rule is right for normalisation, deduplication, ranking, auth and summary schema validation — and close to meaningless for connector HTTP glue, which is better served by recorded-fixture contract tests. Aim for 80% overall with those subsystems well above it, rather than padding connector coverage to hit a number.

---

## 12. Risks

| # | Risk | Severity | Mitigation |
|---|---|---|---|
| 1 | **Cold-start relevance** — feed feels random on day 1, user never returns | **High** | Onboard with concrete topics mapped to OpenAlex topic IDs (not free text alone); show the feed *during* onboarding so picks have visible effect; seed centroids from 2–3 example papers per topic |
| 2 | **OpenAlex dependency** — Feb 2026 introduced keys + credits; terms can change again | **High** | Register a key immediately; mirror the S3 snapshot quarterly; keep the connector interface strict so Crossref can substitute for core metadata |
| 3 | **Dedup errors are user-visible** — duplicates look sloppy, bad merges look broken | **High** | Conservative thresholds (favour duplicates over wrong merges); every merge audited and reversible; a "report a problem" affordance on paper pages |
| 4 | **Abstract-only summaries mislead** — user believes the model read the paper | **High** | `basis` is NOT NULL; provenance rendered unconditionally; no full-text framing when only the abstract was seen |
| 5 | **Rate-limit ban** from NCBI or arXiv | Medium | Shared token-bucket per source; registered `tool`/`email`; off-peak windows; exponential backoff; alert on 429s |
| 6 | **LLM cost overrun** from a tier-policy bug | Medium | Hard monthly cap in config; per-user quotas; `cost_usd` on every row; alert at 50%/80% of cap |
| 7 | **pgvector RAM growth** past ~5M vectors | Medium | `halfvec` from day one; embed only the rolling 24-month window; archive older vectors; measure before sizing |
| 8 | **Medical misinformation liability** — clinicians are a named audience | Medium | Never advisory framing; retraction badges above summaries; visible AI labelling; published correction process |
| 9 | **Solo maintainer scope** — the spec contains ~20 subsystems | **High** | The phase plan below is sequenced so each phase is independently shippable and useful; do not start Phase N+1 before Phase N is deployed |
| 10 | **No distribution plan** — a good feed nobody finds | Medium | Decide SEO stance now (§11.7); the public paper pages are the acquisition surface |

---

## 13. Phased implementation plan

Estimates assume one developer working steadily, not full-time.

| Phase | Deliverable | Key work | Est. |
|---|---|---|---|
| **0** | *This document* | — | done |
| **1** | **Ingestion MVP** — papers land in Postgres, deduplicated, with OA status | Repo scaffold, Compose, Alembic; `paper`/`identifier`/`source_record`/`oa_location`/`venue` schema; connector protocol; OpenAlex + arXiv OAI + bioRxiv/medRxiv; normalise + canonicalise + dedup; OA fields from OpenAlex; jobs table + cron; ingestion metrics; fixture-based tests | 2–3 wks |
| **2** | **Public web** — anyone can browse and search | React/TS/Vite + TanStack Query; feed by field; paper detail; full-text search (tsvector + trigram); responsive layout; public read API; PubMed + Europe PMC connectors; Unpaywall fallback; Retraction Watch nightly | 2–3 wks |
| **3** | **Accounts + personalisation** — the actual product | `fastapi-users`; onboarding (topics/keywords/authors/venues/exclusions); SPECTER2 embedding worker; multi-centroid profiles; hybrid ranking; templated explanations; feed sort/filter | 2–3 wks |
| **4** | **Feedback loop** *(moved earlier — it is cheap and it is what makes Phase 3 improve)* | Save; six feedback verbs; centroid weight updates; impression tracking; "not interested" suppression | 1 wk |
| **5** | **AI summaries** | Provider abstraction; Tier-1 batch worker with threshold policy; Tier-2 on demand with quota; structured-output schemas; provenance; injection-safe assembly; cost accounting + caps | 2 wks |
| **6** | **Polish + launch readiness** | Dark mode; SEO/prerender decision executed; error pages; rate limiting; backups verified by restore drill; Sentry; docs; landing page | 1–2 wks |
| **7** | **Email digest** | Resend integration; daily/weekly cadence; unsubscribe; digest ranking reuse | 1 wk |
| **8** | **Advanced** | Semantic search (HNSW); real trending metric; citation graph; conversational tutor; learning-to-rank; Semantic Scholar enrichment; mobile client | ongoing |

**Two changes from the spec's ordering:** OA resolution folded into Phases 1–2 (§11.2), and the feedback loop moved ahead of AI summaries — feedback makes the ranking better and costs nothing, while summaries are the most expensive and least differentiating piece. A product that recommends well without AI summaries is viable; the reverse is not.

---

## 14. Documentation plan

To be written alongside the phases, not at the end:

```
README.md                 setup, run, test
docs/
  phase-0-report.md        this file
  product.md               concept, users, V1 scope, non-goals
  architecture.md          modules, pipeline, job queue, deployment topology
  data-model.md            schema, dedup rules, field precedence
  sources.md               per-connector: endpoints, limits, quirks, fixtures
  ingestion.md             pipeline stages, cursors, backfill, replay
  open-access.md           resolution chain, licence policy, storage rules
  recommendation.md        centroids, features, weights, explanations
  summarisation.md         tiers, schemas, provenance, injection defence
  security.md              auth, secrets, threat model, PII policy
  legal.md                 what we store and why, takedown process
  cost-model.md            unit economics, caps, live spend
  deployment.md            infra, CI/CD, backup + restore drill
  adr/                     one file per architectural decision
  roadmap.md               phases and their exit criteria
```

---

## 15. What I need from you to start Phase 1

1. **Approve or amend §11** — the seven disagreements, especially the data-model trim and moving OA into Phase 1.
2. **Confirm launch fields** — biomedicine + CS/ML focus (§11.4), or genuinely uniform coverage?
3. **Confirm the SEO stance** (§11.7) — (a) SPA-then-prerender, or (b) SSR from the start?
4. **Confirm auth** — self-hosted `fastapi-users`, or Supabase Auth?
5. **Confirm hosting** — Hetzner + Compose, or a PaaS for less ops at ~3× cost?
6. **Register accounts** (all free, all needed before Phase 1 ends): OpenAlex API key, NCBI API key + registered tool/email, Unpaywall email, and a contact email for `User-Agent` headers.
7. **Confirm the working name** — `Academious` is used throughout; trivial to change now, annoying later.

---

## Sources

- [OpenAlex — rate limits & authentication](https://github.com/ourresearch/openalex-docs/blob/main/how-to-use-the-api/rate-limits-and-authentication.md) · [API keys required from Feb 13 announcement](https://groups.google.com/g/openalex-users/c/rI1GIAySpVQ)
- [Crossref — announcing changes to REST API rate limits](https://www.crossref.org/blog/announcing-changes-to-rest-api-rate-limits/) · [Retraction Watch documentation](https://www.crossref.org/documentation/retrieve-metadata/retraction-watch/)
- [NCBI E-utilities usage guidelines](https://www.ncbi.nlm.nih.gov/books/NBK25497/)
- [Europe PMC developers](https://europepmc.org/developers)
- [arXiv API terms of use](https://info.arxiv.org/help/api/tou.html)
- [bioRxiv/medRxiv API](https://api.biorxiv.org/)
- [Unpaywall FAQ](https://unpaywall.org/faq)
- [Semantic Scholar Academic Graph API](https://api.semanticscholar.org/api-docs) · [release notes](https://github.com/allenai/s2-folks/blob/main/API_RELEASE_NOTES.md)
- [SPECTER2 (AllenAI)](https://allenai.org/blog/specter2-adapting-scientific-document-embeddings-to-multiple-fields-and-task-formats-c95686c06567) · [model card](https://huggingface.co/allenai/specter2)
- [pgvector performance benchmarks](https://www.instaclustr.com/education/vector-database/pgvector-performance-benchmark-results-and-5-ways-to-boost-performance/) · [pgvector index guide (Mar 2026)](https://www.dbi-services.com/blog/pgvector-a-guide-for-dba-part-2-indexes-update-march-2026/)
- [Embedding model specs & pricing 2026](https://pecollective.com/tools/text-embedding-models-compared/) · [OpenAI embedding pricing](https://tokenmix.ai/blog/openai-embedding-pricing)
- [Managed PostgreSQL comparison 2026](https://selfhost.dev/blog/managed-postgresql-comparison-2026/) · [PostgreSQL hosting pricing comparison](https://www.bytebase.com/blog/postgres-hosting-options-pricing-comparison/)
- [Authentication pricing comparison — Clerk / Auth0 / Supabase](https://www.buildmvpfast.com/api-costs/authentication)
- Claude model pricing: Anthropic first-party API rates (Haiku 4.5 $1/$5, Sonnet 5 $2/$10, Opus 5 $5/$25 per MTok; Batch API −50%)

---

## 16. Decisions taken (2026-08-28)

Phase 0 was accepted with the following decisions. They supersede the
recommendations above wherever they differ.

| # | Decision | Detail |
|---|---|---|
| 2 | **Launch domains** | Biomedicine / life sciences, and computer science / AI / ML. Architecture stays domain-neutral; only the configured filters are narrowed. |
| 3 | **SEO** | React/Vite SPA with prerendered, indexable public pages. Paper pages get stable canonical URLs, titles, descriptions, canonical tags, OpenGraph, scholarly structured data and a sitemap. No migration to an SSR framework without a material architectural reason. |
| 4 | **Auth** | Public browsing never requires an account. Authentication gates personalisation only. `fastapi-users` confirmed after re-verification - see ADR 0005. |
| 5 | **Hosting** | Hetzner VPS + Docker Compose. Reverse proxy, frontend, FastAPI, PostgreSQL + pgvector, one background worker. No Redis, no Celery, no Kubernetes, no standalone vector database. PostgreSQL `SKIP LOCKED` for jobs. **Encrypted off-machine backups designed from the start** - see `deployment.md`. |

All seven disagreements in section 11 were accepted, along with OpenAlex as the
spine, preprint linkage via bioRxiv, Retraction Watch integration, OA resolution
during ingestion, paper-level global caching, request-time recommendations,
templated explanations, relevance buckets, no Trending in V1, pgvector with
`halfvec`, SPECTER2, the reduced schema, and no local Author entity.

The processing hierarchy was restated as four tiers (metadata / embedding /
canonical short explanation / deep analysis) and the cost question was reworked
from first principles in [cost-model.md](cost-model.md), which supersedes
section 9 of this document.

## 17. Corrections from Phase 1 measurements

Phase 1 contact with the live APIs corrected three things asserted above.

1. **§9.1 volume is too low for arXiv.** A single OAI-PMH request for
   `set=cs`, 2026-08-18, returned **1,300 records for that one day** - roughly
   39,000/month against the 11,000/month assumed. The OAI window filters on
   *datestamp*, so this includes metadata updates to existing papers rather than
   new submissions only, but it is the volume the pipeline actually processes.
   Re-derive the cost model from `ingestion_run` counters after a week of real
   harvesting.

2. **§2 "has an abstract" cannot be an ingestion filter.** Live OpenAlex records
   for published journal articles frequently have no `abstract_inverted_index`
   at all - both integron fixtures demonstrate it. Requiring an abstract would
   silently discard a large share of the biomedical corpus. Abstract coverage is
   now a metric, not a gate.

3. **§4.3 arXiv-to-OpenAlex matching is weaker than assumed.** OpenAlex does not
   expose arXiv ids as identifiers; the only link is an `arxiv.org` URL on a
   location record. Papers predating arXiv's DOI assignment have no shared DOI
   either, and OpenAlex has begun minting an opaque `10.65215/...` prefix that
   cannot be derived from the arXiv id. Cross-source matching for arXiv content
   therefore leans on the fuzzy title-and-author path more heavily than the
   identifier path - which is why that path exists.

One deliberate deviation: `title_norm` does **not** strip stopwords, contrary to
the sketch in §4.1. Scientific titles are short, and removing `of`/`the`/`in`
degrades trigram similarity on exactly the short titles where deduplication is
hardest.
