"""A deterministic, dependency-free stand-in for SPECTER2.

This is not a mock in the usual sense: it computes a real hashed bag-of-words
embedding, so vectors for texts that share vocabulary genuinely are closer
together. That means the retrieval, ranking, filtering and evaluation code can
be exercised end to end - with meaningful orderings to assert on - without
downloading 440 MB of weights or importing torch.

What it is not is a semantic model. It has no notion that 'neoplasm' and
'tumour' are related, which is exactly the thing SPECTER2 is for. Nothing in
the test suite should assert semantic behaviour against it.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence

import numpy as np

from academious.embeddings.backend import DTYPE, EncodedBatch, l2_normalise

_TOKEN = re.compile(r"[a-z0-9]+")

DEFAULT_DIMENSION = 768
DEFAULT_MAX_LENGTH = 512


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


class HashingBackend:
    """Hashed bag of words with sub-linear term weighting."""

    def __init__(
        self,
        dimension: int = DEFAULT_DIMENSION,
        max_sequence_length: int = DEFAULT_MAX_LENGTH,
        model_id: str = "hashing-bow",
    ) -> None:
        self.model_id = model_id
        self.dimension = dimension
        self.max_sequence_length = max_sequence_length

    def _encode(self, texts: Sequence[str]) -> EncodedBatch:
        vectors = np.zeros((len(texts), self.dimension), dtype=DTYPE)
        token_counts: list[int] = []
        truncated: list[bool] = []

        for row, text in enumerate(texts):
            tokens = _tokens(text)
            token_counts.append(len(tokens))
            truncated.append(len(tokens) > self.max_sequence_length)
            for token in tokens[: self.max_sequence_length]:
                digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
                value = int.from_bytes(digest, "big")
                index = value % self.dimension
                # Sign from an independent bit keeps unrelated collisions from
                # accumulating in one direction.
                sign = 1.0 if (value >> 63) & 1 else -1.0
                vectors[row, index] += sign

        # Sub-linear scaling, the same reason tf-idf uses log tf: a term
        # repeated twenty times is not twenty times more about the subject.
        vectors = np.sign(vectors) * np.log1p(np.abs(vectors))
        return EncodedBatch(l2_normalise(vectors), token_counts, truncated)

    def encode_documents(self, texts: Sequence[str]) -> EncodedBatch:
        return self._encode(texts)

    def encode_queries(self, texts: Sequence[str]) -> EncodedBatch:
        return self._encode(texts)
