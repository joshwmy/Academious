# The public read API

Three endpoints, unauthenticated, read-only. They are the boundary the web
frontend will be built against, so they are versioned by contract rather than by
URL prefix: fields are added, never repurposed or silently removed.

```
GET /papers          browse the corpus
GET /papers/{id}     one paper in full
GET /search          rank papers against a research interest
```

Interactive documentation is at `/docs`; the schema is at `/openapi.json`.

Operational endpoints (`/health`, `/health/db`, `/metrics/*`) are **not** part of
this contract. They are tagged `ops` and [security.md](security.md) requires the
reverse proxy to restrict them.

---

## 1. What the API is, and is not

It is a projection of the retrieval service measured in Phase 2. It validates
input, bounds cost, calls the service with server-controlled configuration and
serialises the result.

It is **not** a second ranker. Search results arrive in exactly the order
retrieval produced, which is what makes the Phase 2 benchmark evidence about
this endpoint rather than about a library underneath it. A regression test
asserts that equality directly.

Nothing here exposes ORM rows. Every response field is named in
`api/schemas.py`, so adding a column to `paper` cannot widen a public response
by accident.

---

## 2. `GET /papers`

A page of papers, most recently published first.

```http
GET /papers?limit=20&offset=0
```

| Parameter | Type | Default | Bounds |
|---|---|---|---|
| `limit` | int | 20 | 1-100 |
| `offset` | int | 0 | 0-10,000 |
| `source` | string, repeatable | — | e.g. `arxiv`, `biorxiv` |
| `preprints` | enum | `any` | `any`, `only_preprints`, `exclude_preprints` |
| `peer_reviewed` | bool | false | |
| `open_access` | bool | false | |

### Ordering

`published_date DESC, id DESC`.

The date alone is **not** a total order. The corpus holds many papers per day
and PostgreSQL may return ties in any order it likes, so paging on date alone
lets page two repeat rows from page one. The id breaks the tie deterministically.

### Filtering

Filters are applied in SQL before pagination, so `page.total` counts what
matched rather than what was returned. They reuse `retrieval/filters.py`, which
means a filter behaves identically on `/papers` and inside search.

Retracted papers are excluded by default at that layer. Corrected papers and
those under an expression of concern are returned with `retraction_status` set,
because those papers still stand - with a caveat the reader is entitled to see.

**Not implemented: `field`.** The roadmap's "feed by field" needs a normalised
subject taxonomy. `SearchFilters.fields` matches `topics[].field`, which is an
OpenAlex concept, and the current corpus is arXiv and bioRxiv only - its topics
carry `{id, label, scheme}` and no `field` key at all. A field filter would
therefore match nothing on every request. It arrives with OpenAlex ingestion,
not before.

### Response

```json
{
  "page": {"limit": 20, "offset": 0, "total": 2455, "returned": 20, "has_more": true},
  "results": [
    {
      "id": "0d2f8b1e-0000-0000-0000-000000000000",
      "title": "Neural Message Passing on Structural Interaction Graphs",
      "abstract_preview": "We introduce a message-passing scheme…",
      "authors": [{"name": "Lovelace, A.", "position": 0, "orcid": null, "affiliations": []}],
      "published_date": "2026-08-21",
      "published_year": 2026,
      "venue": null,
      "doi": "10.1101/2026.08.21.000000",
      "is_preprint": true,
      "is_peer_reviewed": false,
      "open_access_status": "green",
      "retraction_status": "none",
      "topics": [{"id": "bioinformatics", "label": "bioinformatics", "scheme": "biorxiv"}],
      "citation_count": null
    }
  ]
}
```

---

## 3. `GET /papers/{id}`

```http
GET /papers/0d2f8b1e-0000-0000-0000-000000000000
200

GET /papers/00000000-0000-0000-0000-000000000000
404  {"detail": "Paper not found"}

GET /papers/not-a-uuid
422  {"detail": "path.paper_id: Input should be a valid UUID…"}
```

### Identifier semantics

The path takes the **Academious UUID** - the `id` that `/papers` and `/search`
return. DOIs and arXiv ids appear in the `identifiers` object but are not
accepted here: a DOI identifies a work, several corpus rows can legitimately
carry one (a preprint and its published version are linked, not merged - ADR
0004), and resolving one would have to pick a winner silently.

### Additional fields over a summary

`abstract` (full), `language`, `work_type`, `identifiers`, `open_access`
(status, whether a readable copy is known, best URL, PDF URL, licence),
`retraction_notice_url`.

---

## 4. `GET /search`

```http
GET /search?q=graph+neural+networks&limit=20
```

| Parameter | Type | Default | Bounds |
|---|---|---|---|
| `q` | string | required | 1-512 characters, must contain non-whitespace |
| `limit` | int | 20 | 1-50 |

### Retrieval method

Server configuration (`ACADEMIOUS_RETRIEVAL_DEFAULT_METHOD`), default
`semantic`. **Not a query parameter**, deliberately - see
[security.md](security.md).

Semantic is the strongest single-method aggregate in the Phase 2 benchmark
(NDCG@10 0.490 against lexical 0.366 and hybrid 0.472; MRR 0.806 against 0.667
and 0.639). It is an *implementation default*, not a settled architectural
claim: semantic wins two of the six judged queries, hybrid wins three, and
lexical wins `cs-05` outright. The environment variable is the reversal
mechanism, and the decision is meant to be revisited when the six held-out
benchmark queries are judged.

### Query handling

Whitespace is collapsed, so `graph  neural networks` and `graph neural networks`
are one query. Control characters are replaced with a space rather than deleted,
because deleting them welds the neighbouring words together. The normalised
query is echoed back in `query`.

A query that is empty after normalisation is a 422, not an empty result set: a
whitespace-only query is a client bug, and answering it with `[]` hides that.

### Response

```json
{
  "query": "graph neural networks",
  "count": 3,
  "limit": 20,
  "results": [
    {"rank": 1, "paper": {"id": "…", "title": "…"}},
    {"rank": 2, "paper": {"id": "…", "title": "…"}}
  ]
}
```

### No relevance score

`rank` is the relevance signal. There is deliberately no `score`.

Lexical `ts_rank_cd`, cosine similarity and reciprocal-rank fusion measure
different things on different scales, and the active method is configuration. A
`score` field would therefore change meaning without the response shape
changing, and a client that drew a relevance bar from it would be drawing an
artefact of the method rather than a property of the paper.

---

## 5. Errors

Every error is `{"detail": "…"}`.

| Status | When |
|---|---|
| 404 | No such paper |
| 422 | Invalid parameter - out of bounds, malformed id, blank or oversized query |
| 429 | Rate limit exceeded; carries `Retry-After` |
| 503 | Search is at capacity; carries `Retry-After` |
| 500 | Unexpected. Generic body; the detail is in the server log |

Malformed requests are never answered `200` with an error object.

---

## 6. Limits

| Limit | Default | Setting |
|---|---|---|
| Page size | 100 | `ACADEMIOUS_API_MAX_PAGE_SIZE` |
| Offset | 10,000 | `ACADEMIOUS_API_MAX_OFFSET` |
| Search results | 50 | `ACADEMIOUS_API_MAX_SEARCH_RESULTS` |
| Query length | 512 characters | `ACADEMIOUS_API_MAX_QUERY_LENGTH` |
| Reads | 120 / 60 s per client | `ACADEMIOUS_RATE_LIMIT_READ_*` |
| Searches | 20 / 60 s per client | `ACADEMIOUS_RATE_LIMIT_SEARCH_*` |
| Concurrent searches | 2 | `ACADEMIOUS_SEARCH_MAX_CONCURRENCY` |

Out-of-bounds values are **rejected**, not clamped. A client that asked for
1,000,000 and received 100 cannot distinguish that from a short final page, so
it never learns the request was wrong.

Rationale for the numbers is in [security.md](security.md).

---

## 7. Performance

A page of any size is two queries: one for the rows, one for the total. Search
is one retrieval call plus one query that fetches summaries for the ranked ids.
Neither scales its query count with the size of the page, which is why the
repository selects explicit columns rather than ORM entities - loading `Paper`
objects would fire the `identifiers` and `oa_locations` relationships on every
list request.

Offset pagination is used because it is simple and correct. It degrades at deep
offsets, which is why `offset` is capped at 10,000; at a corpus of 2,455 papers
that cap is far beyond any real client, and keyset pagination is the documented
successor when it stops being.

---

## 8. Known limitations

Tracked in [backlog.md](backlog.md); the IDs below are where the current status
of each lives.

* No `field` filter until an OpenAlex-style taxonomy is ingested (§2) -
  [DATA-002](backlog.md#data-002).
* No filter parameters on `/search`; filtering is a `/papers` capability only -
  [WEB-010](backlog.md#web-010).
* No cursor pagination; offset only, capped.
* No sorting parameter. The feed order is fixed, which removes a class of
  injection surface and a class of pathological query.
* No full-text snippets or highlighting.
* No caching layer. Responses carry `Cache-Control: public, max-age=60` and are
  safe for a CDN to hold, but nothing caches them today.
* Search cost is dominated by SPECTER2 query encoding (~160 ms). Concurrency is
  bounded at 2 rather than optimised.
