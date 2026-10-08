# ADR 0012: Consented accounts own the recommendation learning loop

**Status:** accepted and implemented — 2026-10-08

## Context

Device-local profiles proved the end-to-end recommendation shape but could not
sync, build collaborative candidates, or retain attributed impressions. The
product now obtains explicit recommendation-data consent during registration.
That permits durable use; it does not permit treating every observation as a
label or exposing one reader's state to another.

## Decision

Use `fastapi-users` behind `academious.auth` with Argon2 password hashing,
email verification, password reset and opaque revocable database sessions in an
HTTP-only, SameSite cookie. Production requires a non-default secret, secure
cookies and working SMTP. Unsafe credentialed requests must originate at the
configured frontend.

Persist the normalised profile draft, saved papers, recommendation events and
per-reader ranker weights in PostgreSQL. Every event carries the consent version
and client event UUID. A server-issued row stores the feature snapshot and
position that produced each recommendation; a later outcome may learn only by
joining that snapshot. Impressions are exposure, never negative evidence.

The account feed combines content-based, recent-sequence, collaborative and
adjacent-interest candidates, then applies the existing feature ranker and
diversity pass. Explicit saves/more-like-this and explicit negative actions make
small bounded updates to that reader's weights. They never change global weights
online. Collaborative candidates require support from at least three distinct
peers, reducing low-population disclosure. Account deletion cascades through
every reader-owned table.

## Consequences

- Anonymous browsing and local profile use remain available.
- A single user cannot poison ranking for everyone through online updates.
- The system has a production-shaped feedback loop but not a production-proven
  model. Population learning-to-rank requires enough logged outcomes, offline
  position-bias-aware evaluation, a held-out baseline and rollback.
- Backups now contain personal data and inherit the retention/deletion duties in
  the security and deployment documents.
