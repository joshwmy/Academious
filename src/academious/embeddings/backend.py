"""The embedding backend contract.

Retrieval depends on this Protocol, never on torch. That keeps the whole
retrieval and evaluation stack unit-testable on a machine with no model
downloaded, and it is what lets `HashingBackend` stand in for SPECTER2 in tests
without any mocking framework.

Encoding is asymmetric on purpose. SPECTER2 ships two adapters over one shared
encoder: `proximity` for documents and `adhoc_query` for short textual queries.
A research-interest string is not shaped like a paper, and the model card is
explicit that the query adapter is the right one for it, so the contract has two
methods rather than one.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol, cast, runtime_checkable

import numpy as np

#: Vectors are L2-normalised before storage, so cosine distance is exact and
#: half-precision quantisation error is bounded uniformly across the corpus
#: (values live in [-1, 1], where float16 has ~3 decimal digits). See
#: docs/embeddings.md.
DTYPE = np.float32


@dataclass(frozen=True, slots=True)
class EncodedBatch:
    """Vectors plus what the tokenizer had to say about the inputs."""

    vectors: np.ndarray
    token_counts: list[int]
    truncated: list[bool]

    def __post_init__(self) -> None:
        rows = self.vectors.shape[0]
        if not (rows == len(self.token_counts) == len(self.truncated)):
            raise ValueError(
                f"ragged batch: {rows} vectors, {len(self.token_counts)} token counts, "
                f"{len(self.truncated)} truncation flags"
            )

    def __len__(self) -> int:
        return int(self.vectors.shape[0])


@runtime_checkable
class EmbeddingBackend(Protocol):
    """Turns text into vectors. Implementations must be deterministic."""

    #: Stable identity of the weights, recorded on every row this produces.
    model_id: str
    dimension: int
    max_sequence_length: int

    def encode_documents(self, texts: Sequence[str]) -> EncodedBatch:
        """Encode paper texts (title[SEP]abstract) for storage."""
        ...

    def encode_queries(self, texts: Sequence[str]) -> EncodedBatch:
        """Encode short research-interest queries for retrieval."""
        ...


def l2_normalise(vectors: np.ndarray) -> np.ndarray:
    """Row-wise L2 normalisation. A zero row stays zero rather than becoming NaN."""
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0.0] = 1.0
    return cast("np.ndarray[Any, Any]", (vectors / norms).astype(DTYPE, copy=False))
