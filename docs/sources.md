# Sources

Every limit below was verified during Phase 0 research, and each is enforced in
`core/ratelimit.SOURCE_LIMITS` at or below the published ceiling.

## OpenAlex - the metadata spine

| | |
|---|---|
| Endpoint | `https://api.openalex.org/works` |
| Auth | **Free API key required since 2026-02-13.** Keyless = 100 credits/day (demo only). |
| Quota | 100,000 credits/day; hard cap 100 req/s. Configured here at 5 req/s. |
| Credit cost | singleton = 1, list = 10, content download = 100, vector search = 1,000 |
| Licence | CC0. Full snapshot on S3, free. |
| Pagination | `cursor=*`, then `meta.next_cursor` |

100k credits/day is 10,000 list calls/day - at 200 results per page, roughly 100x
more than daily incremental ingest needs. Credits only bind if singleton lookups
are run in a loop; batch up to 50 ids per call with OR-syntax filters instead.

**Quirks verified against live payloads:**

* Abstracts arrive as `abstract_inverted_index` and must be reconstructed.
* **Many published records have no abstract at all.** An abstract therefore
  cannot be an ingestion requirement - both integron fixtures in
  `tests/fixtures/openalex/` demonstrate this.
* `is_retracted` is a first-class boolean on the work.
* arXiv ids are **not** exposed as identifiers. The only link is an `arxiv.org`
  URL on a location record, which `ids.arxiv_id_from_url` extracts.
* OpenAlex has begun minting arXiv works under an opaque `10.65215/...` DOI
  prefix which cannot be derived from the arXiv id, unlike `10.48550/arXiv.*`.
* The polite pool and `mailto` mechanism are being retired in favour of keys.

`ACADEMIOUS_OPENALEX_FILTERS` is a `;`-separated list of filter expressions, each
harvested separately. OpenAlex only supports OR *within* one filter key, so the
two launch domains cannot be expressed as a single query.

## arXiv - OAI-PMH

| | |
|---|---|
| Endpoint | `https://export.arxiv.org/oai2` |
| Limit | **One request per three seconds, one connection, across all machines.** |
| Pagination | `resumptionToken`, which by OAI-PMH rule must be sent *alone* |
| Metadata prefix | `arXiv` |

The REST search API is unusable for volume at this rate; OAI-PMH is the
sanctioned bulk interface.

Terms of use permit metadata retrieval, discovery tools, search interfaces and
citation graphs. They **prohibit** redistributing e-prints and serving PDFs or
source files from our own servers unless licensed.

**Licence reality:** most arXiv papers carry arXiv's non-exclusive licence, not a
Creative Commons one. Verified: `1706.03762` returns
`http://arxiv.org/licenses/nonexclusive-distrib/1.0/`. We link; we never store
or re-serve.

**Volume, measured:** `set=cs` returned **1,300 records for the single day
2026-08-18**. That is roughly 39,000 records/month for computer science alone -
materially above the 11,000/month assumed in the Phase 0 cost model. The OAI
`from`/`until` window filters on *datestamp*, so this includes metadata updates
to existing papers, not only new submissions; the true new-submission rate is
lower. See `phase-1-report.md`.

## bioRxiv / medRxiv

| | |
|---|---|
| Endpoints | `/details/{server}/{from}/{to}/{cursor}` (30/page), `/pubs/{server}/...` (100/page) |
| Auth | None |
| Pagination | Offset cursor; `messages[0].total` is authoritative |

The `/pubs/` endpoint maps preprint DOI to published DOI. **This is the reason
bioRxiv is in Phase 1 at all**: it is the only free, authoritative link between a
preprint and its published version, and no amount of title or identifier matching
substitutes for it.

`/details/` records also carry a `published` field with the same information once
the preprint has appeared in a journal.

Licence codes are bioRxiv's own short forms (`cc_by`, `cc_no`, `cc0`, ...) and are
mapped to SPDX-style strings in `sources/biorxiv/normalise.py`. `cc_no` means "no
reuse without permission" and is not storable.

## Europe PMC

| | |
|---|---|
| Endpoint | `https://www.ebi.ac.uk/europepmc/webservices/rest/search` |
| Auth | None. No key, no registration. |
| Quota | No published ceiling. Configured here at 3 req/s, the polite-pool convention used for Crossref. |
| Pagination | `cursorMark=*`, then `nextCursorMark` |
| Result type | `core` - MeSH terms, affiliations, licences and full-text URLs. `lite` has none of them |

**The bulk prohibition, quoted from europepmc.org/developers:** *"It is not
permissible to use any kind of automated process to bulk download other content
from Europe PMC."* Their protocols exist to serve the open-access subset and
metadata, so `ACADEMIOUS_EUROPEPMC_QUERIES` defaults to `OPEN_ACCESS:Y`. It is a
`;`-separated list of query expressions, each harvested separately; widening it
is a decision to be made against those terms, not by accident.

The harvest window filters on `UPDATE_DATE`, not `FIRST_PDATE`: a paper whose
MeSH terms, licence or retraction status changed today has to come back today,
and its publication date has not moved.

**Quirks verified against live payloads** (`tests/fixtures/europepmc/`):

* `pubTypeList` mixes MEDLINE and JATS vocabularies on the same record
  (`Retracted Publication` beside `research-article`).
* A **retraction notice** (`Retraction of Publication`) is a different document
  from the **retracted article** (`Retracted Publication`).
* `license` is populated on records that are not open access at all: a
  subscription-only article carries `cc by` with `isOpenAccess` `N`. Licence
  never decides OA status.
* `oa_status` from this source is only ever `green`, `bronze` or `closed`.
  Europe PMC reports that a free copy exists and where; it does not report
  whether the *journal* is open access, so `gold` and `hybrid` stay OpenAlex's
  to compute.
* `author.fullName` is the MEDLINE abbreviation ("Jumper J"); `firstName` and
  `lastName` sit beside it and are preferred, because dedup compares surnames
  against other sources' full names.
* HTML and PDF renderings of one copy are listed as two URLs. They are grouped
  into a single location with a `pdf_url`.
* A `Preprint of` entry in `commentCorrectionList` is **heuristic** - the
  payload's own `note` says "Link created based on a title-first author match" -
  and carries a citation string rather than a DOI. It is deliberately **not**
  turned into a preprint relation. bioRxiv's `/pubs/` map stays the only
  authoritative link, and a wrong relation is worse than a missing one.
* MeSH descriptors arrive without their descriptor UI, so topics are keyed by
  the term itself under scheme `mesh`.
* **MeSH is indexed months after publication.** A live page of 100 records
  from a one-week update window carried MeSH on **1** of them. That is not a
  defect and it is the reason the window filters on `UPDATE_DATE`: the same
  paper comes back when it is indexed, and the topics land then.

### First live harvest, 2026-09-01

A bounded harvest of `OPEN_ACCESS:Y` over an `UPDATE_DATE` window, and then a
second one after the corpus-admission policy landed. What the subset contains,
and what Academious takes from it:

| | Before the policy | After |
|---|---|---|
| Papers from Europe PMC | 306 | 618 |
| NCBI Bookshelf chapters | **173** | **0** |
| Journal articles | 47 | 438 |
| Reviews in journals | - | 74 |
| Preprints | 77 | 101 |
| With an author list | 63% | 98% |
| With a venue | 41% | 100% |
| With a DOI | 34% | 91% |

The open-access subset is not a stream of research papers, and three properties
of it drive everything above:

* **Reference works dominate it.** StatPearls and GeneReviews chapters
  outnumbered journal articles roughly four to one, and 105 of them carried no
  author list at all. They are excluded as tertiary literature - see
  [ingestion.md](ingestion.md#what-the-corpus-admits) - and identified through
  `hasBook` and the `NCBI_Bookshelf` full-text site, each of which fired on
  **174 of 174** Bookshelf records and **0 of 132** others. Publication type
  cannot do this job: MEDLINE types GeneReviews chapters as `Review`, exactly
  as it types a review article.
* **A single supplement can dominate a window.** 445 of the first 500 records
  were conference abstracts from two supplement issues (`BJPsych open` Suppl 1,
  `ASHE`), page ranges `S92-S93`, with no DOI, no PMID and no abstract text.
* **Europe PMC marks preprints `isOpenAccess: N`.** Verified against three
  bioRxiv DOIs already in the corpus: all three are indexed by Europe PMC, all
  three are excluded by the default query. The preprints that do arrive are the
  minority flagged open access.

## Retraction Watch, via Crossref

| | |
|---|---|
| Endpoint | `https://api.labs.crossref.org/data/retractionwatch?mailto=...` |
| Licence | **CC-BY 4.0** - commercial use permitted with attribution |
| Size | ~66 MB CSV, ~72,000 rows as of Phase 1 |
| Alternatives | Crossref REST API, or `git clone https://gitlab.com/crossref/retraction-watch-data` |

Downloaded whole and diffed rather than queried per paper.

**Quirks verified against the live dataset:**

* One DOI may carry several notices. `10.1016/s0140-6736(20)31180-6` has a
  correction, an expression of concern and a retraction.
* Dates are US `M/D/YYYY H:MM` with no zero padding.
* `RetractionNature` values seen: `Retraction`, `Expression of concern`,
  `Correction`, `Reinstatement`.
* `Reason` is a `;`-separated list with a trailing separator.

## Not yet integrated

| Source | Role | Phase |
|---|---|---|
| PubMed / NCBI E-utilities | biomedical freshness, MeSH. 10 req/s with a **registered** key; large jobs off-peak (21:00-05:00 US Eastern, or weekends). | 2 |
| Unpaywall | OA fallback resolver, 100k calls/day, `?email=` required. | 2 |
| Crossref | DOI validation, reference lists. Public pool 1 req/s on list endpoints since 2025-12-01; polite pool 3 req/s. | 3 |
| Semantic Scholar | TLDRs, citation context. ~1 req/s per key - unacceptable on a critical path. | 8 |
