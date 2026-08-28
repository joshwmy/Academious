# ADR 0004: Preprints and published versions are linked, never merged

**Status:** Accepted (Phase 0, implemented Phase 1)

## Context

The same research often exists as a preprint and as a published article, with
different DOIs, different titles, different dates and different peer-review
status. A naive deduplicator merges them; a naive feed shows both.

## Decision

Two distinct DOIs always mean two distinct rows. They are connected by a
`paper_relation(preprint_of)` edge. Conflicting DOIs veto every merge path,
including identifier matches that would otherwise fold them together.

## Evidence

Verified against live OpenAlex data:

| | Preprint | Published |
|---|---|---|
| OpenAlex work | `W4296130942` | `W4390571678` |
| DOI | `10.1101/2022.09.11.507474` | `10.1038/s41564-023-01548-y` |
| Title | "A new route for integron cassette dissemination among bacterial genomes" | "Integron cassettes integrate into bacterial genomes via widespread non-classical attG sites" |

The titles are different enough that no similarity threshold would link them, and
they share no identifier. The bioRxiv `/pubs/` endpoint is the only free,
authoritative connection.

## Consequences

* Both records keep their own identity, dates and citation counts.
* The feed can show one row - the published version - while retaining the
  preprint's posting date, which is often the date a reader actually cares about.
* Ingesting bioRxiv is not optional: without it, preprint-to-published linking
  does not work at all.
* A link can only be made once both papers exist; a later run completes pairs
  that were incomplete earlier.
