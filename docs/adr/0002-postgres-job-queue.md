# ADR 0002: PostgreSQL job queue instead of Celery and Redis

**Status:** Accepted (Phase 0, implemented Phase 1)

## Context

Ingestion needs background work: harvests, enrichment, retraction syncs, later
embedding and summarisation. The reflexive answer is Celery with Redis.

## Decision

A `job` table drained with `SELECT ... FOR UPDATE SKIP LOCKED`.

## Consequences

* At roughly 30,000 jobs/day, PostgreSQL handles this without strain.
* Redis, a broker, a result backend and Celery's operational surface all stay out
  of the deployment, which was an explicit infrastructure constraint.
* Jobs are inspectable with SQL, and they participate in the same transaction as
  the data they concern - a job enqueued during ingestion cannot outlive a
  rolled-back transaction.
* Throughput ceiling is lower than a dedicated broker. Revisit if job volume
  exceeds roughly a million a day, which is far beyond V1.
* Redis returns later as a *cache*, not a broker.

## Amendment (Phase 2 closeout): what a dedup key reserves

`dedup_key` is UNIQUE, and `enqueue` suppressed a duplicate only while the
existing job was `pending` or `running`. For a `succeeded` or `failed` job it
fell through to an INSERT and the constraint rejected it, so the one path the
guard was written to permit — queueing the same work again after the previous
attempt finished — raised `IntegrityError` and killed the worker.

This is not hypothetical: migration `0003` makes every embedding row re-check
its source version, which re-derives the same batches and therefore the same
dedup keys as the previous run.

A dedup key now reserves work **in flight**, not for ever. When the existing job
has finished, `enqueue` resets that row to a fresh pending attempt — zero
attempts, no inherited error, new `run_after` — and returns it. One row per key,
the constraint keeps its meaning, and recurring work is queueable.
