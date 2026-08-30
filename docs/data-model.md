# Data Model

Eleven tables in Phase 1. Deliberately fewer than the Phase 0 specification
proposed; the reasoning is in `phase-0-report.md` section 11.1 and ADR 0003.

## Tables

| Table | Purpose |
|---|---|
| `paper` | The canonical record. One row per distinct work. |
| `paper_identifier` | `(id_type, value)` primary key. The deduplication substrate. |
| `paper_relation` | Typed edges: `preprint_of`, `version_of`, `corrects`, `retracts`. |
| `paper_merge` | Audit of every merge. Merges are reversible. |
| `oa_location` | Every discovered legal location for a paper; one is `is_best`. |
| `venue` | Journals, conferences, preprint servers. |
| `source_record` | Immutable raw payload per `(source_key, source_id)`. Enables replay. |
| `retraction_record` | Retraction Watch notices. A paper may have several. |
| `ingestion_run` | One row per source per run. The ingestion metrics store. |
| `source_cursor` | Where each source got to, so the next run is incremental. |
| `job` | `SKIP LOCKED` work queue. |
| `paper_embedding` | One vector per `(paper, model_key)`. `halfvec(768)`, plus `source_updated_at` — the paper version the vector was built from, which is what staleness is decided against. See [embeddings.md](embeddings.md). |

`paper` additionally carries `search_tsv`, a stored generated `tsvector` over
title (weight A), keywords and topic labels (B) and abstract (C). It is
generated rather than trigger-maintained so it cannot drift from its row.

Absent by design: `Recommendation`, `Author`, `PaperAuthor`, `ResearchField`,
`PaperField`, `Source`, `PaperSource`, `PaperVersion`, `CitationRelationship`.

Still absent after Phase 2: any per-user table. An embedding does not depend
on who is asking, so it is stored once globally; personalisation changes
*which* vectors a user is compared against, not how many copies exist.

## Authors are denormalised

`paper.authors` is JSONB: `[{name, position, orcid, openalex_id, affiliations}]`.

Author name disambiguation is a research problem in its own right, and OpenAlex
already solves it upstream and exposes stable author ids. A local `Author` entity
arrives only when a feature needs one - following an author, in Phase 3 - and
then it will be keyed on the OpenAlex id rather than re-solving disambiguation.

`paper.first_author_surname` is extracted at write time purely as a
deduplication blocking key.

## Identifier normalisation

`core/ids.py` is the sole authority. Every identifier is reduced to one canonical
form before storage or comparison:

| Type | Canonical form | Example |
|---|---|---|
| `doi` | bare, lowercase | `https://doi.org/10.1038/S41564-023-01548-Y` → `10.1038/s41564-023-01548-y` |
| `pmid` | digits only | `https://pubmed.ncbi.nlm.nih.gov/38172619` → `38172619` |
| `pmcid` | `PMC` + digits | `7255293` → `PMC7255293` |
| `arxiv` | version stripped | `arXiv:1706.03762v5` → `1706.03762` |
| `openalex` | bare id, uppercase | `https://openalex.org/W4390571678` → `W4390571678` |

Every normaliser returns `None` rather than guessing. A best-effort guess would
create false merges, which are much worse than misses.

arXiv version suffixes are dropped deliberately: v1 and v3 of a preprint are the
same paper for discovery purposes.

## Title normalisation

`core/text.normalise_title` produces the fuzzy-match key: HTML entities and tags
removed, LaTeX commands stripped, editorial prefixes such as `RETRACTED:`
removed, accents folded, case folded, everything non-alphanumeric collapsed to
single spaces.

**Stopwords are not removed**, a deliberate deviation from the Phase 0 sketch.
Scientific titles are short, and dropping `of`/`the`/`in` measurably degrades
trigram similarity on exactly the short titles where deduplication is hardest.

## Deduplication

```
1. IDENTIFIER MATCH                      (exact; the large majority of records)
   normalise every identifier, look up paper_identifier
   several papers matched, none conflicting  -> merge them
   several papers matched, DOIs conflict     -> keep separate, log the conflict

2. FUZZY MATCH                           (only when step 1 finds nothing)
   block:   first_author_surname AND published_year +/- 1
            AND title_norm % title_norm            (pg_trgm GIN index)
   confirm: similarity(title_norm) >= 0.92
            AND author-surname Jaccard >= 0.50
            AND no conflicting DOIs
   titles shorter than 12 characters never fuzzy-match

3. PREPRINT LINKAGE                      (relates, never merges)

4. AUDIT
   every merge writes paper_merge(winner, loser, rule, confidence, details)
```

Thresholds are configurable (`dedup_*` settings) and deliberately conservative.
A missed merge shows a duplicate, which is untidy. A wrong merge destroys a
distinct paper and is very hard to notice afterwards.

### Why conflicting DOIs are decisive

Two distinct DOIs mean two distinct records, always. This is what keeps a
preprint and its published version apart even when a source links them through a
shared arXiv id or a near-identical title.

That case is not hypothetical. Verified against live OpenAlex data: the bioRxiv
preprint `10.1101/2022.09.11.507474` ("A new route for integron cassette
dissemination among bacterial genomes", work `W4296130942`) and its published
version `10.1038/s41564-023-01548-y` ("Integron cassettes integrate into
bacterial genomes via widespread non-classical attG sites", work `W4390571678`)
are separate OpenAlex works **with different titles**. No title matching would
ever link them, and no identifier is shared. Only the bioRxiv publication map
connects them.

## Field precedence on merge

Declared as data in `ingest/merge.py`, not as branches:

| Field | Precedence |
|---|---|
| Abstract | PubMed > Europe PMC > OpenAlex > bioRxiv > arXiv; ties break toward the longer text |
| Title | OpenAlex > PubMed > bioRxiv > arXiv |
| Venue, topics | OpenAlex > PubMed > bioRxiv > arXiv |
| Citation count | OpenAlex only - it is the only source that computes them globally |
| `first_seen_online` | Earliest across all sources |
| `is_peer_reviewed` | Sticky: true once **any** source reports it |
| `is_preprint` | Cleared once a peer-reviewed version is known |
| `oa_status` | Only improves: `unknown < closed < bronze < green < hybrid < gold < diamond` |
| Topics, keywords | Union, keyed by `(scheme, id)`, so arXiv categories and OpenAlex topics coexist |

## Retraction status

`retraction_status` is resolved by **severity across all notices** for a paper,
never last-write-wins:

```
retracted (3) > concern (2) > corrected (1) > none (0)
```

Verified against the live dataset: `10.1016/s0140-6736(20)31180-6` carries three
notices - a correction, an expression of concern, and a retraction - and must
resolve to `retracted`.

## Indexes that matter

| Index | Why |
|---|---|
| `ix_paper_title_norm_trgm` (GIN, `gin_trgm_ops`) | Fuzzy dedup blocking; without it every candidate is a sequential scan |
| `ix_paper_dedup_block` (`first_author_surname`, `published_year`) | Narrows the fuzzy candidate set before similarity runs |
| `pk_paper_identifier` (`id_type`, `value`) | The exact-match dedup path |
| `uq_source_record_source_id` | Idempotency: one stored record per source id |
| `ix_job_claim` (`status`, `priority`, `run_after`) | `SKIP LOCKED` claim query |
| `ix_paper_search_tsv` (GIN) | Lexical retrieval; without it every query is a sequential scan |
| `ix_paper_embedding_model_paper` (`model_key`, `paper_id`) | The anti-join that finds papers still needing an embedding |

There is deliberately **no ANN index** on `paper_embedding.embedding`. See
[ADR 0007](adr/0007-halfvec-and-exact-search-first.md).
