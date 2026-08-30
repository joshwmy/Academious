"""SPECTER2: the real scientific document encoder.

SPECTER2 is one shared bert-base encoder (`allenai/specter2_base`, 768-d CLS
output, 512-token window, Apache-2.0) plus small task adapters. Two of them
matter here:

    proximity     `allenai/specter2`             documents
    adhoc_query   `allenai/specter2_adhoc_query` short textual queries

Both are loaded onto the same encoder and switched per call, so the 440 MB of
base weights is paid for once. Encoding a research-interest string with the
document adapter would be using the model against its documented design; the
model card is explicit that ad-hoc search is the query adapter's job.

torch and adapters are imported inside `load()`, not at module import. Retrieval
code depends on `EmbeddingBackend`, and nothing outside this module should force
a 2 GB dependency into a process that only wants to run a SQL query.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import numpy as np

from academious.core.logging import get_logger
from academious.embeddings.backend import DTYPE, EncodedBatch, l2_normalise
from academious.embeddings.text import SEP_TOKEN

log = get_logger(__name__)

BASE_MODEL = "allenai/specter2_base"
PROXIMITY_ADAPTER = "allenai/specter2"
QUERY_ADAPTER = "allenai/specter2_adhoc_query"

#: Exact commits, not `main`. An unpinned `from_pretrained` fetches whatever the
#: repository head is on the day it runs, which makes the weights behind a
#: measured benchmark unreproducible and makes a compromised or simply updated
#: upstream repository a silent change to this system's behaviour. These are the
#: revisions the Phase 2 benchmark was measured against.
BASE_MODEL_REVISION = "3447645e1def9117997203454fa4495937bfbd83"
PROXIMITY_ADAPTER_REVISION = "2081559630a80fc5851d8f798a05ba81e9468089"
QUERY_ADAPTER_REVISION = "3f4448817028388648a74349ece07af4518ec5bd"

DOCUMENT_ADAPTER_NAME = "proximity"
QUERY_ADAPTER_NAME = "adhoc_query"

DIMENSION = 768
MAX_SEQUENCE_LENGTH = 512
DEFAULT_BATCH_SIZE = 16


class Specter2Backend:
    """Lazily-loaded SPECTER2 encoder. Not thread-safe: adapters are switched in place."""

    model_id = "allenai/specter2_base+proximity"
    dimension = DIMENSION
    max_sequence_length = MAX_SEQUENCE_LENGTH

    def __init__(
        self,
        *,
        batch_size: int = DEFAULT_BATCH_SIZE,
        num_threads: int | None = None,
        cache_dir: str | None = None,
        use_query_adapter: bool = True,
    ) -> None:
        self.batch_size = batch_size
        # Off, this encodes queries with the document adapter. Kept switchable
        # because the asymmetric setup is the documented design but its benefit
        # on research-interest queries is an empirical question, and
        # docs/evaluation.md reports the measurement rather than assuming it.
        self.use_query_adapter = use_query_adapter
        self._num_threads = num_threads
        self._cache_dir = cache_dir
        self._tokenizer: Any = None
        self._model: Any = None
        self._torch: Any = None

    # ------------------------------------------------------------------ load

    def load(self) -> None:
        """Download (once) and initialise the encoder. Idempotent."""
        if self._model is not None:
            return

        import torch
        from adapters import AutoAdapterModel
        from transformers import AutoTokenizer

        if self._num_threads:
            torch.set_num_threads(self._num_threads)

        log.info("embeddings.loading", model=BASE_MODEL)
        tokenizer = AutoTokenizer.from_pretrained(
            BASE_MODEL, revision=BASE_MODEL_REVISION, cache_dir=self._cache_dir
        )
        if tokenizer.sep_token != SEP_TOKEN:
            raise RuntimeError(
                f"tokenizer separator is {tokenizer.sep_token!r}, but the embedding text "
                f"builder writes {SEP_TOKEN!r}; the two must agree or stored inputs do not "
                "tokenise as intended"
            )

        # `trust_remote_code` is left at its default of False throughout. These
        # repositories ship weights and a config, not code, and a model that
        # needed to execute its author's Python to load would be a different
        # trust decision than the one this project has made.
        model = AutoAdapterModel.from_pretrained(
            BASE_MODEL, revision=BASE_MODEL_REVISION, cache_dir=self._cache_dir
        )
        model.load_adapter(
            PROXIMITY_ADAPTER,
            source="hf",
            revision=PROXIMITY_ADAPTER_REVISION,
            load_as=DOCUMENT_ADAPTER_NAME,
            set_active=True,
        )
        model.load_adapter(
            QUERY_ADAPTER,
            source="hf",
            revision=QUERY_ADAPTER_REVISION,
            load_as=QUERY_ADAPTER_NAME,
            set_active=False,
        )
        model.eval()

        hidden = int(model.config.hidden_size)
        if hidden != DIMENSION:
            raise RuntimeError(f"expected {DIMENSION}-d embeddings, model reports {hidden}")

        self._torch = torch
        self._tokenizer = tokenizer
        self._model = model
        log.info("embeddings.loaded", model=BASE_MODEL, dimension=hidden)

    # --------------------------------------------------------------- encode

    def encode_documents(self, texts: Sequence[str]) -> EncodedBatch:
        return self._encode(texts, DOCUMENT_ADAPTER_NAME)

    def encode_queries(self, texts: Sequence[str]) -> EncodedBatch:
        adapter = QUERY_ADAPTER_NAME if self.use_query_adapter else DOCUMENT_ADAPTER_NAME
        return self._encode(texts, adapter)

    def _encode(self, texts: Sequence[str], adapter: str) -> EncodedBatch:
        if not texts:
            return EncodedBatch(np.zeros((0, DIMENSION), dtype=DTYPE), [], [])

        self.load()
        torch = self._torch
        self._model.set_active_adapters(adapter)

        vectors = np.zeros((len(texts), DIMENSION), dtype=DTYPE)
        token_counts: list[int] = []
        truncated: list[bool] = []

        for start in range(0, len(texts), self.batch_size):
            chunk = list(texts[start : start + self.batch_size])

            # True lengths first, so truncation is recorded rather than silent.
            # The tokenizer is Rust and this pass costs nothing next to BERT.
            lengths = [len(ids) for ids in self._tokenizer(chunk)["input_ids"]]
            token_counts.extend(min(n, MAX_SEQUENCE_LENGTH) for n in lengths)
            truncated.extend(n > MAX_SEQUENCE_LENGTH for n in lengths)

            inputs = self._tokenizer(
                chunk,
                padding=True,
                truncation=True,
                max_length=MAX_SEQUENCE_LENGTH,
                return_tensors="pt",
                return_token_type_ids=False,
            )
            with torch.inference_mode():
                output = self._model(**inputs)
            # SPECTER2 pools by taking the CLS position, per the model card.
            chunk_vectors = output.last_hidden_state[:, 0, :].to(torch.float32).numpy()
            vectors[start : start + len(chunk)] = chunk_vectors

        return EncodedBatch(l2_normalise(vectors), token_counts, truncated)
