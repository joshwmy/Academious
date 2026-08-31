"""SPECTER2 through ONNX Runtime, optionally quantised to int8.

Same weights, same pooling and same tokeniser as `specter2.py`; a different
execution engine. It exists because embedding throughput is the constraint on
how far back the corpus can reach: at the measured PyTorch fp32 rate a six-month
backfill is over a week of CPU, and published int8 speedups for bert-base run
2.7-3.4x (RETR-005, docs/performance.md).

Two graphs, not one. SPECTER2 switches task adapters in place per call -
`proximity` for documents, `adhoc_query` for queries - and an ONNX graph is
static, so each active adapter is exported separately. `scripts/export_onnx.py`
writes them; this class loads them.

**int8 vectors are not fp32 vectors.** Quantisation changes the numbers, so an
int8 vector and an fp32 vector of the same paper are not the same vector, and a
corpus holding both under one `model_key` would be a corpus whose distances mean
two different things. That is what the key exists to prevent, so the quantised
profile carries its own key and the two are never mixed in one search. See
`registry.py` and docs/embeddings.md.

torch is never imported here. The graph is the model, so this path runs without
the 2 GB torch dependency at all - which is also why it is the cheaper thing to
run beside PostgreSQL on a small box.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np

from academious.core.logging import get_logger
from academious.embeddings.backend import DTYPE, EncodedBatch, l2_normalise
from academious.embeddings.specter2 import (
    BASE_MODEL,
    BASE_MODEL_REVISION,
    DEFAULT_BATCH_SIZE,
    DIMENSION,
    DOCUMENT_ADAPTER_NAME,
    MAX_SEQUENCE_LENGTH,
    QUERY_ADAPTER_NAME,
)
from academious.embeddings.text import SEP_TOKEN

log = get_logger(__name__)

#: Precisions this backend will load. The value is part of the model_id, so a
#: vector always records which one produced it.
PRECISIONS = ("fp32", "int8")

#: Where `scripts/export_onnx.py` writes by default. Build artefacts derived
#: from the pinned upstream revisions, not tracked in git.
DEFAULT_MODEL_DIR = Path("data/onnx")


def graph_path(model_dir: Path, adapter: str, precision: str) -> Path:
    return model_dir / f"specter2-{adapter}-{precision}.onnx"


class OnnxSpecter2Backend:
    """SPECTER2 over ONNX Runtime. Not thread-safe: sessions are created lazily."""

    dimension = DIMENSION
    max_sequence_length = MAX_SEQUENCE_LENGTH

    def __init__(
        self,
        *,
        precision: str = "int8",
        model_dir: Path | str = DEFAULT_MODEL_DIR,
        batch_size: int = DEFAULT_BATCH_SIZE,
        num_threads: int | None = None,
        cache_dir: str | None = None,
        use_query_adapter: bool = True,
    ) -> None:
        if precision not in PRECISIONS:
            raise ValueError(f"precision must be one of {PRECISIONS}, got {precision!r}")
        self.precision = precision
        self.model_dir = Path(model_dir)
        self.batch_size = batch_size
        self.use_query_adapter = use_query_adapter
        self._num_threads = num_threads
        self._cache_dir = cache_dir
        self._tokenizer: Any = None
        self._sessions: dict[str, Any] = {}
        #: Carries the precision, because an int8 vector must never be mistaken
        #: for an fp32 one. A plain attribute rather than a property: the
        #: EmbeddingBackend Protocol declares model_id settable, and a read-only
        #: property does not structurally satisfy it.
        self.model_id = f"allenai/specter2_base+proximity/onnx-{precision}"

    # ------------------------------------------------------------------ load

    def load(self) -> None:
        """Open both graphs and the tokeniser. Idempotent."""
        if self._sessions:
            return

        import onnxruntime as ort
        from transformers import AutoTokenizer

        missing = [
            path
            for path in (
                graph_path(self.model_dir, DOCUMENT_ADAPTER_NAME, self.precision),
                graph_path(self.model_dir, QUERY_ADAPTER_NAME, self.precision),
            )
            if not path.exists()
        ]
        if missing:
            raise FileNotFoundError(
                f"no exported graph at {', '.join(str(path) for path in missing)}. "
                "Run: python scripts/export_onnx.py"
            )

        tokenizer = AutoTokenizer.from_pretrained(
            BASE_MODEL, revision=BASE_MODEL_REVISION, cache_dir=self._cache_dir
        )
        if tokenizer.sep_token != SEP_TOKEN:
            raise RuntimeError(
                f"tokenizer separator is {tokenizer.sep_token!r}, but the embedding text "
                f"builder writes {SEP_TOKEN!r}; the two must agree or stored inputs do not "
                "tokenise as intended"
            )

        options = ort.SessionOptions()
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        if self._num_threads:
            # Pinned below the core count when this shares a machine with the
            # API, for the same reason the torch backend pins its threads.
            options.intra_op_num_threads = self._num_threads

        log.info("embeddings.loading", model=self.model_id, precision=self.precision)
        for adapter in (DOCUMENT_ADAPTER_NAME, QUERY_ADAPTER_NAME):
            self._sessions[adapter] = ort.InferenceSession(
                str(graph_path(self.model_dir, adapter, self.precision)),
                sess_options=options,
                providers=["CPUExecutionProvider"],
            )
        self._tokenizer = tokenizer
        log.info("embeddings.loaded", model=self.model_id, dimension=DIMENSION)

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
        session = self._sessions[adapter]

        vectors = np.zeros((len(texts), DIMENSION), dtype=DTYPE)
        token_counts: list[int] = []
        truncated: list[bool] = []

        for start in range(0, len(texts), self.batch_size):
            chunk = list(texts[start : start + self.batch_size])

            # True lengths first, so truncation is recorded rather than silent.
            lengths = [len(ids) for ids in self._tokenizer(chunk)["input_ids"]]
            token_counts.extend(min(n, MAX_SEQUENCE_LENGTH) for n in lengths)
            truncated.extend(n > MAX_SEQUENCE_LENGTH for n in lengths)

            encoded = self._tokenizer(
                chunk,
                padding=True,
                truncation=True,
                max_length=MAX_SEQUENCE_LENGTH,
                return_tensors="np",
                return_token_type_ids=False,
            )
            outputs = session.run(
                ["embedding"],
                {
                    "input_ids": encoded["input_ids"].astype(np.int64),
                    "attention_mask": encoded["attention_mask"].astype(np.int64),
                },
            )
            vectors[start : start + len(chunk)] = outputs[0].astype(DTYPE, copy=False)

        return EncodedBatch(l2_normalise(vectors), token_counts, truncated)
