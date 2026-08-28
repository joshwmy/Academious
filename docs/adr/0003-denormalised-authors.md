# ADR 0003: Authors stored as JSONB, with no local Author entity

**Status:** Accepted (Phase 0, implemented Phase 1)

## Context

The Phase 0 specification proposed `Author` and `PaperAuthor` tables. Author name
disambiguation - deciding that "C. Loot", "Céline Loot" and "Loot C" are one
person, and that two different Wei Zhangs are not - is a research problem in its
own right.

## Decision

`paper.authors` is a JSONB array of `{name, position, orcid, openalex_id,
affiliations}`. No local `Author` table in Phase 1.

## Consequences

* Rendering a paper needs no joins.
* OpenAlex already performs disambiguation and exposes stable author ids, so we
  inherit the solution instead of re-solving it badly.
* Following an author (Phase 3) will key on the OpenAlex author id, and only
  authors somebody actually follows get a local row.
* Querying "all papers by author X" is a JSONB containment query rather than an
  index-friendly join. Acceptable at V1 scale; revisit for researcher profiles.
* `paper.first_author_surname` is extracted at write time as a dedup blocking key.
