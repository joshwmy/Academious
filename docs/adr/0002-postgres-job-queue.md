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
