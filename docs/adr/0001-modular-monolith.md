# ADR 0001: A modular monolith, not microservices

**Status:** Accepted (Phase 0)

## Context

The system has several distinct responsibilities - harvesting, deduplication,
ranking, summarisation, serving - and each could be a service.

## Decision

One FastAPI application, one PostgreSQL, workers in the same codebase, one
deployable image. Boundaries are enforced by package structure, not by network
calls.

## Consequences

* One developer can hold the whole system in their head and deploy it in one step.
* No service mesh, no distributed tracing, no cross-service schema versioning.
* Scaling is vertical first, then splitting the database onto its own machine.
* If a component ever genuinely needs independent scaling, the package boundary
  is already where the service boundary would go.
