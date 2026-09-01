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
| [SRC-002](#src-002) | Europe PMC connector | DONE | — |
| [SRC-003](#src-003) | Unpaywall fallback | DEFERRED | Phase 2 remainder |
| [SRC-004](#src-004) | OpenAlex harvesting into the live corpus | READY | Phase 2 remainder |
| [SRC-005](#src-005) | Europe PMC's open-access subset is majority tertiary literature | READY | Before WEB-011 |
| [SRC-006](#src-006) | Europe PMC harvest is unscheduled and unmeasured at volume | BLOCKED | With DEPLOY-001 |
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
| [WEB-011](#web-011) | Europe PMC is not offered in the frontend source filter | BLOCKED | With SRC-005 |
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

**ONNX int8 inference.** — `DONE` (2026-09-01) — implemented, measured, **not adopted**

Implemented and measured rather than left as a published estimate. The answer is
that it does not pay for itself: **1.64x, not the 2.7–3.4x the published figures
promised, and it changes the top ten on every benchmark query.**

* **Closed by** — `feat: ONNX Runtime embedding backend, measured against torch`.
* **What was built** — `embeddings/onnx_specter2.py` (a second backend behind the
  existing Protocol, no torch required at run time), `scripts/export_onnx.py`
  (trace, fuse, quantise) and `scripts/benchmark_onnx.py` (throughput, fidelity
  and retrieval agreement in one process).
* **The measurement** — 3.45 papers/s against PyTorch's 2.11 on the same texts
  in the same process; mean cosine 0.991 against the fp32 vectors; 0.875 top-10
  overlap; **0 of 12 queries kept their ordering**. Full table in
  [performance.md §9](performance.md#9-onnx-int8-measured-and-not-adopted).
* **Why that settles it** — 1.64x takes the 6-month backfill from 8.1 days to
  ~5. It still does not fit beside PostgreSQL on the box, so the temporary
  high-CPU instance is still the answer, and that instance costs ~EUR 4.
  Adopting int8 to save EUR 4 would mean re-embedding under a second `model_key`
  and re-running the Phase 2 benchmark to learn whether NDCG@10 survived.
* **What the exercise did establish** — the ONNX fp32 export reproduces PyTorch
  exactly (cosine 1.0, identical top ten on all twelve queries), which is what
  makes the int8 numbers attributable to quantisation alone; and int8 is
  resident in 349 MB against torch's 907 MB, with no torch installed at all.
* **Reopen if** — memory rather than time becomes the binding constraint on the
  deployment box, or a re-measurement on real server hardware shows a materially
  different ratio. The backend and both scripts remain in place for exactly that.
* **Source** — [performance.md §9](performance.md), [cost-model.md](cost-model.md) §8a.

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
* **Two unblocking paths now, not one.** OpenAlex topics carry `field` and
  `domain` (SRC-004). Europe PMC (SRC-002) carries MeSH descriptors under scheme
  `mesh`, which is a real taxonomy but a biomedical one with no `field` key
  either — so whichever arrives first, `SearchFilters.fields` still needs a
  mapping layer rather than a passthrough, and that decision is the work here.
* **Depends on** — a live harvest of SRC-004 or SRC-002.
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
* **First real exercise, 2026-09-01** — the Europe PMC harvest embedded 303
  papers and **24 fell back to title-only** because Europe PMC supplied no
  abstract for them. Small, but it is the first time the path has met sparse
  metadata outside a unit test, and it neither failed nor produced an empty
  vector.
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

**Europe PMC connector.** — `DONE` (2026-09-01) — built and tested, not yet harvested live

* **Closed by** — `feat: Europe PMC connector over the open-access subset`.
* **What was built** — `sources/europepmc/{client,normalise,connector}.py`, four
  payloads captured from the live API in `tests/fixtures/europepmc/`, and 24
  tests across `test_europepmc.py` and `test_harvest_pagination.py`.
* **Scope decision** — `ACADEMIOUS_EUROPEPMC_QUERIES` defaults to
  `OPEN_ACCESS:Y`. Europe PMC's terms prohibit automated bulk download of
  anything outside the open-access subset, and a default that has to be widened
  deliberately is the only version of that rule a scheduler cannot break by
  accident. See [sources.md](sources.md#europe-pmc).
* **What it adds that nothing else does** — MeSH descriptors (topics under
  scheme `mesh`), author affiliations, and peer-reviewed non-preprint records,
  which the corpus has never held. It is the first source to give DATA-002 a
  taxonomy that is not OpenAlex's.
* **What was deliberately left out** — the `Preprint of` link in
  `commentCorrectionList`. The payload's own `note` says it is a title-first
  author match and it carries a citation string rather than a DOI, so promoting
  it to a relation would put a guess in the graph. bioRxiv's `/pubs/` map
  remains the only authoritative link.
* **Verified against live traffic** — one real page, no database: 100 of 100
  records normalised, 87 peer reviewed, 13 preprints, 99 with an abstract, all
  100 with an open-access location. **1 of 100 carried MeSH**, because MEDLINE
  indexes months after publication — which is precisely why the harvest window
  filters on `UPDATE_DATE`: the paper returns when it is indexed.
* **Validated against the development database on 2026-09-01** — four bounded
  runs, 1,203 records fetched, **306 papers** carrying Europe PMC provenance.
  Ingestion, deduplication, provenance and the read API all behave correctly;
  the full evidence is in [sources.md](sources.md#first-live-harvest-2026-09-01)
  and the numbers are summarised under SRC-005.
* **What the harvest proved** — identifier dedup folds a Europe PMC record into
  an existing bioRxiv paper (3 of 3 probed DOIs updated, 0 duplicated) and the
  abstract precedence table then hands the abstract to Europe PMC; a source
  outage mid-run marks the run `failed` and leaves the cursor where it was, so
  nothing is skipped; a re-run hash-skips 480 of 500 records.
* **What it changed** — the stored cursor now carries a fingerprint of the query
  that minted it, not only the window. Two expressions share one `source_cursor`
  row, and a mark replayed against a different expression is not rejected by the
  API, only misapplied. Found by hitting it: a DOI-scoped probe run overwrote
  the open-access window's cursor.
* **Still open** — no *scheduled* harvest (SRC-006), the subset composition
  problem (SRC-005), and the frontend filter (WEB-011). DATA-005's ingestion
  volumes remain estimates.
* **Depends on** — DEPLOY-001 for a sustained run, exactly as SRC-004 does.

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

### SRC-005

**Europe PMC's open-access subset is majority tertiary literature.** — `READY`

The first live harvest ingested 306 papers. **173 of them are NCBI Bookshelf
chapters** — StatPearls and GeneReviews reference articles whose best open-access
location is `europepmc.org/books/NBK…`. 105 carry **no author list at all**,
because a `core` result does not supply one for those records. Journal articles
number 47; preprints 77.

A further 445 records in the same window were conference abstracts from two
journal supplements, correctly rejected at normalisation.

* **Why it matters** — a reader who filters the feed to "Europe PMC" today would
  mostly see clinical reference chapters with no authors, not research
  literature. That is a product-quality problem, not a bug: the connector is
  reporting what the subset contains.
* **Options, none chosen yet** — (a) exclude Bookshelf records at normalisation,
  keyed on `hasBook` / the `NCBI_Bookshelf` site, which is a scope decision
  about tertiary literature and should be made once for every source, not just
  this one; (b) narrow `ACADEMIOUS_EUROPEPMC_QUERIES` so they never arrive;
  (c) keep them and let a `work_type` filter carry the distinction to the
  reader. Option (c) needs WEB-010-style filter plumbing first.
* **Also observed, deliberately not fixed** — two `book-review` records were
  ingested as `work_type: article`. Two records is an edge case, and the same
  scope decision covers it.
* **Blocks** — WEB-011.

### SRC-006

**Europe PMC harvest is unscheduled and unmeasured at volume.** — `BLOCKED`

Four bounded runs of 200–500 records each is not a sustained harvest. The window
holds ~120,000–152,000 open-access records; at 100 records a page and 3 req/s,
that is a job measured in hours, and the ingest rate observed here was
~0.28 s/record, dominated by the database rather than the API.

* **Depends on** — DEPLOY-001. A host that is up is the prerequisite, and this
  entry exists so that a successful bounded run is never mistaken for one.
* **Also unmeasured** — DATA-004 (`halfvec` at scale), DATA-005 (real ingestion
  volumes), RETR-004 (retrieval quality beyond ~2.5k papers) all still want the
  same thing.

## 8. Frontend

### WEB-011

**Europe PMC is not offered in the frontend source filter.** — `BLOCKED`

`SOURCES` in `web/src/lib/filters.ts` lists arXiv, bioRxiv/medRxiv and OpenAlex.
The backend already filters on `source=europepmc` correctly — verified against
the live corpus, 303 papers returned with no duplicates and no serialisation
errors — so this is one line of frontend transcription and nothing more.

* **Why blocked** — SRC-005. The filter is a promise that the source is worth
  filtering to; 57% Bookshelf chapters is not that yet.
* **Not blocked by** — the API. `/papers`, `/papers/{id}` and `/search` were all
  checked against Europe PMC records on 2026-09-01 and were correct.

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
* **What it did not cover** — search, which accepted no filter parameters. That
  asymmetry was closed by WEB-010 on 2026-09-01; the panel's caveat is gone
  because there is no longer anything to caveat.
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

**`/search` accepts no filters, so filtering stops at the feed.** — `DONE` (2026-09-01)

`GET /search` now takes `source`, `preprints`, `peer_reviewed` and `open_access`,
in the same spelling and with the same semantics as `/papers`. The search page
renders the same `FilterPanel`, and submitting a search carries whatever filters
the URL already holds.

* **Closed by** — `feat: filter search results, not just the feed`.
* **Smaller than estimated, and worth recording why.** The deferral assumed a
  retrieval change. There was none: `RetrievalService.search_by_interest` already
  accepted `search_filters` and threaded it through lexical, semantic and hybrid,
  which had been true since Phase 2. Only the router declined to expose it. The
  benchmark re-verification the entry called for reduced to one assertion — that
  an unfiltered search still passes `SearchFilters()` — because a request with no
  filter parameters is unchanged, so every Phase 2 number still describes this
  endpoint.
* **What proves filtering precedes ranking** — a model-marked test builds a
  corpus of alternating preprints and journal articles and asks for three
  preprints. Filtering after ranking would return however many of the top three
  happened to be preprints; filtering before it returns three. That distinction
  is the whole point of doing the work in SQL, so it is asserted rather than
  assumed.
* **Deliberately still not exposed** — `retraction`, whose default keeps
  withdrawn work out of ordinary discovery and is a product decision rather than
  a caller preference; and `published_from` / `published_to`, which
  `SearchFilters` supports but no interface needs yet.
* **Source** — `src/academious/api/routers/search.py`,
  [api.md §4](api.md#4-get-search), [frontend.md §6](frontend.md#6-filtering).

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
