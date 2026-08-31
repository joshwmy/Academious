# Security of the public read API

This document says which controls exist, which layer owns each of them, and what
remains dependent on deployment. It does not claim the system is secure; that is
not a property software has, and a document asserting it would be the least
trustworthy part of the repository.

Scope: the public surface added in the Phase 2 public-read-API milestone -
`GET /papers`, `GET /papers/{id}`, `GET /search` - plus the middleware and
configuration it introduced.

---

## 1. Threat model

### Assets

| Asset | Why it is worth something |
|---|---|
| PostgreSQL data | The corpus and its integrity. Corruption is unrecoverable without a restore |
| Paper metadata | Public by nature, but bulk extraction is a hosting cost, not a feature |
| Retrieval service | Correctness of ranking; the product |
| SPECTER2 weights | Loaded from an external registry - a supply-chain input |
| Embedding corpus | ~7,200 vectors representing weeks of CPU |
| Host CPU | 4 vCPU shared between API, model inference and the ingest worker |
| Host memory | The model is hundreds of MB resident |
| Availability | A single VPS; there is no second instance to fail over to |
| Internal configuration | Database URL, OpenAlex API key, contact email |
| Logs | Contain user queries, which are a privacy asset |
| Operational endpoints | Corpus size, job health, model state, active profile |
| Model/profile identifiers | Reveal which model and which experiments exist |
| Infrastructure topology | Host names, internal addresses, library versions |

### Attackers

Anonymous internet users; scrapers wanting the corpus cheaply; abusive bots;
denial-of-service clients; input fuzzers; parameter manipulators; attackers
specifically trying to make expensive model calls; attackers trying to infer
internal implementation details; automated vulnerability scanners.

No authenticated users exist, so there is no privilege-escalation surface and no
IDOR surface: every reader is entitled to every paper.

### Trust boundaries

```
Internet                       ← wholly untrusted
    ↓
Caddy (TLS, reverse proxy)     ← trusted; owns TLS, host allowlisting,
    ↓                            request-size caps, ops-endpoint restriction
FastAPI application            ← trusted; owns validation, limits, serialisation
    ↓
validation / rate limit / concurrency gate
    ↓
retrieval service              ← trusted; server-controlled configuration only
    ↓
SPECTER2  +  PostgreSQL        ← trusted; never reachable directly from outside
```

The boundary that matters most is the third: **everything a client sends is data
by the time it reaches retrieval**. No caller-supplied value becomes SQL syntax,
a model identifier, a file path, a URL, or a configuration value.

### Assumptions

1. PostgreSQL is not exposed to the internet; only the API reaches it.
2. Caddy terminates TLS and is the only ingress.
3. The API runs as **one** process. The rate limiter is process-local, and this
   assumption is what makes it a global limit (§3).
4. The frontend is not a trust boundary. Every bound is enforced server-side;
   nothing relies on a client validating anything.
5. Operational endpoints are restricted at the proxy. The application cannot
   enforce that and does not pretend to (§9).

---

## 2. OWASP API Security Top 10 (2023), as it applies here

| Risk | Status | Why |
|---|---|---|
| API1 Broken object-level authorisation | **Not applicable** | No per-object ownership. Every paper is public to every reader |
| API2 Broken authentication | **Not applicable** | No authentication exists. Nothing to bypass |
| API3 Broken object property-level authorisation | **Applicable** | Mitigated: responses are an explicit allowlist, never an ORM row (§7) |
| API4 Unrestricted resource consumption | **Applicable, primary risk** | Mitigated: rate limits, page/query bounds, bounded model concurrency (§3-§5) |
| API5 Broken function-level authorisation | **Partially applicable** | The public surface is read-only; operational endpoints need proxy restriction (§9) |
| API6 Unrestricted access to sensitive business flows | **Partially applicable** | Bulk corpus scraping is the flow worth throttling; rate limits are the control |
| API7 SSRF | **Not exposed** | No endpoint accepts a URL or fetches one (§8) |
| API8 Security misconfiguration | **Applicable** | Mitigated: explicit CORS, security headers, host allowlist, generic errors (§6, §7) |
| API9 Improper inventory management | **Applicable** | Mitigated: one OpenAPI document; public and ops routes tagged distinctly, asserted by test |
| API10 Unsafe consumption of third-party APIs | **Partially applicable** | Ingestion consumes external sources, but not on the public request path |

---

## 3. Rate limiting

`slowapi` (over the `limits` library), applied per endpoint.

| Policy | Default | Setting |
|---|---|---|
| Reads (`/papers`, `/papers/{id}`) | 120 per 60 s | `ACADEMIOUS_RATE_LIMIT_READ_REQUESTS` / `_WINDOW_SECONDS` |
| Search | 20 per 60 s | `ACADEMIOUS_RATE_LIMIT_SEARCH_REQUESTS` / `_WINDOW_SECONDS` |
| Enabled | true | `ACADEMIOUS_RATE_LIMIT_ENABLED` |

### Why those numbers

Measured in this repository, at the Phase 2 corpus of 2,455 papers:

| Method | Mean | Max |
|---|---|---|
| lexical | 160 ms | 548 ms |
| semantic (the default) | 160 ms | 174 ms |
| hybrid | 331 ms | 994 ms |

A paper page is a few milliseconds; a search is ~160 ms of largely CPU-bound
work, dominated by SPECTER2 query encoding. The budgets therefore differ by an
order of magnitude, not by taste. Twenty searches a minute is ~3.2 s of CPU per
client per minute - roughly 5% of one core - which a handful of simultaneous
heavy users can sustain on a 4 vCPU box without starving reads.

### Response

`429` with `{"detail": "Rate limit exceeded. Please slow down."}` and a
`Retry-After` header. `X-RateLimit-Limit`, `-Remaining` and `-Reset` are sent on
successful responses. No policy internals are disclosed.

### Client identity

The socket peer address, and **only** the socket peer address, unless
`ACADEMIOUS_TRUSTED_PROXY_COUNT` is greater than zero.

`X-Forwarded-For` is attacker-controlled. Any client can send
`X-Forwarded-For: 1.2.3.4`, and an application that believes it hands out a
fresh budget on every request - which is a rate limiter that does nothing. When
the setting names *n* trusted proxies, the client is taken as the entry *n* from
the right, because each proxy appends and only the rightmost entries were
written by infrastructure we control. Everything to the left was supplied by the
caller and is not believed.

A request with no identifiable peer is keyed `unknown` - one shared bucket. That
can throttle unrelated callers together, but it cannot hand an unidentified
caller an unlimited budget, which is the failure that matters.

**Production requirement.** With Caddy in front, set
`ACADEMIOUS_TRUSTED_PROXY_COUNT=1`. Leaving it at 0 makes every request appear to
come from the proxy, so all clients share one bucket and the limiter throttles
the whole world at once. Run uvicorn with `--proxy-headers` and
`--forwarded-allow-ips` set to the proxy address.

### Horizontal scaling

**This limiter is process-local.** Counters live in this process's memory.

The approved deployment ([deployment.md](deployment.md)) is one FastAPI container
on one VPS, so a process-local limiter *is* the global limiter there. It stops
being one the moment a second worker or replica exists: *n* workers means *n*
independent budgets and an effective limit of *n* times the configured number.
Counters are also lost on restart, which resets every window.

This is why the limiter is `slowapi` rather than something hand-rolled: migrating
to shared state is a `storage_uri` change (`redis://…`) and nothing else. Redis
is deliberately **not** introduced now - there is one instance, and an
unnecessary stateful dependency is its own availability risk.

---

## 4. Search resource limits

The bounds that keep expensive work bounded, all enforced before the model is
reached:

| Bound | Default | Enforcement |
|---|---|---|
| Query length | 512 characters | FastAPI `max_length`; rejected at validation |
| Query content | ≥ 1 non-whitespace character | Rejected after normalisation |
| Results per search | 1-50 | FastAPI `le`; rejected |
| Page size | 1-100 | FastAPI `le`; rejected |
| Offset | 0-10,000 | FastAPI `le`; rejected |
| Retrieval depth | Server-side only | Not a parameter |

A multi-megabyte `?q=` is rejected by validation and **never reaches the
tokeniser**. It is rejected, not truncated: silent truncation answers a different
question than the one asked, and the product specification does not call for it.
Tests assert that no oversized or blank query reaches the retrieval service.

512 characters suits research queries: the benchmark's own queries are under 50
characters, a discursive research-interest description is a sentence or two, and
SPECTER2 truncates at 512 *tokens* regardless - so a longer string could not
influence the vector even if it were accepted.

---

## 5. Concurrency

Rate limiting caps how often one client may ask. It does not cap how many
requests are in flight, and those are different failures: a hundred clients each
under their own limit can still put a hundred query encodes on four cores at
once, at which point everything slows down together until it all times out.

So the retrieval path runs behind a counting semaphore.

| Control | Default | Setting |
|---|---|---|
| Concurrent searches | 2 | `ACADEMIOUS_SEARCH_MAX_CONCURRENCY` |
| Wait for a slot | 2.0 s | `ACADEMIOUS_SEARCH_QUEUE_TIMEOUT_SECONDS` |

Two, on a 4 vCPU target, because one encode is ~160 ms of largely CPU-bound work
and torch itself uses several threads: headroom for request handling, database
reads and the ingest worker matters more than peak search throughput.

Beyond the wait the request is refused with `503` and `Retry-After`, which bounds
the queue - the alternative is a request that occupies a worker and fails anyway.
The permit is released in a `finally` block, so it returns on success, on
exception and on client disconnect; a leaked permit would shrink capacity
permanently and silently. Tests cover all four paths.

`threading.BoundedSemaphore` rather than an asyncio primitive because the guarded
work is synchronous and CPU-bound (SQLAlchemy, torch) and runs in Starlette's
threadpool; an asyncio semaphore would bound the coroutine that schedules the
work rather than the work itself.

---

## 6. Transport, headers, CORS and hosts

### Which layer owns what

| Control | Owner | Why |
|---|---|---|
| TLS termination, HSTS | **Caddy** | The app cannot see whether TLS terminated in front of it, so it cannot honestly assert HSTS. Available as `ACADEMIOUS_SECURITY_HSTS_ENABLED` only if FastAPI ever becomes the edge |
| Request/URL size caps | **Caddy** | Oversized requests should be dropped before application parsing |
| Connection and read timeouts | **Caddy + uvicorn** | Ownership is transport-level |
| Ops endpoint restriction | **Caddy** | The app has no authentication to enforce it with |
| Response security headers | **FastAPI** | They describe how *this* response must be treated |
| CORS | **FastAPI** | Origin policy is application knowledge |
| Host allowlist | **FastAPI** (optional) | `TrustedHostMiddleware`, off unless configured |

### Headers this application sets

```
X-Content-Type-Options: nosniff
Referrer-Policy: no-referrer
Content-Security-Policy: default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'
Permissions-Policy: geolocation=(), microphone=(), camera=(), interest-cohort=()
Cache-Control: public, max-age=60
```

The CSP is for a JSON API: it loads nothing and frames nothing, so if a response
is ever coaxed into rendering as HTML it is inert. Headers are applied to error
responses too, which is the case usually missed.

### CORS

`ACADEMIOUS_CORS_ALLOWED_ORIGINS`, comma-separated. **Empty by default**, which
allows no browser origin at all - the correct default while no frontend is
deployed. `Access-Control-Allow-Origin: *` is never emitted, credentials are
never allowed, and only `GET` and `OPTIONS` are advertised.

Development sets `http://localhost:5173` (Vite) through the environment; it is
not baked into the application.

### Hosts

`ACADEMIOUS_ALLOWED_HOSTS`, comma-separated. Empty disables host checking so
local development on `localhost`, `127.0.0.1` and a container name keeps working.
Production should set it to the real hostname.

---

## 7. Information disclosure

### Responses

Every public field is declared in `api/schemas.py`. Nothing serialises an ORM
object and nothing splats a row, because the corpus row carries operational
columns - `search_tsv`, `title_norm`, `first_author_surname`, `quality_prior`,
`venue_id`, timestamps - that describe how the system works rather than what the
literature says. An allowlist is the only form of that boundary that stays
correct when a column is added later. Author objects are projected field by
field, so upstream identifiers do not travel.

Never returned: embedding vectors, `model_key` or profile names,
`input_text_hash`, `source_updated_at`, job state, ingestion internals,
filesystem or model paths, stack traces, module or class names. A test asserts
each of these strings is absent from every endpoint's response.

No relevance score is exposed - see [api.md](api.md).

### Errors

Every error is `{"detail": "…"}` and nothing more. Unexpected exceptions become a
fixed `500 Internal server error`; the traceback goes to the log. A test raises
an exception whose message contains a database host, port, username and the word
`password`, and asserts none of it appears in the response body.

Validation errors name the offending parameter and the reason but **do not echo
the value back**. Pydantic's default rendering includes the input, which is a
reflection primitive and tells the caller nothing they did not already know.

### Not exposing retrieval internals

None of the following is accepted from the query string: `method`, `model_key`,
`embedding_profile`, `adapter`, `rrf_k`, semantic or lexical weights, internal
depth, database query mode, device, batch size. All are server configuration. A
test sends every one of them and asserts the retrieval service is called with
exactly `query`, `limit`, the configured method, and the metadata filters.

This is not merely tidiness. A caller who could set `method=hybrid` could force
the most expensive path at will; one who could set `model_key` could select an
experimental profile whose vectors were never validated, or probe which profiles
exist.

**Metadata filters are not retrieval internals** and `/search` accepts the four
`/papers` accepts (WEB-010). The line is what the parameter describes: `source`
and `preprints` describe the papers a reader wants; `method` describes how the
ranker works. The same test asserts the filters arrive at their defaults when
nobody set them, so a smuggled parameter cannot reach retrieval disguised as
one. `retraction` stays server-side: its default keeps withdrawn work out of
ordinary discovery, which is a product decision, not a caller preference.

`source` is free text and reaches a `WHERE` clause as a bound parameter, on both
endpoints. It is not validated against the connector registry - an unknown key
matches nothing, which is the honest answer and avoids publishing the list of
sources that exist. Neither endpoint caps how many `source` values one request
may carry; the request-size limit at Caddy and the 20-per-minute search budget
bound it instead.

---

## 8. AI/ML-specific risk (OWASP GenAI/LLM Top 10)

Academious runs an **embedding model**, not an instruction-following LLM. There
is no prompt, no system message, no tool-calling loop and no agent. Risks are
classified accordingly rather than mitigated by ritual.

| Risk | Classification | Reasoning |
|---|---|---|
| **LLM01 Prompt injection** | **Not currently applicable** | SPECTER2 is a bi-encoder. A query is tokenised and mapped to a 768-dimensional vector; there is no instruction channel, no context to poison and no execution step to hijack. "Ignore previous instructions" is inert text that produces an embedding like any other. Verified: no endpoint can alter configuration, choose a model, execute a tool, read the filesystem, run a shell command, make an outbound request, inject SQL, or change a retrieval code path beyond configured options. **No "prompt injection detector" is implemented**, because keyword matching is not a security control and would imply a capability that does not exist |
| **LLM02 Sensitive information disclosure** | **Applicable** | Mitigated by the response allowlist and generic errors (§7). The specifically AI-shaped variants - leaking vectors, model identifiers or model paths - are asserted absent by test |
| **LLM04 Model denial of service / unbounded consumption** | **Applicable - the primary AI risk here** | Inference is the expensive operation and is reachable anonymously. Mitigated by the stricter search rate limit (§3), query-length and result bounds (§4), and bounded concurrency with a bounded queue (§5) |
| **LLM03 Supply chain** | **Applicable** | Model weights come from an external registry. Mitigated by pinning exact commit revisions (§10) and by `trust_remote_code` remaining false. Dependency scanning in §11 |
| **LLM05 Data and model poisoning** | **Not applicable to this surface** | The public API is strictly read-only. Anonymous callers cannot create or edit papers, submit embeddings, trigger ingestion, enqueue jobs, upload model files, or alter relevance judgments. Poisoning would require access to the ingestion worker or the database, neither of which this milestone exposes. A test asserts that no write verb is routed and that a search changes neither the paper count nor the job count |
| **LLM06 Excessive agency** | **Not applicable** | There is no agent. The model has one capability - turn text into a vector - and no tools, no filesystem access and no network access |
| **LLM07 System prompt leakage** | **Not applicable** | There is no system prompt |
| **LLM08 Vector and embedding weaknesses** | **Partially applicable** | Vectors are never returned, so inversion from API output is not possible. Embedding-inversion research targets access to the vectors themselves; ranking-only output is a far weaker channel. Membership inference through ranking is theoretically possible, but the corpus is public literature, so there is nothing to infer |
| **LLM09 Misinformation** | **Partially applicable, product-level** | The system ranks existing papers and generates no text, so it cannot fabricate a claim. It can surface a retracted or low-quality one, which is why retracted papers are excluded by default and `retraction_status` travels with every result |
| **LLM10 Unbounded consumption** | See LLM04 | |

### Unsafe output handling

No model-generated text is returned. Search responses contain corpus metadata
only. The CSP and `X-Content-Type-Options: nosniff` mean that even paper titles
containing HTML cannot execute if a client mishandles them; escaping in the
frontend remains the frontend's responsibility when it exists.

---

## 9. Operational endpoints

```
/health              minimal, safe to expose
/health/db           reveals corpus size
/metrics/ingestion   reveals source health, error counts, ingestion cadence
/metrics/embeddings  reveals corpus size, model keys, active profile, job queue state
```

`/metrics/*` is genuinely useful reconnaissance: it names the active embedding
profile and every model key that exists, reports queue depth, and reports whether
ingestion is failing.

**This milestone did not expand their exposure**, and they are tagged `ops` in
the OpenAPI document so a proxy rule can find them - a test asserts the tagging
stays accurate, and that public routes carry `papers`/`search` instead.

**Deployment requirement:** restrict `/metrics/*` and `/health/db` at Caddy to
the operator's network or behind basic authentication. Leave `/health` public if
an uptime checker needs it. No authentication architecture is added here; that
would be a larger change than the risk warrants when a proxy rule solves it.

---

## 10. Model artifact trust

| Question | Finding |
|---|---|
| Is the model source expected? | Yes - `allenai/specter2_base` plus the `specter2` (proximity) and `specter2_adhoc_query` adapters, all module constants in `embeddings/specter2.py` |
| Can a user supply a model path or repository? | **No.** Model ids are constants; no request parameter reaches them |
| Can a user switch revision or profile? | **No.** The profile is settings-only, and `model_key` is not a query parameter |
| Is `trust_remote_code` enabled? | **No.** Left at its default of false. These repositories ship weights and a config, not code |
| Is `torch.load` or bare pickle used? | **No.** Loading goes through `transformers`/`adapters`; no `torch.load`, no `pickle` anywhere in `src` |
| Are revisions pinned? | **Now yes** - fixed in this milestone |
| Are local cache paths exposed? | No. `embedding_cache_dir` is settings-only and never serialised |

### Revision pinning

Previously `from_pretrained` was called without `revision`, which fetches
whatever the repository head is on the day it runs. That makes the weights behind
a measured benchmark unreproducible, and turns any upstream change - benign or
hostile - into a silent change in this system's behaviour.

All three loads are now pinned to the exact commits the Phase 2 benchmark was
measured against:

```
allenai/specter2_base         3447645e1def9117997203454fa4495937bfbd83
allenai/specter2              2081559630a80fc5851d8f798a05ba81e9468089
allenai/specter2_adhoc_query  3f4448817028388648a74349ece07af4518ec5bd
```

The weights are unchanged - these are the revisions already in the local cache -
so no re-embedding is required and the benchmark is unaffected.

---

## 11. Security tooling and findings

Run from the dev extra:

```bash
pip-audit                 # dependency vulnerabilities
bandit -q -r src          # static analysis
```

### `pip-audit`: 5 findings, all in `transformers 4.57.6`

Investigated rather than suppressed. Every one requires loading a model from an
attacker-controlled source, which this system cannot be made to do.

| ID | Finding | Applicability |
|---|---|---|
| PYSEC-2025-217 | Deserialisation RCE in the X-CLIP **checkpoint conversion** script | **Not reachable.** No conversion script is run; X-CLIP is never loaded. No fix version exists |
| PYSEC-2026-2288 | `Trainer._load_rng_state()` calls `torch.load()` without `weights_only=True` | **Not reachable.** `Trainer` is never used; nothing here trains |
| PYSEC-2026-2289 | Malicious `config.json` sets `_attn_implementation_internal` to an attacker Hub repo | **Not reachable.** Model ids are constants pinned to exact commits, so upstream cannot introduce that field |
| PYSEC-2026-2290 (×2) | RCE in the LightGlue loading path, `trust_remote_code` overridden by serialised config | **Not reachable.** LightGlue is never loaded, and the advisory describes 5.2.0 |

**Why not upgrade.** Fix versions are 5.0.0, 5.3.0 and 5.5.0. `adapters` (which
provides the SPECTER2 adapter stack) requires `transformers` 4.x, so moving to
5.x would break adapter loading and change embedding behaviour - which the Phase
2 benchmark depends on. The common precondition of every advisory is an untrusted
model source, and pinned constants remove it.

**Revisit trigger:** when `adapters` supports `transformers` 5.x, upgrade both
together and re-run the six-query benchmark before accepting the result.

`torch` and the local `academious` package cannot be audited by `pip-audit` (not
resolvable on PyPI); `torch` is a CPU wheel from the PyTorch index and should be
tracked against PyTorch's own advisories.

### `bandit`: 3 low-severity findings, all false positives

| Location | Rule | Reason it is a false positive |
|---|---|---|
| `core/http.py:76` | B311 pseudo-random | `random.uniform` produces retry backoff jitter. Non-cryptographic by design, and the comment says so |
| `core/http.py:134` | B101 assert | `assert last_error is not None` narrows a type for mypy immediately before `raise last_error`. Not a security check; under `-O` the raise still happens |
| `embeddings/text.py:32` | B105 hardcoded password | `SEP_TOKEN = "[SEP]"` is the BERT separator token, verified against the tokenizer at load. Not a credential |

No high or medium findings. Nothing suppressed with `# nosec`.

### Secret scanning

No secret-scanning service is configured. Checked manually: no credential
literals in `src`, `tests` or `migrations`; `.env` is git-ignored; all
credentials load through `core/config.py` from the environment. The only
committed connection string is the local development default
(`academious:academious@localhost`), a placeholder for a container that is not
internet-reachable.

---

## 12. Residual risks

### Application level

* **The rate limiter is process-local.** Correct for one instance; wrong the
  moment there are two. Migration path documented (§3).
* **No authentication anywhere**, so there is no per-user quota. A distributed
  scraper across many addresses is limited only by aggregate concurrency.
* **Deep offsets are permitted up to 10,000**, which PostgreSQL serves by
  counting rows. Cheap at 2,455 papers; the cap is what keeps it cheap.
* **Search logs record query length, not the query.** If full queries are ever
  logged for analytics, that is a privacy decision to take deliberately and
  document, not to arrive at by default.

### Deployment level

These are **not** solved by this milestone and must be configured. Each is
tracked in [backlog.md](backlog.md) so it survives past this document:

1. Restrict `/metrics/*` and `/health/db` at the proxy - [SEC-003](backlog.md#sec-003).
2. Set `ACADEMIOUS_TRUSTED_PROXY_COUNT=1` behind Caddy, and run uvicorn with
   `--proxy-headers --forwarded-allow-ips=<proxy>` - [SEC-004](backlog.md#sec-004).
3. Set `ACADEMIOUS_ALLOWED_HOSTS` and `ACADEMIOUS_CORS_ALLOWED_ORIGINS` -
   [DEPLOY-004](backlog.md#deploy-004).
4. Terminate TLS and enable HSTS at Caddy - [SEC-005](backlog.md#sec-005).
5. Cap request and URL size, and set connection/read timeouts, at Caddy -
   [SEC-005](backlog.md#sec-005).
6. Keep PostgreSQL off the public internet.
7. Run one API process, or move the limiter to shared storage first -
   [SEC-001](backlog.md#sec-001), [SEC-002](backlog.md#sec-002).

The deployment these assume does not exist yet; see
[DEPLOY-001](backlog.md#deploy-001) for what is running instead.

### Future-feature risks

Not present today; recorded so they are not inherited by accident.

* **A generative answer layer** would make LLM01 prompt injection immediately
  applicable, and would make paper abstracts - attacker-influenced content, since
  anyone can post a preprint - part of the prompt. The API boundary is built so
  that such a layer would be a new endpoint with its own limits, not a flag on
  `/search`.
* **Accounts** introduce API1, API2 and API3 in their real forms.
* **Personalisation** turns a user's stored interest profile into a privacy
  asset, and makes query logs far more sensitive than they are now.
* **User-submitted content** of any kind would introduce data poisoning, which
  today is genuinely out of scope.

---

## 13. What is verified by test

`tests/test_api_security_db.py`, 46 tests: rate limiting including spoofed
`X-Forwarded-For`; concurrency capacity, release on success, exception and
cancellation, and bounded waiting; generic 500 with no internals; response
allowlist and absence of vectors, model keys and operational columns; fourteen
hostile inputs (SQL, XSS, shell, traversal, SSRF-shaped, template, JNDI and
prompt-injection-shaped) proven inert; smuggled retrieval parameters ignored;
read-only enforcement; security headers on success and error paths; CORS allowed
and denied origins; host validation; ops/public route separation.

The injection tests never assert that an input was *detected*. Keyword detection
is not a security control. They assert that the corpus is unchanged, the
configuration is unchanged, and the string arrived at retrieval as text.
