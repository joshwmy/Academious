# Ingestion

## Stages

1. **Harvest** - `connector.harvest(since, cursor)` yields pages of `RawRecord`.
   The only code that touches the network. Rate-limited per source.
2. **Store raw** - each payload is written to `source_record`, keyed
   `(source_key, source_id)`, with a SHA-256 content hash. Immutable; enables replay.
3. **Normalise** - `connector.normalise(raw)` returns a `PaperCandidate` or
   `None` for out-of-scope records. Pure function.
4. **Canonicalise** - identifier match, then fuzzy match, then insert. See
   [data-model.md](data-model.md).
5. **Enrich** - identifiers synced, venue upserted, field precedence applied, OA
   locations stored and a best elected, preprint relations created.
6. **Record** - `ingestion_run` counters written, cursor advanced.

## Ingestion filters

A record is skipped at normalisation when it has no title, no resolvable
identifier, or a work type that is not research output (`paratext`, `editorial`,
`letter`, `erratum`, `grant`, `dataset`, `peer-review`).

A Europe PMC window can be dominated by one journal supplement: the first live
harvest rejected 445 conference abstracts out of 500 records, all from two
supplement issues. That is the filter working, but it means a `--max-records`
cap bounds *records fetched*, not papers gained.

Europe PMC labels a record with both MEDLINE and JATS publication types, and
the two disagree often enough to matter, so scope there is decided by looking
for a research type first and only then for an excluded one. A **retraction
notice** is excluded; the **retracted article** it refers to is kept and
flagged, because the paper is still the record of what was claimed.

**An abstract is not required.** Live OpenAlex data shows many published journal
articles with no abstract; requiring one would silently discard a large fraction
of the biomedical corpus. Abstract coverage is instead a metric to watch.

## Idempotency

Idempotency is a property of the pipeline, not an accident.

Before any work is done, the incoming payload is hashed and compared with the
stored `source_record` for that `(source_key, source_id)`. If the hash is
unchanged, the record is counted as skipped and nothing else happens - no
deduplication query, no merge, no write.

Consequences:

* Re-running a harvest is cheap and safe.
* An interrupted harvest is recovered by simply running it again.
* Replaying an entire window produces zero new papers and zero new source
  records, which `scripts/demo_phase1.py` section 7 demonstrates.

## Cursors

`source_cursor` stores where each source got to.

**A failed run does not advance the cursor.** If a source dies mid-harvest, the
next run retries the same window rather than skipping past records that were
never fetched. A run that completes with per-record errors *does* advance -
those records were seen, and their failures are recorded in
`ingestion_run.detail.error_samples`.

Cursor semantics differ by source:

| Source | Cursor |
|---|---|
| OpenAlex | opaque `next_cursor` from `meta`; belongs to one filter expression |
| arXiv | OAI-PMH `resumptionToken`; must be sent alone, with no other arguments |
| bioRxiv | the window end date; the next run starts there |
| Europe PMC | `queryfingerprint`&#124;`start`&#124;`end`&#124;`cursorMark`. Discarded when the query or the window moves; an empty mark means that window finished |

## Failure handling

Three levels, so one bad thing never escalates:

* **One bad record** - caught, counted, logged, and the run continues. Up to ten
  error samples are stored on the run.
* **A source outage** - the run is marked `failed`, everything already ingested
  is kept and committed, and the cursor is not advanced.
* **Rate limiting** - the token bucket is penalised for the whole process, so a
  `Retry-After` is respected by every subsequent request to that source, not
  only the one that received it.

A run ends `succeeded` (no errors), `partial` (some record errors) or `failed`
(the source itself failed).

## Preprint linking

Two paths, both idempotent:

1. During ingestion, when a bioRxiv/medRxiv record carries a `published` DOI.
2. Via `python -m academious.workers link-publications`, which walks the
   `/pubs/` endpoint and links pairs where both papers are already present.

Linking creates a `paper_relation(preprint_of)` edge and marks the published
version as peer reviewed and no longer a preprint. It never merges the two rows.

Papers whose counterpart has not been ingested yet are simply not linked; a later
run picks them up once both exist.

## Running it

```bash
python -m academious.workers harvest --source all
python -m academious.workers harvest --source openalex --since 2026-08-01 --max-records 500
python -m academious.workers harvest --source arxiv --no-cursor
python -m academious.workers harvest --source europepmc --since 2026-08-01
python -m academious.workers retractions
python -m academious.workers link-publications --since 2026-08-01
```

`--max-records` caps a run, which is the safe way to try a new source or filter
against a live API without spending a day's quota.

## Metrics

Every run writes one `ingestion_run` row:

| Column | Meaning |
|---|---|
| `records_fetched` | raw records seen |
| `records_skipped` | unchanged since last run, or filtered out at normalisation |
| `papers_created` / `papers_updated` | new rows, and existing rows a source changed |
| `papers_merged` | duplicates folded together |
| `relations_created` | preprint links made |
| `oa_locations_created` | legal locations discovered |
| `errors`, `detail.error_samples` | per-record failures, with up to ten samples |
| `cursor_start`, `cursor_end` | the window covered |

Available at `GET /metrics/ingestion`.
