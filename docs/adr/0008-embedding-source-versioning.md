# ADR 0008: embeddings record the paper version they were built from

**Status:** Accepted (Phase 2 closeout)

## Context

The embedding worker must answer one question cheaply and in SQL: *which papers
need work under this model key?* Phase 2 answered it by comparing the two
tables' own modification timestamps:

```sql
paper.updated_at > paper_embedding.updated_at
```

Those timestamps are generated independently and do not share a clock or a
semantics. `paper.updated_at` is PostgreSQL `func.now()`, which is the
**transaction start** time and constant for the whole transaction.
`paper_embedding.updated_at` was the application's `utcnow()`, evaluated at
**statement time** on a different host.

That makes the comparison unsound, and not only under clock skew. A paper edit
whose transaction opens *before* the worker writes a vector, and commits
*after*, carries the earlier timestamp despite landing later. The predicate
concludes the vector is current. The paper never queues again until some
unrelated later write happens to bump its row, so the obsolete vector is
stranded indefinitely — and because the prefilter is what decides whether the
`input_text_hash` check runs at all, the hash never gets the chance to catch it.

Reproduced against a live database before the fix:

```
paper.abstract       : COMPLETELY DIFFERENT TEXT   (embedded from "original text")
paper.updated_at     : 16:07:00.887612+00   <- editing transaction start
embedding.updated_at : 16:07:00.945231+00   <- written by the worker mid-flight
queued for re-embedding? False
```

## Decision

**Store the source version on the embedding row.** `paper_embedding.
source_updated_at` holds the value of `paper.updated_at` from the paper row the
worker actually read when it built that vector. Staleness becomes:

```sql
paper_embedding.paper_id IS NULL
OR paper.updated_at IS DISTINCT FROM paper_embedding.source_updated_at
```

Both sides are now the same value read from the same column, so the comparison
is exact: it does not order two clocks, and no commit interleaving loses an
update. If an edit commits before the worker's snapshot, the worker records the
new version. If it commits after, the worker records the old one and the paper
queues again.

Existing rows are left NULL by migration `0003` rather than backfilled to
`paper.updated_at`. `IS DISTINCT FROM` treats NULL as an unknown version, so
each legacy row is re-checked exactly once against `input_text_hash` — dismissed
without inference if unchanged, rebuilt if the old rule had stranded it.

## Alternatives considered

**Change `>` to `>=`, or align both columns on `func.now()`.** Neither fixes
it. The failure is not operator choice or clock choice; it is that two
independently generated timestamps cannot express which text a vector was built
from when a writer may commit either side of the worker's snapshot.

**Compare content hashes in SQL.** The embedding already stores
`input_text_hash`, but the hash it must be compared against is the hash of the
text the builder would produce *now*, and the builder is Python and
profile-dependent (`TITLE_ONLY` and `AUTO` produce different text from the same
paper). A paper-side hash column would need one column per input strategy and
would have to be kept in step with `INPUT_VERSION`. More schema, more coupling,
and no more correctness than a version copy.

**Drop the prefilter and hash-check every paper on every pass.** Correct, and
trivial at 2,455 papers, but it builds and hashes the text of the entire corpus
on every run. The prefilter exists so that a steady-state pass is a cheap index
scan; removing it trades a real property for one this ADR already gets.

## Consequences

* One nullable `timestamptz` per embedding row. No index needed: the predicate
  is evaluated against the row the existing `(model_key, paper_id)` join already
  reaches.
* Dismissing an unchanged paper now advances `source_updated_at`. This is the
  only path that marks a vector current without running the model, and it is
  sound because the hash proved the text identical.
* The first pass after this migration re-checks every row. Measured on the
  Phase 2 corpus: 2,455 rows per profile, ~11 s, **zero** model inference and
  zero hash mismatches — confirming the defect had stranded nothing in this
  corpus and that no published benchmark number depended on it.
* `updated_at` remains on the row for observability. It no longer decides
  anything.
