"""Raw DDL that both Alembic migrations and the test bootstrap need.

The test suite builds its schema with ``Base.metadata.create_all`` rather than by
running migrations, so anything a table definition depends on but SQLAlchemy
cannot emit - extensions, helper functions - has to live somewhere both paths
can reach. That is this module. One definition, two callers, no drift.
"""

from __future__ import annotations

# pg_trgm backs fuzzy deduplication (Phase 1); vector backs halfvec storage and
# the distance operators used by semantic retrieval (Phase 2).
EXTENSIONS = ("pg_trgm", "vector")

# PostgreSQL marks array_to_string() STABLE rather than IMMUTABLE because for a
# general anyarray the element output function may depend on settings. For
# text[] with a constant separator there is no such dependency, so this wrapper
# is genuinely immutable and a generated column may use it. Without the wrapper,
# `search_tsv` cannot include keywords at all.
KEYWORDS_TEXT_FUNCTION = """
CREATE OR REPLACE FUNCTION academious_keywords_text(text[]) RETURNS text
    LANGUAGE sql IMMUTABLE PARALLEL SAFE
    AS $fn$ SELECT coalesce(array_to_string($1, ' '), '') $fn$
"""

DROP_KEYWORDS_TEXT_FUNCTION = "DROP FUNCTION IF EXISTS academious_keywords_text(text[])"

# The lexical index. Field weights are assigned here and interpreted at query
# time by ts_rank_cd's weight array, so changing the relative importance of
# title vs abstract does not require reindexing 
#
#   A  title       - the strongest signal a paper gives about its own subject
#   B  keywords    - curated subject terms, and OpenAlex topic display names
#   C  abstract    - richest but noisiest; a term here is weak evidence alone
#
# Topics are JSONB (see sources/openalex/normalise.py for the shape: the human
# readable name is under `label`). They are flattened with
# jsonb_path_query_array, whose text cast *is* immutable, unlike
# array_to_string. Only `label` is indexed: `field` and `domain` are
# coarse names like 'Computer Science' that match almost any query in
# their discipline and would flatten the ranking.
SEARCH_TSV_EXPRESSION = (
    "setweight(to_tsvector('english', coalesce(title, '')), 'A') || "
    "setweight(to_tsvector('english', academious_keywords_text(keywords)), 'B') || "
    "setweight(to_tsvector('english', "
    "coalesce(jsonb_path_query_array(topics, '$[*].label')::text, '')), 'B') || "
    "setweight(to_tsvector('english', coalesce(abstract, '')), 'C')"
)


#: What the feed sorts on: the earlier of the date a paper claims and the date
#: it first reached us. Journals postdate issues, so `published_date` alone puts
#: work that is not out yet above work that is - see migration 0005.
#:
#: `created_at` is cast through an explicit UTC conversion because a bare
#: `::date` on a timestamptz is only STABLE (it depends on the session
#: timezone) and a generated column requires IMMUTABLE.
#:
#: The CASE is not decoration. **PostgreSQL's LEAST skips NULLs**, unlike
#: arithmetic - `LEAST(NULL, current_date)` is today, not NULL - so without it
#: a paper with no publication date would be dated today and lead the feed.
#: That is precisely the row that must not lead it: the papers whose
#: implausible dates were cleared would have been promoted for being repaired.
FEED_DATE_EXPRESSION = (
    "CASE WHEN published_date IS NULL THEN NULL "
    "ELSE LEAST(published_date, (created_at AT TIME ZONE 'UTC')::date) END"
)


def create_extensions_sql() -> list[str]:
    return [f"CREATE EXTENSION IF NOT EXISTS {name}" for name in EXTENSIONS]


def bootstrap_sql() -> list[str]:
    """Everything that must exist before any Academious table can be created."""
    return [*create_extensions_sql(), KEYWORDS_TEXT_FUNCTION]
