# ADR 0005: `fastapi-users` for authentication, re-verified

**Status:** Accepted (Phase 0), re-verified 2026-08-28, implementation deferred to Phase 3

## Context

Phase 0 recommended `fastapi-users` over Clerk and Supabase Auth. Before
committing, its current maintenance and security posture was re-checked.

## Findings (2026-08-28)

* Latest release **15.0.5**, March 2026.
* The project is in **maintenance mode**: security updates and dependency
  maintenance continue, but no new features are planned. A successor Python
  authentication toolkit is being worked on.
* Security handling is credible: a CSRF vulnerability in the OAuth2 flow,
  responsibly disclosed by a Snyk researcher, was patched in 15.0.2 with a
  cookie-based mitigation.
* v15 dropped Python 3.9 and Pydantic v1; both are irrelevant to this project.

## Decision

Proceed with `fastapi-users`.

Maintenance mode is acceptable here, and arguably appropriate: email/password
authentication is a *stable* problem, not a feature-growth area. What matters is
that security reports are still acted on, and they are.

Two conditions:

1. **Isolate it.** Application code depends on our own thin auth layer, not on
   `fastapi-users` types directly, so replacing it later is contained.
2. **Re-verify at Phase 3.** If the successor toolkit has shipped by then, or if
   security updates have visibly stopped, reconsider - the nearest alternative is
   Authlib plus our own user table, or Supabase Auth if outsourcing is preferred.

## Rejected alternatives

* **Clerk** - free to 50k MAU, then roughly $1,025-1,825/month at 100k. A free
  public app accumulates exactly the population that per-MAU pricing punishes,
  and it puts user data in a vendor's database.
* **Supabase Auth** - viable fallback, around $187/month at 100k MAU.
* **Hand-rolled** - explicitly ruled out by the project owner, and correctly so.

## Non-negotiables regardless of library

Argon2id hashing, email verification before personalisation, rate-limited login,
short-lived access tokens with rotating refresh tokens, secrets from environment
only, and no PII beyond email and display name. Public browsing never requires
an account.
