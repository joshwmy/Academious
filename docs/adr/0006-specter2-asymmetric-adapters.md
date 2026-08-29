# ADR 0006: SPECTER2 with asymmetric adapters for documents and queries

**Status:** Accepted (Phase 2)

## Context

Phase 0 selected SPECTER2 as the paper encoder on the strength of its training
signal — 6M citation triplets from scientific literature — and its CPU-friendly
`bert-base` size. Phase 2 had to turn that into an implementation, and doing so
surfaced a detail the Phase 0 sketch had not accounted for.

SPECTER2 is not one model. It is a shared encoder (`allenai/specter2_base`) plus
task adapters, and the adapters are not interchangeable:

* `allenai/specter2` — **proximity**. Given a paper, retrieve related papers.
* `allenai/specter2_adhoc_query` — **ad-hoc query**. Given a short textual
  query, retrieve papers.

The core Academious query is a description of a research interest — *"machine
learning for cancer genomics"* — which is not shaped like a paper. Encoding it
with the proximity adapter would use the model against its documented design.

## Decision

Encode **documents with the proximity adapter and queries with the ad-hoc query
adapter**, over one shared instance of the base encoder.

Store L2-normalised CLS embeddings. Build the input text as
`title[SEP]abstract`, falling back to `title` alone — with no trailing separator
— when there is no usable abstract.

## Consequences

* Both adapters load onto the same 440 MB of base weights, so the asymmetry
  costs a few megabytes of adapter parameters, not a second model.
* `EmbeddingBackend` needs two methods, `encode_documents` and `encode_queries`,
  rather than one `encode`. Every caller must therefore say which side of the
  comparison it is on, which is the point: a symmetric API would make the wrong
  choice the easy one.
* The backend asserts `tokenizer.sep_token == "[SEP]"` at load and refuses to
  start otherwise. A silent separator mismatch would degrade every vector in the
  corpus with no visible symptom.
* The choice is switchable (`Specter2Backend(use_query_adapter=False)`) so that
  it can be measured on the benchmark rather than taken on faith.
* `adapters` pins `transformers~=4.57.6`. That is a real constraint on upgrading
  the model stack, and it is why the stack is an optional `embed` extra rather
  than a hard dependency — nothing but embedding generation needs it.
* Papers with no abstract are embedded rather than skipped. A weaker vector is
  strictly better than absence from the index, because a paper that is not in
  the index cannot be discovered at all.
