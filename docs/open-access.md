# Open Access and Legal Constraints

## The rule

This project links to legal copies of research. It never bypasses paywalls,
never re-hosts publisher PDFs, never integrates Sci-Hub, and never scrapes
publisher pages.

Source terms, the dependency inventory and the obligations that follow from both
are in [licensing.md](licensing.md). This file is the storage policy and the
resolution chain.

## What we may store

| Content | Store? | Basis |
|---|---|---|
| Metadata: title, authors, DOI, venue, dates, topics | **Yes** | OpenAlex is CC0; Crossref metadata is openly reusable |
| Abstract | **Yes**, with attribution and a source link | |
| Full text under CC-BY / CC-BY-SA / CC0 | **Yes** - may store and process | Licence permits it |
| Full text under CC-BY-NC | Store and process, **flag NC** | Revisit if the project ever monetises |
| PMC Open Access Subset | **Yes** | That is the subset's purpose |
| Any other full text | **No** | Includes most arXiv papers - the arXiv non-exclusive licence is not CC |
| Publisher PDFs | **Never re-host** | arXiv terms prohibit it explicitly; publishers likewise |
| Paywalled content | **Never** | |

Phase 1 stores **no full text at all**. It records where a legal copy lives and
under what licence. `fulltext_status` is `linked` or `abstract_only`, never
`stored`.

## Resolution chain

Resolve once at ingest, then re-check on a decaying schedule - day 7, day 30,
day 90, quarterly - because embargoes lift and papers become open later.

1. OpenAlex `best_oa_location` / `open_access` (free, already in the payload)
2. PMC id
3. Europe PMC `fullTextUrlList`
4. Unpaywall `best_oa_location`
5. Preprint version, via identifier or the bioRxiv `/pubs/` reverse map
6. Repository links in metadata - OpenAlex `locations[]` includes institutional repositories
7. Publisher OA landing page

Phase 1 implements steps 1 and 5. Steps 2-4 and 6-7 arrive in Phase 2 with
Europe PMC and Unpaywall.

**Every** discovered location is stored as an `oa_location` row with its URL, PDF
URL, host type, version, licence, how it was discovered and when it was last
verified. Nothing is discarded because something better was found.

## Electing the best location

Ranked by version, then host, then licence:

```
version: publishedVersion > acceptedVersion > submittedVersion > unknown
host:    publisher > repository > preprint > unknown
licence: cc0 > cc-by > cc-by-sa > cc-by-nc > everything else
```

Exactly one location per paper carries `is_best`, and `paper.best_oa_location_id`
points at it.

## When nothing is found

The interface must say **"No legal free version found"** and offer the DOI link.
An abstract plus an honest link out is a complete experience, not a dead end.
Never imply a copy exists when it does not.

## Licence detection

Two helpers exist because the two preprint servers encode licences differently:

* `sources/arxiv/normalise.is_open_licence` - true only for `creativecommons.org`
  or `publicdomain` URLs. arXiv's default `nonexclusive-distrib` licence is false.
* `sources/biorxiv/normalise.is_storable_licence` - true for `cc0`, `cc-by`,
  `cc-by-sa`. bioRxiv's `cc_no` ("no reuse without permission") is false.

Both must be consulted before any future full-text storage. Neither is used in
Phase 1, because Phase 1 stores no full text.

## Attribution

| Source | Requirement |
|---|---|
| Retraction Watch (via Crossref) | CC-BY 4.0 - attribution required, commercial use permitted |
| OpenAlex | CC0 - no requirement, but credited anyway |
| arXiv | Link to the abstract page; do not represent the project as arXiv-endorsed |
| bioRxiv / medRxiv | Per-paper licence, shown alongside the link |

## Retraction and correction notices

Surfaced prominently, and above any generated summary. A retracted paper is never
hidden from the corpus - it is flagged. A reader who arrives at a retracted paper
needs to know that more than they need the paper to disappear.
