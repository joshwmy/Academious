# Embeddings

How a paper becomes a vector, where the vector lives, and what has to happen
before it can be recomputed.

Measured throughput, storage and latency numbers are in
[performance.md](performance.md). This document is about the decisions.

---

## 1. The model

Academious embeds papers with **SPECTER2**, verified against the model cards
rather than carried over from Phase 0 estimates.

| Property | Value |
|---|---|
| Base encoder | `allenai/specter2_base` |
| Architecture | `bert-base-uncased` plus adapters |
| Document adapter | `allenai/specter2` (proximity) |
| Query adapter | `allenai/specter2_adhoc_query` |
| Embedding dimension | 768 |
| Maximum sequence length | 512 tokens |
| Pooling | CLS token of the last hidden state |
| Separator | `[SEP]`, the tokenizer's own separator token |
| Licence | Apache-2.0 |

SPECTER2 is one shared encoder with small task adapters loaded on top. Both
adapters used here sit on the same 440 MB of base weights, so supporting
asymmetric encoding costs a few megabytes rather than a second model.

### Asymmetric encoding

Documents are encoded with the **proximity** adapter; queries with the **ad-hoc
query** adapter. This is not an optimisation, it is what the model was built
for: the proximity adapter is trained for paper-to-paper similarity, and a
research interest such as *"transformer models for protein structure"* is not
shaped like a paper. The model card is explicit that ad-hoc search is the query
adapter's job.

`Specter2Backend(use_query_adapter=False)` switches queries back to the document
adapter, so the choice can be measured rather than asserted. See
[evaluation.md](evaluation.md).

### Why not something else

The alternatives were weighed in Phase 0 and re-checked here. SPECTER2 is
trained on 6M citation triplets from scientific literature, runs on CPU, has
permissive licensing, and produces a 768-dimensional vector that fits
comfortably in a `halfvec` column. A general-purpose sentence embedding model
would need no adapter machinery but has no notion that two papers citing each
other are related, which is the signal SPECTER2 is built on.

---

## 2. The input text

`academious.embeddings.text` builds the string the model sees. It has exactly
two jobs, and both are load-bearing.

**Determinism.** The same paper row must always produce byte-identical text,
because the hash of that text is what tells an embedding run there is nothing to
do. Anything non-deterministic would force perpetual re-embedding of an
unchanged corpus.

**Versioning.** `INPUT_VERSION` changes whenever the output changes for any
input. It is part of every `model_key`, so vectors built from old preprocessing
are distinguishable rather than silently mixed in with new ones.

### Format

Following the SPECTER2 reference implementation exactly:

```
title[SEP]abstract
```

The separator is written as the literal string `[SEP]`. HuggingFace fast
tokenizers recognise special tokens inside input text, so this produces the same
token ids as passing the fields separately. `Specter2Backend.load()` asserts the
tokenizer agrees, and refuses to start if it does not — a silent mismatch here
would degrade every vector in the corpus with no visible symptom.

Before joining, the title has any editorial status prefix removed
(`RETRACTED:`, `Erratum:`, …). That prefix is metadata about the fate of a
paper, not a statement about its subject, and leaving it in would move every
retracted paper in the corpus towards every other one in vector space.

### Papers with no abstract

**Abstracts are not required.** Papers arrive at three levels of detail:

1. title only, or sparse metadata
2. title and abstract
3. richer source or full-text data (later phases)

A paper with no usable abstract is embedded from its title alone, and the row
records `input_strategy = title_only`. It is not skipped: a paper absent from
the index cannot be discovered at all, which is a worse outcome than a weaker
vector.

An abstract shorter than `MIN_ABSTRACT_CHARS` (40) is treated as absent. Sources
supply placeholders — `n/a`, a bare `Abstract`, a stray full stop — and feeding
those to the model adds noise while falsely recording the paper as having had an
abstract-quality embedding.

The title-only form carries **no trailing separator**. `title[SEP]` tells the
model there was an abstract and it was empty, which is not what is meant. This
is a deliberate departure from the reference snippet, which does emit a trailing
separator when the abstract is missing.

### Two strategies, so the question can be answered

The value of abstracts is an empirical question, so both answers are
implementable:

| Profile key | Input |
|---|---|
| `specter2-proximity@v1` | title + abstract, falling back to title only |
| `specter2-title-only@v1` | titles only, even when an abstract exists |

The second exists purely so the corpus can be embedded both ways and compared on
the same benchmark. That comparison has been run: **mean top-10 overlap is
0.417**, and 5 of 12 queries disagree on the top result. Abstracts materially
change what is retrieved, so a title-only paper is genuinely disadvantaged
rather than merely approximated - which is the argument for enriching abstracts
rather than shrugging at their absence. See [evaluation.md](evaluation.md).

---

## 3. Storage

```sql
CREATE TABLE paper_embedding (
    paper_id        uuid         NOT NULL REFERENCES paper(id) ON DELETE CASCADE,
    model_key       varchar(64)  NOT NULL,
    embedding       halfvec(768) NOT NULL,
    dim             integer      NOT NULL,
    input_strategy  varchar(32)  NOT NULL,
    input_text_hash varchar(64)  NOT NULL,
    token_count     integer,
    truncated       boolean      NOT NULL DEFAULT false,
    created_at      timestamptz  NOT NULL,
    updated_at      timestamptz  NOT NULL,
    PRIMARY KEY (paper_id, model_key)
);
CREATE INDEX ix_paper_embedding_model_paper ON paper_embedding (model_key, paper_id);
```

### One vector per canonical paper

The primary key is `(paper_id, model_key)`. A vector is a property of a paper,
not of a user: it does not depend on who is asking, so a per-user copy would
multiply 1.5 KB by the user count and buy nothing. Personalisation is a matter
of *which* vectors a user is compared against and how results are re-ranked, not
of storing the same numbers repeatedly.

Preprints and their published versions are separate `paper` rows (ADR 0004) and
therefore get separate vectors. That is correct: they are different documents
with different abstracts, and the `preprint_of` relation is what ties them
together at read time.

### halfvec, not vector

`halfvec` stores each component as a 16-bit float: **1536 bytes per vector
instead of 3072**. The saving is exactly half, and it applies to the table, any
index over it, the WAL and every page read.

The precision loss is safe here because of a deliberate choice made upstream:
**vectors are L2-normalised before storage**. Every component therefore lies in
`[-1, 1]`, the range where float16 carries about three decimal digits of
precision, so quantisation error is bounded uniformly across the corpus rather
than depending on the magnitude of a vector. Normalising also makes cosine
distance and inner product rank identically.

Whether that precision loss changes what comes back is measured, not assumed —
[performance.md](performance.md) reports top-k agreement between halfvec storage
and float32 arithmetic over the same vectors.

`768` is fixed in the column type on purpose. A model with a different width is
a schema change and should be visible as one, rather than hidden behind a
nullable width column that lets two incompatible vector sets share a table.

### model_key

```
specter2-proximity@v1
└─── model + adapter ──┘ └ input version
```

A `model_key` answers, on its own, *what would we have to do to recompute this?*
Everything that changes the resulting vector is in the key, which means:

* two vectors sharing a key are comparable;
* two vectors with different keys are never mixed in one search — the semantic
  query filters on `model_key` explicitly;
* re-embedding is populating rows under a new key and then switching the read
  path, with the old vectors queryable throughout;
* a partially migrated corpus is a normal state, not a corrupt one.

`academious.embeddings.registry` maps each key to the backend and input mode
that produce it.

---

## 4. Running embedding work

### Idempotency

Work is decided by hash, not by timestamp:

1. Build the text the paper would produce **now**.
2. If a row exists for this `model_key` with the same `input_text_hash`, there
   is nothing to do. Touch `updated_at` and move on — no inference.
3. Otherwise encode and upsert.

Re-running over an already-embedded corpus performs **zero** model inference.

The pending query uses `paper.updated_at > embedding.updated_at` as a cheap
prefilter, but that is not the decision. A paper can be updated in ways that do
not change its embedding text — a citation count refresh, a new OA location.
Those rows reach the hash check, fail it, and are dismissed. Their embedding
timestamp is then bumped, which is what stops them queueing again on every
subsequent pass.

### Resumability

Pending work is a **query**, not a checkpoint:

```sql
SELECT p.id FROM paper p
LEFT JOIN paper_embedding e ON e.paper_id = p.id AND e.model_key = :key
WHERE e.paper_id IS NULL OR p.updated_at > e.updated_at
ORDER BY p.created_at DESC, p.id
```

Newest papers first, because a daily delta matters more than a backlog. There is
no cursor to corrupt: whatever was committed before an interruption stays
committed, and the next run derives the remainder from the state of the database
itself.

One pass takes at most `MAX_PENDING_SCAN` (10,000) ids into memory. Draining a
large backlog therefore takes several runs, which is the intended shape — each
run is bounded and safe to interrupt.

### Jobs

Embedding is queued through the existing `SELECT … FOR UPDATE SKIP LOCKED` queue
(ADR 0002) as `embed_papers` jobs at priority 200, below ingestion. Ingestion has
source-side rate limits it cannot defer; embedding can always wait.

A job payload carries **paper ids**, never a range or an offset. Ids are stable,
so a job means the same thing whenever it eventually runs — including after new
papers have been ingested, which would have shifted any offset window.

Duplicate work is prevented at two levels, because each catches what the other
cannot:

* `dedup_key` stops the same batch being queued twice, which happens when the
  enqueue pass runs again before the previous one has drained.
* `input_text_hash` stops the same paper being re-encoded when it arrives in a
  differently-shaped batch. This is the guarantee that actually matters, because
  it holds no matter how the work was partitioned.

### Crash safety

The worker uses three separate transactions per job:

1. **Claim** — commits alone, so the attempt counter survives a crash. Without
   this, a job that kills its worker every time would retry forever.
2. **Execute** — commits the vectors. Separating this means a failure while
   completing the job cannot throw away the inference.
3. **Complete or fail** — commits last.

A process killed between 2 and 3 leaves the job `running` with its vectors
already saved. `queue.reap_stale` returns it to `pending` after
`ACADEMIOUS_JOB_STALE_AFTER_MINUTES`; it runs again, and the hash check finds
every paper already done — so the retry costs one query, not a re-encode. A job
whose worker keeps dying exhausts `max_attempts` and lands in an explicit
`failed` state rather than looping.

**Embedding failure never damages ingestion.** Embeddings live in their own
table, written in their own transactions. A model that will not load, an
out-of-memory kill or a poison record costs the corpus nothing: papers stay
ingested, stay lexically searchable, and are simply unembedded until the next
run.

### Commands

```bash
# How many papers still need work
python -m academious.workers embed --pending

# Reap stale jobs, queue pending papers, drain the queue
python -m academious.workers embed

# Queue only - does not load the model, so it is cheap to run often
python -m academious.workers embed --enqueue-only

# Bound a run
python -m academious.workers embed --max-papers 2000 --batch-size 32
```

---

## 5. Backends

Retrieval depends on the `EmbeddingBackend` protocol, never on torch. That is
what lets the whole retrieval and evaluation stack run — and be tested — on a
machine with no model downloaded.

| Backend | Purpose |
|---|---|
| `Specter2Backend` | Production. Lazily imports torch inside `load()`. |
| `HashingBackend` | Deterministic hashed bag of words, no dependencies. |

`HashingBackend` is not a mock. It computes a real embedding with sub-linear
term weighting, so texts sharing vocabulary genuinely are closer together and
retrieval orderings are meaningful to assert on. It is emphatically **not** a
semantic model — it has no idea that *neoplasm* and *tumour* are related, which
is the entire point of SPECTER2. Nothing in the test suite asserts semantic
behaviour against it.

The model stack is an optional install:

```bash
pip install -e ".[dev]"          # everything except the model
pip install -e ".[dev,embed]"    # adds torch, transformers, adapters
```

---

## 6. Re-embedding

When preprocessing or the model changes:

1. Bump `INPUT_VERSION`, or add a profile with a new `key`.
2. Run `python -m academious.workers embed --profile <new-key>`. Every paper is
   pending under the new key, so this backfills naturally.
3. Switch `ACADEMIOUS_EMBEDDING_PROFILE` once coverage is complete.
4. Delete the old rows when nothing reads them.

Read and write paths never mix keys, so steps 2 and 3 can be separated by days.
