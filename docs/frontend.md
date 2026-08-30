# The public frontend

React + TypeScript + Vite, in `web/`. It consumes the public read API described
in [api.md](api.md) and nothing else.

```
web/
  src/
    api/         types mirroring the backend schemas, the HTTP client, errors
    hooks/       useRequest - one request, cancelled when it stops mattering
    components/  AppShell, SearchBar, PaperCard, Pagination, states, primitives
    pages/       FeedPage, SearchPage, PaperPage, NotFoundPage
    lib/         URL safety, formatting
    styles/      design tokens, then global element defaults
    test/        setup, factories, captured API fixtures, a11y and journey tests
```

---

## 1. Development setup

```bash
# Terminal 1 - the API
ACADEMIOUS_CORS_ALLOWED_ORIGINS=http://localhost:5173 \
  uvicorn academious.api.main:app --reload --port 8000

# Terminal 2 - the frontend
cd web
npm install
cp .env.example .env.local     # VITE_API_BASE_URL=http://localhost:8000
npm run dev                    # http://localhost:5173
```

### Local CORS

Backend CORS is **empty by default**, which allows no browser origin at all.
That is deliberate and is not relaxed for development: instead the dev origin is
named explicitly through the environment.

```bash
ACADEMIOUS_CORS_ALLOWED_ORIGINS=http://localhost:5173
```

Vite is pinned to port 5173 (`strictPort: true`) so this value stays correct - a
dev server that silently moved to 5174 would produce CORS failures that look
like backend bugs.

### Scripts

| Command | What it does |
|---|---|
| `npm run dev` | Dev server on 5173 |
| `npm run build` | Typecheck, then production build to `web/dist` |
| `npm run preview` | Serve the built output |
| `npm run typecheck` | `tsc -b` only |
| `npm run lint` | ESLint |
| `npm test` | Vitest, once |

---

## 2. Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `VITE_API_BASE_URL` | same origin | Base URL of the API, no trailing slash |

**Every `VITE_*` value is inlined into the JavaScript bundle at build time and
is public.** It is readable by anyone who opens the site. Never put a secret, a
key, a database URL or a credential there. The public API needs none: it is
unauthenticated by design.

An unset `VITE_API_BASE_URL` means "same origin", which is a valid production
configuration when a reverse proxy serves the static build and the API from one
hostname.

---

## 3. Routes

| Route | Page |
|---|---|
| `/` | Feed. `?offset=` selects the page |
| `/search?q=…` | Search results |
| `/papers/:id` | Paper detail |
| anything else | Not found |

Everything that identifies what you are looking at lives in the URL: the query,
the page offset, the paper. Nothing essential is held only in memory, so back
and forward work, and any view can be linked or bookmarked.

`/search` and `/papers/:id` are code-split, so the feed does not carry them.

---

## 4. API client architecture

```
components  ->  pages  ->  api/client.ts  ->  HTTP
```

Components never call `fetch`. `api/client.ts` is the only module that does, and
it owns the base URL, query-string construction, response typing and error
normalisation. `api/types.ts` transcribes the backend response schemas, so a
field rename upstream becomes a compile error rather than `undefined` in a
paragraph.

Every failure becomes an `ApiError` with a `kind` - `not_found`,
`invalid_request`, `rate_limited`, `capacity`, `server`, `network`, `malformed`.
Pages branch on `kind`, never on message text.

### No data-fetching library

The roadmap named TanStack Query. This milestone uses plain `fetch` behind the
typed client instead, for reasons specific to this API:

* Three read endpoints, no mutations and no cache invalidation. The caching a
  query library provides has little to invalidate.
* **Background refetching would spend the user's rate-limit budget.** The
  backend allows 20 searches a minute per client; refetch-on-focus and
  refetch-on-reconnect are exactly the behaviours that would consume it without
  the user asking for anything.
* The whole client is around 150 lines and does not grow with the number of
  endpoints.

Revisit if mutations, optimistic updates or cross-view cache sharing arrive.

### No automatic retries

The backend answers `429` when a client exceeds its budget and `503` when the
two-slot inference gate is saturated. Retrying those automatically converts
backpressure into a retry storm - the precise failure those controls exist to
prevent. Retrying is a button, and the user decides.

---

## 5. Rate-limit-aware search

The backend budget is 120 reads and 20 searches per minute per client. The
frontend is built not to spend it accidentally:

* **Search on submit, never on keystroke.** Search-as-you-type would exhaust a
  minute's budget in one typed phrase, mostly on prefixes nobody wanted results
  for. A test asserts that typing produces zero requests.
* **One submission, one request.** Asserted by test.
* **No speculative prefetching.** Nothing is fetched before the user asks for it.
* **Obsolete requests are cancelled.** `useRequest` aborts the request in flight
  when the query changes or the user navigates away, so an abandoned search
  stops occupying one of the backend's two inference slots.
* **StrictMode does not double-spend.** React's development double-invocation is
  cancelled by the same cleanup rather than completing twice.

---

## 6. Filtering the feed

`GET /papers` has accepted source, preprint, peer-review and open-access filters
since the API shipped, applied in SQL before pagination so that `total` counts
what matched. The feed now surfaces them.

| Control | Query parameter | Values |
|---|---|---|
| Source | `source`, repeatable | `arxiv`, `biorxiv` (which covers medRxiv), `openalex` |
| Type | `preprints` | `any`, `only_preprints`, `exclude_preprints` |
| Peer-reviewed only | `peer_reviewed` | `true` |
| Open access only | `open_access` | `true` |

### The URL is the state

Filters live in the query string exactly as the offset and the search query do.
`FilterPanel` is fully controlled and holds nothing; `FeedPage` reads the
filters out of the URL, sends them to the API, and writes every change back.
There is therefore one place a filter can be described from, and a filtered feed
is a page you can link to, bookmark and reach again with the back button.

Only values that differ from the backend's own defaults are written, so an
unfiltered feed has a clean URL and an unfiltered request is byte-identical to
the one the feed made before filters existed.

### A hand-edited URL must not become an error page

Everything in the query string is untrusted input. The backend validates its
enums strictly, so `?source=nonsense` would be a 422 - a broken page for what is
really a typo. `parseFilters` drops what it does not recognise instead of
forwarding it: unknown source keys, unknown preprint policies, and any value
other than `true` for the two booleans. Sources are also de-duplicated and
ordered canonically, so two URLs that mean the same thing produce the same
request.

### Changing a filter returns to the first page

Page three of an unfiltered feed is not page three of a filtered one, and there
may be no page three at all. Keeping the offset across a filter change shows an
empty page for results that do exist, so the offset resets to zero. Paging, by
contrast, keeps the filters.

### Applied immediately, unlike search

There is no *Apply* button. The read budget is 120 requests a minute against
roughly 12 ms of database work, so a request per toggle is affordable. Search is
the opposite case - each search costs about 160 ms of SPECTER2 inference against
a 20-per-minute budget - which is why it stays submit-driven. The two controls
behave differently because the work behind them differs by more than an order of
magnitude.

### Filters do not reach search

`GET /search` accepts `q` and `limit` and no filter parameters at all, so a
filter set on the feed does not carry into search results. The panel says so
while any filter is active rather than letting a reader assume otherwise.
Extending filtering to search is a backend and retrieval change - filters apply
before ranking, so a filtered search is a different retrieval run whose
interaction with the measured ranking would need re-verifying against the
benchmark - and is tracked as [WEB-010](backlog.md#web-010).

### Empty is two different situations

No results with no filters set means the corpus has not been populated. No
results with filters set means the filters excluded everything. These read
identically if you only count rows, so they are separate states and the second
one offers a way out.

---

## 7. Design system

Tokens live in `src/styles/tokens.css` and cover typography, a 4px spacing
scale, radii, borders, surfaces, text hierarchy, status colours, content widths
and motion. Components reference tokens; they do not invent scales or hard-code
pixel values.

This is a deliberately restrained baseline sized for a later dedicated design
pass: the structure - reusable primitives, one breakpoint at 40rem, consistent
state components - is meant to survive a full restyle that touches mostly
`tokens.css`.

Dark mode follows `prefers-color-scheme`. `prefers-reduced-motion` removes
transitions and the skeleton pulse.

---

## 8. Security assumptions

The frontend does not weaken any backend control, and it is not a security
boundary itself. Every bound it applies is also enforced server-side.

| Concern | How it is handled |
|---|---|
| XSS | React escapes all rendered text. `dangerouslySetInnerHTML` is used nowhere, and paper metadata is treated as untrusted content. Tested with markup-bearing titles, abstracts, authors and venues |
| Hostile URLs | Every external URL passes `safeExternalUrl`, which allows only `http:` and `https:`. `javascript:`, `data:`, `file:`, `blob:` and anything else render as text, not as links. Tested |
| New tabs | External links carry `rel="noopener noreferrer"` |
| Secrets | Nothing secret exists client-side. The built bundle is audited for connection strings, keys and internal identifiers |
| Retrieval internals | The client sends only `q` and `limit` to `/search`. There is no method, model, profile or fusion parameter to send, and a test asserts the request carries nothing else |
| Operational endpoints | `/health`, `/health/db` and `/metrics/*` are never called. The client has no code path that can reach them |
| Third parties | No analytics, no trackers, no third-party scripts, no external fonts. Everything loads from this origin |
| CSP | The API's `default-src 'none'` applies to API responses. The static frontend is served separately; a CSP for it belongs to whatever serves `dist/` |

### AI boundary

A search query is data. The frontend adds no prompt template, no system prompt,
no generative text, no agent, no tool execution and no model selection - there
is no LLM dependency anywhere in `web/`. The backend's `/search` runs an
embedding model with no instruction channel, and nothing here reinterprets user
text as instructions.

### Privacy

Search queries live in the URL and nowhere else. Nothing is written to cookies,
`localStorage` or `sessionStorage`; no search history is stored; no query is
sent to any third party. The backend logs query *length*, not query text.

---

## 9. Deployment

The build is static: `npm run build` produces `web/dist`.

| Requirement | Detail |
|---|---|
| Hosting | Any static host. The approved topology serves `dist/` from Caddy alongside the API |
| SPA fallback | **Required.** `/papers/:id` and `/search` are client routes with no file behind them, so unmatched paths must fall back to `index.html` or a deep link returns 404 |
| API base URL | Set `VITE_API_BASE_URL` at *build* time, or leave it unset when the proxy serves both from one origin |
| HTTPS | Terminated at the proxy. The frontend assumes it and asserts nothing about it |
| CORS | Set `ACADEMIOUS_CORS_ALLOWED_ORIGINS` to the real frontend origin. Never a wildcard |

Nothing about a specific host is hard-coded, and no infrastructure has been
changed by this milestone.

---

## 10. Known limitations

Each is tracked in [backlog.md](backlog.md), which carries the current status,
the reason it is deferred and what would trigger picking it up.

* **No SEO.** This is a client-rendered SPA, so paper pages are not indexable.
  The Phase 0 decision (section 11.7, option a) was to prerender later; the API
  already returns everything a full page render needs -
  [WEB-004](backlog.md#web-004).
* **Filters stop at the feed.** `/search` accepts no filter parameters, so a
  filter set on the feed does not carry into search results (§6) -
  [WEB-010](backlog.md#web-010).
* **No "feed by field".** The corpus carries no normalised subject taxonomy, so
  there is nothing to filter by - see [api.md](api.md),
  [WEB-003](backlog.md#web-003).
* **Offset pagination only**, capped by the backend at 10,000 -
  [WEB-005](backlog.md#web-005).
* **No result-count control.** Search returns 20; the backend permits up to 50 -
  [WEB-006](backlog.md#web-006).
* **`axe` colour-contrast checks are unreliable under jsdom**, which has no
  canvas. Contrast was set from the tokens by hand and should be re-verified in
  a browser during the design pass - [WEB-007](backlog.md#web-007).
* **Visual design is a deliberate baseline**, not a finished appearance -
  [WEB-001](backlog.md#web-001).
