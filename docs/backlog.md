# Backlog — deferred and open engineering work

This file is the **canonical register of work that is known, deliberate and not
done**. If something is deferred, it is written down here; if it is not written
down here, it is not deferred, it is forgotten.

It is not a roadmap. The roadmap is the intended *sequence* of product phases
and lives in [phase-0-report.md §13](phase-0-report.md#13-phased-implementation-plan).
This file is the *open engineering work* that sits alongside that sequence —
things measured and postponed, blocked on infrastructure, or consciously scoped
out. Items point at a target phase; they do not restate it.

It is also not a project-management system. There are no assignees, no estimates
and no priorities beyond status and dependency. The purpose is **durable
engineering memory across sessions**.

---

## 1. How to use this file

| When you… | Do this |
|---|---|
| Defer something | Add an item, or update the existing one. Never leave it only in a phase report |
| Start something | Set status `IN PROGRESS` |
| Finish something | Set status `DONE`, cite the commit or ADR — do not delete the entry |
| Decide never to do it | Set status `WONTFIX` and record why |
| Find a duplicate | Merge into the lower-numbered ID and note the merge. Do not create variants |
| Find a blocker | Set status `BLOCKED` and name the blocking ID under *Depends on* |
| Hit a real defect in work you are shipping | **Fix it.** The backlog is for deferrable work, not for parking correctness, security, migration-safety or API-contract bugs that affect the milestone in hand |

History is kept. A `DONE` or `WONTFIX` entry stays in the file, because the
useful information is usually *why* something was closed, not that it was.

Anything large enough to need argument gets an [ADR](adr/) or its own document,
and the backlog entry links to it rather than absorbing it.

Every implementation report from 2026-08-31 onward carries a **Backlog changes**
section (added / updated / closed / new blockers) and a **Deferred
intentionally** section. That is a standing discipline, not a per-milestone
request.

### IDs

Stable, never reused, referenceable from commits and docs.

| Prefix | Area |
|---|---|
| `DEPLOY-` | Deployment, hosting, DNS, CI/CD, backups |
| `SEC-` | Security and operations |
| `RETR-` | Retrieval quality, evaluation, ranking performance |
| `DATA-` | Embeddings, data model, corpus and migration debt |
| `SRC-` | Sources, connectors, ingestion coverage |
| `WEB-` | Frontend |
| `PROD-` | Product-level decisions and future-feature risk |

### Status values

`DEFERRED` · `BLOCKED` · `READY` · `IN PROGRESS` · `DONE` · `WONTFIX`

`READY` means nothing blocks it and it could be picked up next. `DEFERRED` means
it could be started but deliberately is not.

---

## 2. Index

| ID | Item | Status | Target |
|---|---|---|---|
| [DEPLOY-001](#deploy-001) | Move the backend to the approved VPS topology | DEFERRED | Pre-launch |
| [DEPLOY-002](#deploy-002) | Stable API hostname, DNS and TLS | BLOCKED | Pre-launch |
| [DEPLOY-003](#deploy-003) | Remove backend-only environment variables from the Vercel project | READY | Next infra pass |
| [DEPLOY-004](#deploy-004) | Cut CORS and allowed hosts over to the permanent origin | BLOCKED | Pre-launch |
| [DEPLOY-005](#deploy-005) | Decide the production frontend domain | DEFERRED | Pre-launch |
| [DEPLOY-006](#deploy-006) | Encrypted off-machine backups and a restore drill | BLOCKED | Phase 6 exit criterion |
| [DEPLOY-007](#deploy-007) | CI/CD pipeline | DEFERRED | Phase 6 |
| [SEC-001](#sec-001) | Rate limiter is process-local | DEFERRED | Before a second API process |
| [SEC-002](#sec-002) | SPECTER2 concurrency gate is process-local | DEFERRED | Before a second API process |
| [SEC-003](#sec-003) | Restrict `/metrics/*` and `/health/db` at the proxy | BLOCKED | With DEPLOY-001 |
| [SEC-004](#sec-004) | Proxy trust configuration in production | BLOCKED | With DEPLOY-001 |
| [SEC-005](#sec-005) | Transport limits: TLS, HSTS, request size, timeouts | BLOCKED | With DEPLOY-001 |
| [SEC-006](#sec-006) | Vercel preview origins are not allowed by production CORS | WONTFIX | — |
| [SEC-007](#sec-007) | Prompt-injection and tool-use threat model for a generative layer | DEFERRED | Before Phase 5 code |
| [SEC-008](#sec-008) | No per-caller quota without accounts | DEFERRED | Phase 3 |
| [SEC-009](#sec-009) | Query text is not logged; logging it is a privacy decision | DEFERRED | Whenever analytics is proposed |
| [SEC-010](#sec-010) | `transformers` 4.x advisories, unreachable but pinned | DEFERRED | When `adapters` supports 5.x |
| [SEC-011](#sec-011) | No automated secret scanning | DEFERRED | With DEPLOY-007 |
| [RETR-001](#retr-001) | The default retrieval method is provisional | DEFERRED | First phase exposing ranking to users |
| [RETR-002](#retr-002) | Six benchmark queries held out, unjudged | DEFERRED | See trigger |
| [RETR-003](#retr-003) | Hybrid/RRF investigation is frozen | DEFERRED | With RETR-002 |
| [RETR-004](#retr-004) | Retrieval measured at ~2.5k papers only | DEFERRED | At 10x corpus |
| [RETR-005](#retr-005) | ONNX int8 inference unimplemented | DEFERRED | When a backfill is scheduled |
| [RETR-006](#retr-006) | No re-ranking, learning-to-rank or personalisation | DEFERRED | Phase 3 / Phase 8 |
| [DATA-001](#data-001) | `specter2-benchmark@v1` ablation vectors remain in the database | DEFERRED | Storage or maintenance pressure |
| [DATA-002](#data-002) | No normalised subject taxonomy | BLOCKED | With SRC-004 |
| [DATA-003](#data-003) | Title-only embedding path unexercised at volume | BLOCKED | With SRC-004 |
| [DATA-004](#data-004) | `halfvec` quantisation effect not re-checked at scale | DEFERRED | At 10x corpus |
| [DATA-005](#data-005) | Cost model still rests on estimated ingestion volumes | DEFERRED | After a week of real harvesting |
| [SRC-001](#src-001) | PubMed connector | DEFERRED | Phase 2 remainder |
| [SRC-002](#src-002) | Europe PMC connector | DEFERRED | Phase 2 remainder |
| [SRC-003](#src-003) | Unpaywall fallback | DEFERRED | Phase 2 remainder |
| [SRC-004](#src-004) | OpenAlex harvesting into the live corpus | READY | Phase 2 remainder |
| [WEB-001](#web-001) | Visual design is a baseline, not a finished appearance | DEFERRED | Dedicated design pass |
| [WEB-002](#web-002) | Filter UI over the filters `/papers` supports | DONE | — |
| [WEB-003](#web-003) | Feed by field | BLOCKED | With DATA-002 |
| [WEB-004](#web-004) | SEO and prerendering | DEFERRED | Phase 6 |
| [WEB-005](#web-005) | Offset pagination only | DEFERRED | When deep offsets hurt |
| [WEB-006](#web-006) | Search result count fixed at 20 | DEFERRED | With the design pass |
| [WEB-007](#web-007) | Colour contrast verified by hand, not in a browser | DEFERRED | With the design pass |
| [WEB-008](#web-008) | No analytics | WONTFIX | — |
| [WEB-009](#web-009) | No accounts, saved papers or recommendations | DEFERRED | Phase 3 |
| [WEB-010](#web-010) | `/search` accepts no filters, so filtering stops at the feed | DEFERRED | Phase 3 |
| [PROD-001](#prod-001) | A generative explanation layer changes the threat model | DEFERRED | Phase 5 |
| [PROD-002](#prod-002) | Accounts turn query logs and interest profiles into privacy assets | DEFERRED | Phase 3 |

---

## 3. Deployment and infrastructure

### DEPLOY-001

**Move the backend to the approved VPS topology.** — `DEFERRED`

The production-testing topology today is:

```
Vercel (static frontend)
  -> Cloudflare quick tunnel        (ephemeral hostname, no stable DNS)
     -> this development PC
        -> Caddy
           -> FastAPI / PostgreSQL / SPECTER2
```

The permanent target is unchanged from the Phase 0 decision: a Hetzner VPS
running Docker Compose behind Caddy — see [deployment.md](deployment.md).

* **Why deferred** — the tunnel exercises the whole stack end to end from a real
  browser making a real cross-origin request, which is what the frontend
  milestone needed. Standing up a VPS buys no product capability and costs a day
  better spent on user-facing work.
* **Risk/impact** — **the backend is up only while this PC is.** No uptime
  guarantee, no restart policy, and the tunnel hostname is ephemeral: it changes
  whenever the tunnel restarts, and the Vercel frontend is built against
  whichever hostname was current at build time, so a restart breaks the deployed
  site until it is rebuilt. This topology must not be described to anyone as
  production.
* **Trigger to revisit** — before any public announcement, any real user, or
  anything that needs the API to answer while the developer is asleep.
* **Depends on** — nothing. Blocks DEPLOY-002, DEPLOY-004, DEPLOY-006, SEC-003,
  SEC-004, SEC-005, and the sustained harvesting behind SRC-004 and DATA-005.
* **Source** — [deployment.md](deployment.md),
  [phase-0-report.md §16](phase-0-report.md#16-decisions-taken-2026-08-28)
  decision 5.

### DEPLOY-002

**Stable API hostname, DNS and TLS.** — `BLOCKED`

The API should answer on a permanent name — `api.<domain>` — with its own DNS
record and TLS terminated at Caddy, replacing the Cloudflare quick-tunnel
hostname the Vercel build currently points at.

* **Why deferred** — a stable name is only meaningful once the thing behind it is
  stable, which is DEPLOY-001.
* **Risk/impact** — until then every tunnel restart is a frontend rebuild, and no
  external party can be given a durable link to the API.
* **Trigger to revisit** — with DEPLOY-001.
* **Depends on** — DEPLOY-001, DEPLOY-005.

### DEPLOY-003

**Remove backend-only environment variables from the Vercel project.** — `READY`

The Vercel project retains environment variables and secrets from an abandoned
attempt to deploy the backend there — database configuration, the OpenAlex API
key, and other server-only values. Vercel now builds only the Vite frontend in
`web/`.

* **Why deferred** — not exposed, so not urgent: only `VITE_*` variables are
  inlined into the bundle, and none of these are. Removing them is cleanup, and
  this pass was scoped to feature work.
* **Risk/impact** — a credential stored where it is not needed has a larger blast
  radius than it should. Anyone with project access can read it, and a future
  misconfiguration that prefixed one with `VITE_` would publish it in a public
  bundle. The OpenAlex key should be **rotated** unless it can be established
  that it was never exposed.
* **What to do** — delete every backend-only variable from the Vercel project;
  rotate the OpenAlex credential if warranted; verify the only remaining value is
  `VITE_API_BASE_URL`.
* **Trigger to revisit** — the next infrastructure pass, or immediately if
  project access changes hands.
* **Note** — deliberately not folded into a feature milestone. Destructive
  changes to a live deployment's configuration are their own change with their
  own verification.

### DEPLOY-004

**Cut CORS and allowed hosts over to the permanent origin.** — `BLOCKED`

`ACADEMIOUS_CORS_ALLOWED_ORIGINS` and `ACADEMIOUS_ALLOWED_HOSTS` currently name
the temporary tunnel host and the current Vercel origin. Both move to the
permanent hostnames, and the temporary values are removed rather than left
alongside.

* **Risk/impact** — a stale allowed origin is a permanently trusted origin that
  somebody else may later be able to claim.
* **Depends on** — DEPLOY-001, DEPLOY-002, DEPLOY-005.
* **Source** — [security.md §6](security.md#6-transport-headers-cors-and-hosts).

### DEPLOY-005

**Decide the production frontend domain.** — `DEFERRED`

Whether the frontend keeps its Vercel-assigned hostname or moves to a custom
domain, and whether the API then lives on a subdomain of that domain.

* **Why deferred** — a naming decision with no engineering content until there is
  something to announce.
* **Risk/impact** — low in itself, but it is an input to DEPLOY-002 and
  DEPLOY-004, and changing it later invalidates every shared link and every
  canonical URL WEB-004 would emit.
* **Trigger to revisit** — before DEPLOY-002, and before WEB-004.

### DEPLOY-006

**Encrypted off-machine backups and a restore drill.** — `BLOCKED`

pgBackRest or wal-g, encrypted with age before leaving the host, to B2 or R2,
7/4/12 retention, staleness alerting, and a quarterly restore drill.

* **Why deferred** — there is no user data yet and the corpus is re-derivable
  from the sources. The obligation attaches to real data, not to a development
  database.
* **Risk/impact** — a Phase 0 design obligation and a **Phase 6 exit criterion**.
  It must be in place *before* real user data exists, not after. Even with
  nothing irreplaceable lost, re-harvesting a full corpus costs days of
  rate-limited requests.
* **Trigger to revisit** — with DEPLOY-001, and unconditionally before accounts.
* **Depends on** — DEPLOY-001.
* **Source** — [deployment.md](deployment.md#backups-encrypted-and-off-machine).

### DEPLOY-007

**CI/CD pipeline.** — `DEFERRED`

GitHub Actions building the image to GHCR, `docker compose pull && up -d` over
SSH, migrations as a separate step before the new image serves. There is no
`.github/` directory today; every gate runs locally.

* **Why deferred** — nothing to deploy to (DEPLOY-001), and one developer running
  the same gates locally gets most of the value.
* **Risk/impact** — gates depend on discipline rather than enforcement; nothing
  prevents a commit that was never linted or typechecked.
* **Depends on** — DEPLOY-001.

---

## 4. Security and operations

These are recorded because they are **deployment-dependent**, not because the
application is missing a control. The distinction is kept explicit below.
Controls already implemented and tested — rate limiting, the concurrency gate,
response allowlisting, security headers, CORS and host validation, hostile-input
handling, model revision pinning — are documented in [security.md](security.md)
and are **not** listed here.

### SEC-001

**The rate limiter is process-local.** — `DEFERRED`

* **Status of the control** — *implemented, and correct for the approved
  deployment*, which is one FastAPI process. Not a gap today.
* **Why deferred** — introducing Redis for a single-instance deployment adds a
  stateful dependency and an availability risk of its own, to solve a problem
  that does not exist yet.
* **Risk/impact** — the moment a second worker or replica exists, *n* processes
  means *n* independent budgets and an effective limit of *n* times the
  configured number. Counters are also lost on restart, which resets every
  window.
* **Trigger to revisit** — **before** running more than one API process. This is
  a precondition of horizontal scaling, not a follow-up to it.
* **Migration path** — `slowapi` `storage_uri` to `redis://…`, and nothing else.
* **Source** — [security.md §3](security.md#3-rate-limiting).

### SEC-002

**The SPECTER2 concurrency gate is process-local.** — `DEFERRED`

Search holds a two-slot semaphore so concurrent query encoding cannot exhaust the
box. Same shape as SEC-001: with *n* processes the real concurrency is 2*n*, and
the memory ceiling it protects is per-machine, not per-process.

* **Trigger to revisit** — with SEC-001, before a second API process.
* **Source** — [security.md §5](security.md#5-concurrency).

### SEC-003

**Restrict `/metrics/*` and `/health/db` at the reverse proxy.** — `BLOCKED`

`/metrics/embeddings` names the active embedding profile and every model key that
exists and reports queue depth; `/metrics/ingestion` reports source health and
error counts; `/health/db` reveals corpus size.

* **Status of the control** — the application deliberately has **no**
  authentication to enforce this with; a proxy rule is the intended mechanism.
  The routes are tagged `ops` in the OpenAPI document precisely so a proxy rule
  can find them, and a test asserts the tagging stays accurate.
* **Risk/impact** — useful reconnaissance if left open.
* **Depends on** — DEPLOY-001.
* **Source** — [security.md §9](security.md#9-operational-endpoints).

### SEC-004

**Proxy trust configuration in production.** — `BLOCKED`

Behind Caddy: `ACADEMIOUS_TRUSTED_PROXY_COUNT=1`, uvicorn run with
`--proxy-headers` and `--forwarded-allow-ips` set to the proxy address.

* **Risk/impact** — leaving the count at 0 makes every request appear to come
  from the proxy, so all clients share one bucket and the limiter throttles the
  whole world at once. Setting it too high lets a client spoof `X-Forwarded-For`
  and mint itself a fresh budget.
* **Depends on** — DEPLOY-001.

### SEC-005

**Transport limits belong to the deployment layer.** — `BLOCKED`

TLS termination and HSTS, request and URL size caps, and connection/read timeouts
are Caddy's by design: the application cannot see whether TLS terminated in front
of it and so cannot honestly assert HSTS, and oversized requests should be
dropped before application parsing.

* **Depends on** — DEPLOY-001.
* **Source** — [security.md §6](security.md#6-transport-headers-cors-and-hosts).

### SEC-006

**Vercel preview origins are not allowed by production CORS.** — `WONTFIX`

Preview deployments get a fresh, unpredictable origin per build. Allowing them
would mean either a wildcard or an origin pattern that anybody's preview could
satisfy.

* **Why not** — a decision, not an omission. Preview builds are exercised against
  a local API; the production API answers the production origin only.
* **Reopen only if** — preview builds must be tested against production data, in
  which case the answer is a separate, explicitly named staging origin, never a
  pattern.

### SEC-007

**A generative layer needs its own threat model.** — `DEFERRED`

An answer or explanation layer would make prompt injection (OWASP LLM01)
immediately applicable, and would make paper abstracts — attacker-influenced
content, since anyone can post a preprint — part of the prompt.

* **Status** — *future-feature risk*, not a present gap. Nothing generative exists
  in the codebase.
* **Design already in place** — the API boundary is built so such a layer is a new
  endpoint with its own limits, not a flag on `/search`.
* **Trigger to revisit** — before the first line of Phase 5 code, not after it.
* **Gates** — PROD-001.
* **Source** — [security.md §12](security.md#future-feature-risks),
  [phase-0-report.md §3.5](phase-0-report.md#35-prompt-injection-defence).

### SEC-008

**No authentication means no per-caller quota.** — `DEFERRED`

Limits are per client address. A distributed scraper across many addresses is
bounded only by aggregate concurrency.

* **Status** — accepted for a public, unauthenticated read API over CC0-derived
  metadata. Accounts (Phase 3) bring real per-user quotas, and with them OWASP
  API1/API2/API3 in their real forms.

### SEC-009

**Query text is not logged.** — `DEFERRED`

Search logs record query *length*. Logging full queries would be a deliberate
privacy decision — one to take and document, not to arrive at by accident while
adding analytics.

* **Trigger to revisit** — the first time anyone proposes query analytics.
* **Related** — WEB-008, PROD-002.

### SEC-010

**`transformers` 4.x advisories: unreachable, and pinned there.** — `DEFERRED`

Five `pip-audit` findings, all in `transformers 4.57.6`, all requiring a model
loaded from an attacker-controlled source — a precondition that pinned model
constants and pinned revisions remove. Fix versions are 5.x, and `adapters` (the
SPECTER2 adapter stack) requires 4.x.

* **Trigger to revisit** — when `adapters` supports `transformers` 5.x. Upgrade
  both together and **re-run the six-query benchmark before accepting the
  result**: an encoder change invalidates the measurement the retrieval gate was
  passed on.
* **Source** — [security.md §11](security.md#11-security-tooling-and-findings).

### SEC-011

**No automated secret scanning.** — `DEFERRED`

Checked by hand: no credential literals in `src`, `tests` or `migrations`; `.env`
is git-ignored; the only committed connection string is the local development
placeholder.

* **Trigger to revisit** — with DEPLOY-007. A scanner belongs in CI.

---

## 5. Retrieval

### RETR-001

**The default retrieval method is provisional.** — `DEFERRED`

`ACADEMIOUS_RETRIEVAL_DEFAULT_METHOD` defaults to `semantic` on the strength of
the aggregate over six judged queries. That is an implementation default backed
by evidence, **not** a resolution of the question.

What the evidence says, from 208 judgments over six queries:

* semantic is the strongest single method on aggregate P@5, MRR and NDCG@10;
* the lead is domain-shaped — +0.230 NDCG@10 across the biomedical queries,
  +0.018 across the computing queries, where lexical has the best MRR;
* hybrid wins NDCG@10 on 3 of 6 queries and leads recall@10, but sits behind both
  components on MRR and wins MRR on no individual query;
* there is **no universal winner**.

Notes:

* **Why deferred** — six queries and one judge cannot choose a default without
  fitting noise. Nothing was retuned in response to them, deliberately.
* **Risk/impact** — an *evaluation and architecture* item, not a blocker. The
  endpoint is honest about what it does; the open question is which default
  serves readers best.
* **Trigger to revisit** — the first phase that exposes ranking to real users,
  informed by RETR-002.
* **Source** — [phase-2-report.md §9](phase-2-report.md#what-the-gate-does-not-decide),
  [evaluation.md §8](evaluation.md#8-measured-results).

### RETR-002

**Six benchmark queries are held out and unjudged.** — `DEFERRED`

Preserved deliberately, and **not to be judged to settle a present argument — a
holdout that has been peeked at is no longer a holdout.**

The remaining holdout, exactly:

```
bio-03   bio-04   bio-06   cs-01   cs-03   cs-04
```

They are pooled but unjudged, and cover query behaviours the judged six do not:
ranking under high match density, broad-field intersections, weak lexical
modifiers, and recency.

* **Why deferred** — they are worth more unspent than spent. Their value is as
  confirming or overturning evidence for the interim reading, which requires that
  the interim reading be formed without them.
* **Risk/impact** — spending them casually is irreversible.
* **Trigger to revisit** — when a decision genuinely turns on them: choosing the
  production default method (RETR-001), or validating a retrieval change large
  enough that the judged six cannot be trusted to detect a regression.
* **Cost** — human judgment time, not code.

### RETR-003

**The hybrid/RRF investigation is frozen.** — `DEFERRED`

What six queries established: RRF trades first-rank accuracy for coverage. Both
of its mechanisms appear in every run — it recovers relevant papers one component
buried, *and* it demotes papers the other component alone got right. Overlap
between the components did **not** predict which mechanism dominated: hybrid wins
at top-20 overlaps of 12, 5 and 2 and loses at 7, 2 and 1.

* **Decision** — **no further parameter tuning** — not the fusion constant `k`,
  not the weights, not the candidate depth — until more evaluation evidence
  exists. Tuning against six queries fits noise and then launders it as a result.
* **Trigger to revisit** — with RETR-002.

### RETR-004

**Retrieval is measured at ~2.5k papers only.** — `DEFERRED`

Known limits of the current measurements:

* the benchmark corpus is 2,455 preprints from two sources, all with abstracts;
* **no ANN index ships.** HNSW measured *slower* than exact search at this scale
  (68.2 ms against 61.9 ms), and its risk at scale is that recall degrades
  silently while a filter applied alongside it drops papers the traversal never
  visited. `academious.embeddings.index` builds one on demand when measurement
  justifies it; no migration creates one;
* latency at 100k or 1M vectors is extrapolation — the scan is linear, so roughly
  220 ms at 100k and 2.2 s at 1M, and the decision point for an index sits
  between those;
* no re-ranking, no learning-to-rank, no personalisation (RETR-006).

Notes:

* **Trigger to revisit** — at roughly an order of magnitude more data, or when
  measured semantic latency crosses ~200 ms.
* **Source** — [phase-2-report.md §4](phase-2-report.md#hnsw-made-queries-slower),
  [ADR 0007](adr/0007-halfvec-and-exact-search-first.md).

### RETR-005

**ONNX int8 inference is unimplemented.** — `DEFERRED`

The stack runs stock PyTorch fp32 and measured 1.29–1.41 papers/second against a
Phase 0 estimate of 20–35 that assumed ONNX Runtime int8. Published int8 speedups
run 2.7–3.4x and are the **largest known performance lever**.

* **Risk/impact** — a 6-month backfill is ~194 hours (8.1 days) at the measured
  rate. The daily delta is ~60–65 minutes and interruptible, so daily operation
  is fine and only backfill hurts.
* **Trigger to revisit** — when a backfill is actually scheduled, or when daily
  embedding stops fitting its off-peak window.
* **Source** — [performance.md](performance.md), [cost-model.md](cost-model.md) §8a.

### RETR-006

**No re-ranking, learning-to-rank or personalisation.** — `DEFERRED`

Deliberate. Learning-to-rank in particular waits until there are ≥100k labelled
interactions; there are zero, because there are no users. Personalisation is
Phase 3. Re-ranking has no evidence yet that it would help.

---

## 6. Embeddings and data

### DATA-001

**`specter2-benchmark@v1` ablation vectors remain in the database.** — `DEFERRED`

2,320 rows from the input-strategy ablation, under a model key that is **no
longer a registered profile**. No worker can settle them, so they keep a NULL
source version indefinitely.

* **Why deferred** — retained on purpose. They are the raw evidence behind the
  title-versus-abstract comparison, and deleting evidence to tidy a table is a
  bad trade.
* **Risk/impact** — harmless to correctness; nothing reads that key. The one
  visible effect is that a stale-vector count grouped by `model_key` shows it as
  unversioned.
* **Trigger to revisit** — when storage or maintenance genuinely warrants it, or
  when a metrics view is built that cannot express the exception cleanly.
* **Source** — [embeddings.md](embeddings.md),
  [ADR 0008](adr/0008-embedding-source-versioning.md).

### DATA-002

**No normalised subject taxonomy.** — `BLOCKED`

`SearchFilters.fields` matches `topics[].field`, an OpenAlex concept. The live
corpus is arXiv and bioRxiv only, whose topics carry `{id, label, scheme}` and no
`field` key at all — so a field filter would match nothing on every request,
which is why it is not exposed.

* **Risk/impact** — blocks WEB-003 (feed by field), a named Phase 2 deliverable.
* **Depends on** — SRC-004.
* **Source** — [api.md §2](api.md#filtering).

### DATA-003

**The title-only embedding path is unexercised at volume.** — `BLOCKED`

Papers with no abstract are embedded from the title alone and the fallback is
recorded on the row. The path is unit-tested but has never met real sparse
metadata in bulk, because arXiv and bioRxiv both supply abstracts.

* **Why it matters** — abstract coverage is a *retrieval-quality* problem, not a
  metadata-completeness one. The two input strategies share only 41.7% of their
  top-10 results and agree on the top result for 7 of 12 queries, so a title-only
  paper lands somewhere materially different in vector space.
* **Depends on** — SRC-004; live OpenAlex records frequently have no abstract.

### DATA-004

**The `halfvec` quantisation effect has not been re-checked at scale.** —
`DEFERRED`

float16 storage changed no first result at either measured corpus size, but mean
top-10 overlap fell from 1.000 at 1,120 vectors to 0.992 at 2,320 — one query in
twelve moved a single position inside its top ten.

* **Risk/impact** — the effect *grows with corpus size* and should be measured
  again rather than assumed to stay harmless.
* **Trigger to revisit** — at roughly an order of magnitude more vectors, with
  RETR-004.

### DATA-005

**The cost model still rests on estimated ingestion volumes.** — `DEFERRED`

Phase 1 contact with the live APIs already corrected one assumption by roughly
3.5x: a single arXiv OAI-PMH request for one day of `set=cs` returned 1,300
records against ~11,000/month assumed. Every figure downstream of the volume
assumption is soft.

* **Trigger to revisit** — after a week of real continuous harvesting, re-derive
  from `ingestion_run` counters rather than from estimates.
* **Depends on** — DEPLOY-001; continuous harvesting needs a host that stays up.
* **Source** — [phase-0-report.md §17](phase-0-report.md#17-corrections-from-phase-1-measurements).

---

## 7. Sources and ingestion

### SRC-001

**PubMed connector.** — `DEFERRED`

Named in the Phase 2 roadmap row. NCBI E-utilities: 3 req/s without a key, 10
with a free key; `tool` and `email` must be *registered*, not merely sent; large
jobs are asked to run at weekends or 21:00–05:00 US Eastern, and that is enforced
with IP bans.

* **Risk/impact** — biomedical freshness and volume. The current corpus is
  preprints only, which shapes every retrieval measurement taken so far.
* **Depends on** — an NCBI API key and a registered tool/email.

### SRC-002

**Europe PMC connector.** — `DEFERRED`

The best free full-text source. Roadmap Phase 2.

### SRC-003

**Unpaywall fallback.** — `DEFERRED`

OA resolution today comes from OpenAlex. Unpaywall is the fallback leg of the
resolution chain in [open-access.md](open-access.md).

* **Depends on** — a registered Unpaywall email.

### SRC-004

**OpenAlex harvesting into the live corpus.** — `READY`

The OpenAlex connector exists and is tested against captured fixtures. It is not
running against live data at volume, which is why the corpus is arXiv and bioRxiv
only.

* **Why deferred** — needs an API key (free, but **required since 2026-02-13**;
  keyless is 100 credits/day, demo only) and a sustained harvest, which wants a
  host that stays up.
* **Risk/impact** — the **highest-leverage unblocking item in the data layer**.
  It unblocks DATA-002 (taxonomy) and through it WEB-003 (feed by field),
  exercises DATA-003, adds peer-reviewed non-preprint content the benchmark has
  never seen, and makes DATA-005 answerable.
* **Depends on** — `ACADEMIOUS_OPENALEX_API_KEY`; DEPLOY-001 for a sustained run.

---

## 8. Frontend

### WEB-001

**Visual design is a baseline, not a finished appearance.** — `DEFERRED`

The design system is a deliberate starting point: tokens in
`web/src/styles/tokens.css`, restrained palette, no decoration. Components
reference tokens and do not invent scales, so a later visual pass edits one file
rather than hunting pixel values through pages.

* **Status** — *intentional scope for the milestone that shipped*, and a real
  outstanding item. A dedicated design refinement pass is pending.
* **Trigger to revisit** — before anything public-facing is announced.
* **Related** — WEB-006 and WEB-007 both belong to that pass.

### WEB-002

**Filter UI over the filters `/papers` supports.** — `DONE` (2026-08-31)

`GET /papers` accepts `source`, `preprints`, `peer_reviewed` and `open_access`,
applied in SQL before pagination. The feed now surfaces all four, carried in the
query string so a filtered feed is linkable.

* **Closed by** — `feat: filter the feed by source, type and availability`.
  Frontend only; no backend file changed.
* **What it did not cover** — search, which accepts no filter parameters. That
  asymmetry is stated in the interface and tracked as WEB-010.
* **Source** — [frontend.md §6](frontend.md#6-filtering-the-feed),
  [api.md §2](api.md#filtering).

### WEB-003

**Feed by field.** — `BLOCKED`

A named Phase 2 deliverable. There is nothing to filter by until the corpus
carries a normalised subject taxonomy.

* **Depends on** — DATA-002, and through it SRC-004.

### WEB-004

**SEO and prerendering.** — `DEFERRED`

The Phase 0 decision (§11.7, option a) was SPA now, prerender later, and the API
already returns everything a full page render needs. Paper pages are the only
content with long-tail search demand and are the acquisition surface.

* **Status** — *technical debt taken knowingly*, with the debt's shape recorded
  when it was taken.
* **Risk/impact** — a client-rendered SPA gets essentially zero organic traffic on
  paper pages. Phase 0 risk #10 is "a good feed nobody finds".
* **Scope when picked up** — prerendered indexable public pages, stable canonical
  URLs, titles and descriptions, canonical tags, OpenGraph, scholarly structured
  data, and a sitemap.
* **Depends on** — DEPLOY-005; canonical URLs need the final domain.

### WEB-005

**Offset pagination only.** — `DEFERRED`

Offsets are capped by the backend at 10,000, which PostgreSQL serves by counting
rows. Cheap at 2,455 papers, and the cap is what keeps it cheap.

* **Trigger to revisit** — when corpus size makes deep offsets expensive, or when
  a caller legitimately needs to page past the cap.

### WEB-006

**Search returns a fixed 20 results.** — `DEFERRED`

The backend permits up to 50. No control is exposed.

* **Status** — *intentional scope*, not a defect. It belongs to the design pass,
  where it is a question about the shape of a results page rather than a
  parameter to expose.

### WEB-007

**Colour contrast was set by hand, not verified in a browser.** — `DEFERRED`

`axe` colour-contrast checks are unreliable under jsdom, which has no canvas.
Ratios were computed from the tokens by hand against WCAG AA.

* **Trigger to revisit** — during the design pass (WEB-001), in a real browser, in
  both light and dark schemes.

### WEB-008

**No analytics.** — `WONTFIX`

Nothing is written to cookies, `localStorage` or `sessionStorage`; no search
history is stored; no query is sent to any third party.

* **Why** — a decision, not an omission. Reversing it is a privacy decision to
  take and document deliberately — see SEC-009 and PROD-002.

### WEB-009

**No accounts, saved papers or recommendations.** — `DEFERRED`

Roadmap Phase 3 and Phase 4. Public browsing never requires an account;
authentication gates personalisation only.

### WEB-010

**`/search` accepts no filters, so filtering stops at the feed.** — `DEFERRED`

`GET /papers` takes `source`, `preprints`, `peer_reviewed` and `open_access`.
`GET /search` takes `q` and `limit` only. Any filter UI therefore applies to the
feed and not to search results.

* **Why deferred** — adding filter parameters to `/search` is a backend and
  retrieval change, not a frontend one. Filters apply in SQL before ranking, so a
  filtered search is a different retrieval run, and its interaction with the
  measured ranking would have to be re-verified against the benchmark. That does
  not belong inside a frontend milestone.
* **Risk/impact** — a visible asymmetry: a reader who filters the feed and then
  searches loses the filter. The filter panel states this while any filter is
  active rather than hiding it (WEB-002, shipped 2026-08-31).
* **Trigger to revisit** — when search filtering becomes a stated product
  requirement, most likely with the Phase 3 personalised feed, which needs
  filtered ranking anyway.
* **Source** — `src/academious/api/routers/search.py`; confirmed while
  implementing WEB-002, 2026-08-31.

---

## 9. Product-level and future-feature

The roadmap sequences the product; see
[phase-0-report.md §13](phase-0-report.md#13-phased-implementation-plan). Only
items with open engineering consequences are recorded here.

### PROD-001

**A generative explanation layer changes the threat model.** — `DEFERRED`

Roadmap Phase 5. Gated on SEC-007, which is done *before* the code, not after it.
Also carries Phase 0 provenance obligations — `basis` is NOT NULL, and never
full-text framing when only the abstract was seen — and a hard monthly cost cap.

### PROD-002

**Accounts turn query logs and interest profiles into privacy assets.** —
`DEFERRED`

Roadmap Phase 3. Today a query lives in a URL and a log line records its length.
With accounts, a stored interest profile is personal data and query logs become
far more sensitive than they are now.

* **Consequences to carry in** — SEC-008 (real per-user quotas), SEC-009 (the
  logging decision), DEPLOY-006 (backups must exist before real user data does).
