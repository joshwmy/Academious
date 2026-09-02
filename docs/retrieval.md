# Retrieval

Three ways to find papers, how they are combined, and what is filtered out
before ranking begins.

Measured latency is in [performance.md](performance.md); quality measurement is
in [evaluation.md](evaluation.md).

**Retrieval is not personalisation.** Everything here is query-driven: the
caller supplies a research-interest description, gets ranked results, and the
system retains nothing about them. There is no user model, no stored interest
and no feedback. In the product direction ([product.md §5](product.md#5-product-hierarchy))
this layer becomes *candidate generation* — the stage that narrows a corpus to
a few thousand plausible papers, which a personalised ranker then orders for one
reader. The interest-description framing below is what makes that transition
natural: a stored interest is the same kind of input as a typed one.

---

## 1. What a query is

The query is a **description of a research interest**, not a paper title and not
a keyword list:

```
machine learning for cancer genomics
transformer models for protein structure and function
Alzheimer's disease biomarkers
```

That framing drives most of what follows. A researcher describing their field
uses different words from the ones a paper uses to title itself, and closing that
gap is exactly what the semantic path is for. It is also why the lexical
baseline needs care: a five-term interest description is not a search box query.

```python
service = RetrievalService(backend=backend, model_key=profile.key)
result = service.search_by_interest(
    session,
    "machine learning for cancer genomics",
    limit=20,
    method="hybrid",
    search_filters=SearchFilters(published_from=date(2025, 1, 1)),
)
```

`RetrievalService` owns the `model_key` and the backend together, so a query
encoded by one model can never be run against vectors from another — a mistake
that produces plausible-looking nonsense rather than an error.

---

## 2. Scores are not percentages

Every hit carries a raw score and a `score_kind` naming its units:

| `score_kind` | Method | Range |
|---|---|---|
| `cosine_similarity` | semantic | `[-1, 1]` |
| `ts_rank_cd` | lexical | `[0, 1)` |
| `reciprocal_rank_fusion` | hybrid | small positive |
| `normalised_weighted_sum` | hybrid | `[0, n_methods]` |

They are deliberately **not** rescaled into a common "relevance percentage".
Cosine similarity and `ts_rank_cd` do not measure the same thing, and mapping
either onto a percentage would invent a precision the system does not have —
"87% relevant" is a claim nothing in the pipeline can support. Ranking is the
product; the score is a diagnostic for engineers.

---

## 3. Lexical retrieval

The baseline the semantic system must beat. Without it, *"the embeddings return
plausible papers"* is an observation about plausibility, not evidence that
SPECTER2 earns its CPU cost. So the baseline is built to be genuinely good.

**No Elasticsearch.** It would add a second datastore, a second index to keep
consistent with `paper`, and an operational surface nothing else in Phase 2
needs. PostgreSQL full-text search covers the baseline role at this corpus size.

### The index

`paper.search_tsv` is a **stored generated column**, so PostgreSQL maintains it
and it cannot drift from the row it describes. A trigger could be bypassed by a
bulk load; a generated column cannot.

| Weight | Field | Reasoning |
|---|---|---|
| `A` | title | A paper that puts a term in its title *is about* that term. |
| `B` | keywords, topic labels | Curated subject terms. |
| `C` | abstract | Richest but noisiest; one term here is weak evidence. |

Weights are applied at query time via the `ts_rank_cd` weight array
`{0.1, 0.2, 0.4, 1.0}` (ordered `{D, C, B, A}`), so changing the relative
importance of title versus abstract needs no reindex.

Normalisation is `1 | 32`: divide by `1 + log(document length)` so long abstracts
do not win on volume, then `rank / (rank + 1)` to bound the score in `[0, 1)`,
which makes it comparable across queries and safe to feed weighted fusion.

Two implementation notes worth knowing:

* **Keywords need a helper function.** PostgreSQL marks `array_to_string()`
  STABLE rather than IMMUTABLE, so a generated column cannot call it, and
  `keywords::text` and `to_jsonb(keywords)::text` are rejected for the same
  reason. `academious_keywords_text(text[])` is a one-line IMMUTABLE wrapper.
  For `text[]` with a constant separator the operation genuinely is immutable —
  the STABLE marking exists for the general `anyarray` case. Without the wrapper,
  keywords could not be indexed at all.
* **Topics can be indexed directly.** `jsonb_path_query_array(topics,
  '$[*].label')::text` *is* immutable. Only `label` is indexed; `field` and
  `domain` are coarse names like *Computer Science* that would match almost
  every query in their discipline and flatten the ranking.

Both definitions live in `academious/db/ddl.py`, shared by the Alembic migration
and the test bootstrap so the two cannot diverge.

### Strict, then relaxed

`websearch_to_tsquery` requires **every** term. That is right for a search box
and wrong for a research interest: *"public health diabetes risk prediction"* as
a conjunction matches almost nothing, and a baseline that returns nothing is not
a baseline, it is a strawman.

So the query runs in two passes:

1. **Strict** — `websearch_to_tsquery`, all terms required.
2. **Relaxed** — only if strict returned nothing. The rendered tsquery has its
   `&` operators rewritten to `|`. Ranking still favours papers matching more
   terms, because that is what `ts_rank_cd` measures.

Rewriting the *rendered* tsquery rather than re-parsing the raw string preserves
everything `websearch_to_tsquery` understood: a quoted phrase stays a phrase
operator, and stemming has already been applied.

The relaxation is **skipped when the query contains a negation**. Turning
`a & !b` into `a | !b` does not loosen the query, it inverts what the exclusion
means. Which pass produced a result is reported in `result.detail["query_mode"]`.

---

## 4. Semantic retrieval

```sql
SELECT p.*, 1 - (e.embedding <=> :query_vector) AS score
FROM paper_embedding e
JOIN paper p ON p.id = e.paper_id
WHERE e.model_key = :model_key
  AND <filters>
ORDER BY e.embedding <=> :query_vector
LIMIT :limit
```

The query is encoded with the ad-hoc query adapter and the corpus with the
proximity adapter — see [embeddings.md](embeddings.md).

Ordering is written as *distance ascending* rather than *similarity descending*
even though they are equivalent, because only the former is a shape an HNSW
index can serve.

### Exact search, on purpose

**No ANN index is created by any migration.** Phase 2 exists to establish what
exact search costs before trading accuracy away, and an index shipping by default
would make that measurement impossible.

Exact search is correct by construction: it reads every vector for the
`model_key`, so recall is 1.0 and a filter can never cost a result. HNSW gives
that up in two ways — it returns approximate neighbours, and a selective filter
applied alongside the index can silently drop relevant papers the graph traversal
never visited.

`academious.embeddings.index` builds and drops the index as an explicit
operational step:

```python
from academious.embeddings import index
index.create_hnsw()             # halfvec_cosine_ops, m=16, ef_construction=64
index.set_search_ef(session, 100)
```

The measured build cost, latency and recall against exact search are in
[performance.md](performance.md), along with the corpus size at which the trade
starts to be worth making.

---

## 5. Hybrid retrieval

Two fusion methods, both deterministic and inspectable — an unexplainable
ranking cannot be debugged and cannot be defended.

### Reciprocal rank fusion (default)

```
score(paper) = Σ  weight_method / (k + rank_method)      k = 60
```

RRF uses only **positions**, so it needs no score calibration and cannot be
destabilised by one method having scores on a different scale. That is the
precise failure mode of naive score addition here, given that `ts_rank_cd` and
cosine similarity share no unit. `k = 60` damps the difference between top
positions, so rank 1 in one method does not automatically outrank a paper that
both methods placed in their top five.

### Normalised weighted sum

Min-max normalises each method's scores within its own result list, then adds
them. It preserves the *margin* between a strong and a marginal match, which rank
fusion discards. That extra information is only worth having when the score
distributions are well behaved, so it is offered but not the default.

A method that returned one result, or all-equal scores, gives every hit `1.0`
rather than `0.0` — it did rank them, it simply did not discriminate, and
zeroing them would silently delete the method from the fusion.

### Candidate pool

Each component contributes `max(5 × limit, 50)` candidates. Fusion can only
reorder what it is given, so a paper that lexical search ranks 40th and semantic
search ranks 3rd is only reachable if lexical actually handed over 40 results.

Ties break on `paper_id`, so identical inputs always produce an identical page.
Every hit carries `components`, the per-method contribution to its score, so a
position can be explained without re-running the query.

**No learning-to-rank.** With no relevance labels yet, a learned ranker would be
fitted to nothing — and producing those labels is what Phase 2 is for.

---

## 6. Filters

Filtering happens in **SQL, before ranking**. Filtering a ranked page in Python
would shrink ten results to three and make recall depend on how aggressive the
filter is, which is the bug that makes date-filtered search feel broken.

| Filter | Field |
|---|---|
| `published_from` / `published_to` | `paper.published_date` |
| `sources` | `EXISTS` over `source_record.source_key` |
| `preprints` | `any` / `only_preprints` / `exclude_preprints` |
| `peer_reviewed_only` | `paper.is_peer_reviewed` |
| `open_access_only` | `paper.oa_status` in gold, green, hybrid, bronze, diamond |
| `fields` | Array overlap on `paper.fields` (GIN, `ix_paper_fields`) |
| `languages` | `paper.language` |
| `retraction` | see below |

`sources` is an `EXISTS` over `source_record` rather than a column on `paper`,
because one canonical paper is routinely assembled from several sources.

`fields` takes normalised slugs - `computer-science`, not OpenAlex's
`Computer Science`. It used to be JSONB containment on `topics[].field`, which
only OpenAlex records carry, so it reached 43% of the corpus while looking
complete. `paper.fields` is derived from every source's vocabulary by
`ingest/taxonomy.py`; see [ADR 0009](adr/0009-normalised-subject-fields.md).

`open_access_only` is an allowlist, not `!= 'closed'`: `unknown` means we do not
know of a legal copy, which is not the same as knowing one exists.

### Retraction policy

This is the one filter with an opinionated default.

| Policy | Behaviour |
|---|---|
| `exclude_retracted` | **Default.** Retracted papers hidden. |
| `include_all` | Everything, retractions included. |
| `only_flagged` | Only papers carrying some notice. Auditing, not discovery. |

A retracted paper is not merely lower quality — the literature has **withdrawn
the claim**. Ranking it silently alongside standing work would present a
repudiated result as a current one, so it is excluded from ordinary discovery
unless explicitly requested.

Corrections and expressions of concern are different. Those papers stand, with a
caveat. They are returned normally and `retraction_status` travels with every
hit, so a caller can surface the caveat rather than having the decision made for
it. Silently hiding a corrected paper would be its own kind of dishonesty.

---

## 7. Command line

There is no user interface in Phase 2, so this is how retrieval is inspected.

```bash
python -m academious.workers search "cancer genomics machine learning"
python -m academious.workers search "graph neural networks" --method lexical
python -m academious.workers search "AI safety evaluation" \
    --from 2025-01-01 --field "Computer Science" --open-access
python -m academious.workers search "hydroxychloroquine" --include-retracted
python -m academious.workers search "hydroxychloroquine" --only-flagged
```

Output shows the raw score, publication date, retraction status and — for hybrid
— each method's contribution, because the point of looking at results by hand is
to see what the ranker did, not a tidied-up version of it.
