# ADR 0009: one subject vocabulary, derived and stored per paper

**Status:** Accepted (Phase 2, feed by field)

## Context

`SearchFilters.fields` has existed since Phase 2's retrieval work and was never
exposed, because it matched `topics[].field` — a key only OpenAlex records
carry. On the deployed corpus of 102,948 papers that is a filter over 43% of the
rows:

| Source | Papers | What it classifies with |
|---|---|---|
| OpenAlex | 44,777 | topic hierarchy; `field` is its middle level (26 values) |
| Europe PMC | 48,160 | MeSH descriptors, on roughly 45% of its records |
| arXiv | 10,131 | archive categories, `cs.LG`, `q-bio.NC`, `hep-th` |
| bioRxiv / medRxiv | 2,103 | one free-text category, `neuroscience`, `public and global health` |

(The columns sum past the total because 2,223 papers were seen in more than one
source.)

Passing any one vocabulary through would have shipped a filter whose recall
depends on which connector happened to find a paper. A reader selecting
"Computer Science" would see OpenAlex's computer science and not arXiv's, with
nothing on the page to say so. That is worse than having no field filter: it
looks like a complete answer.

Three sub-decisions had to be made together — which vocabulary, where the
mapping runs, and what happens to papers it cannot classify.

## Decision

### The vocabulary is OpenAlex's 26 fields

Not because it is the best taxonomy available, but because it is already the
largest one in the corpus, it is stable, its members have ids, and it spans
physics and dentistry in one flat list of a browsable size. `FIELDS` in
[`ingest/taxonomy.py`](../../src/academious/ingest/taxonomy.py) is a
transcription of `api.openalex.org/fields`, each entry carrying the slug the API
accepts, the label a reader sees, and the upstream id so the list can be
re-derived rather than trusted.

### Every other source is mapped onto it, coarsely and on purpose

* **arXiv** maps by archive prefix — all of `cs.*` is Computer Science — with a
  short override table for the subcategories where the archive would actively
  mislead (`q-bio.NC` is Neuroscience, `stat.ML` is Computer Science,
  `physics.med-ph` is Medicine).
* **bioRxiv and medRxiv** map by category label, from a table covering all 70
  labels observed in the deployed corpus plus the medRxiv categories that had
  not yet appeared in it.
* **OpenAlex** passes its own field name through.

Coarse is the point. `cs.LG` and `cs.DB` are both Computer Science, and a
mapping that tried to be finer would be inventing precision the source
vocabularies do not carry. A field facet is a browsing aid, not a classification
system.

### MeSH is not mapped

Europe PMC supplies the MeSH *descriptor term* and not its tree number, so there
is no hierarchy to climb — mapping "Neoplasms" to a field would mean shipping
the MeSH descriptor file and a term-to-tree index to answer a question the facet
does not really ask. MeSH is also biomedical-only: mapped, it would put nearly
every Europe PMC paper into Medicine and make that field mean "came from Europe
PMC".

So a paper classified only in MeSH carries no field. **This is stated rather than
hidden**: `unmapped_topics()` reports it, the backfill counts it, `GET /fields`
returns `papers_without_field`, and the filter UI says how many papers selecting
a field will hide.

### Fields are derived into a stored column, not resolved at query time

The mapping tables live in Python. Resolving them in SQL would mean shipping
them into the database and joining per row. `paper.fields text[]` (migration
0004, GIN-indexed) holds the result, filtering is one `&&` overlap, and the
column is recomputed from `paper.topics` on every ingestion pass — so a mapping
change reaches a paper the next time any source describes it, and
[`scripts/backfill_fields.py`](../../scripts/backfill_fields.py) re-derives the
whole corpus on demand.

The derived column is not authoritative. `topics` remains the record of what
each source said; `fields` is an index over it that can be thrown away and
rebuilt.

### An unknown field slug is a 422

`GET /papers?field=compter-science` is refused rather than ignored or answered
with an empty page. Ignoring it answers a filtered request with an unfiltered
one; an empty page makes a typo indistinguishable from a field nothing is
published in. The frontend drops unrecognised slugs while parsing the URL, so a
hand-edited link degrades to an unfiltered feed rather than an error page.

## Consequences

* One filter reaches every source. An arXiv `cs.LG` preprint, an OpenAlex record
  whose field is Computer Science, and a bioRxiv `bioinformatics` preprint are
  each reachable from the field a reader would look under.
* **Roughly half the corpus is unreachable by any field**, because Europe PMC is
  47% of it and MeSH is unmapped. The number is published, not implied.
* The vocabulary is duplicated in three places — `ingest/taxonomy.py`,
  `web/src/lib/filters.ts`, and this ADR. The frontend copy exists because
  parsing a URL is synchronous and cannot wait for `GET /fields`; the counts it
  displays always come from the endpoint, so a stale constant can cost a label
  but never a wrong number.
* Adding a source means extending one table, and a category it introduces that
  nobody has mapped shows up in the backfill report instead of silently
  classifying nothing.

## Alternatives rejected

**Ship the OpenAlex field through unchanged.** Simplest, and the version the
filter already implemented. Rejected: it filters 43% of the corpus while looking
like it filters all of it.

**Map MeSH via the descriptor file.** Real work, and it would make the biggest
single source filterable. Rejected for now because the tree is biomedical-only:
the facet it produces is "Medicine, or Medicine" for nearly every record.
Revisit if the corpus stops being half Europe PMC, or if a finer biomedical
facet is wanted in its own right.

**Enrich every paper with OpenAlex topics.** The taxonomy problem disappears if
every paper is an OpenAlex paper. Rejected as a dependency: it needs a DOI
lookup per record against a rate-limited API, and it makes a browsing filter
wait on a data-completeness project.
