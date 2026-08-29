"""Deterministic construction of the text an embedding is computed from.

Two properties matter here and nothing else does:

* **Determinism.** The same paper row must always produce byte-identical text,
  because `input_text_hash` is what tells an embedding run there is no work to
  do. Anything non-deterministic - dict ordering, locale-dependent casing,
  wall-clock - would silently force perpetual re-embedding.
* **Versioning.** When this module's output changes, embeddings computed from
  the old output are stale but not wrong. `INPUT_VERSION` is what makes that
  distinguishable, and it is part of every model_key.

Formatting follows the SPECTER2 reference implementation exactly: title, the
tokenizer's separator token, then abstract. The separator is written as the
literal ``[SEP]``; HuggingFace fast tokenizers recognise special tokens inside
input text, so this produces the same token ids as passing the two fields
separately. `Specter2Backend` asserts its tokenizer agrees.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum

from academious.core.text import clean_display_text, strip_status_prefix

#: Bumped whenever the text produced by this module changes for any input.
INPUT_VERSION = "v1"

#: bert-base-uncased separator. Verified against the tokenizer at backend init.
SEP_TOKEN = "[SEP]"

# An abstract of a handful of characters is a placeholder ("n/a", "Abstract",
# a stray full stop), not content. Feeding it to the model adds noise and,
# worse, records the paper as having had an abstract-quality embedding.
MIN_ABSTRACT_CHARS = 40


class InputStrategy(StrEnum):
    """Which fields actually went into the text."""

    TITLE_ABSTRACT = "title_abstract"
    TITLE_ONLY = "title_only"


class InputMode(StrEnum):
    """What the caller asked for, before availability is taken into account."""

    #: Use the abstract when there is one; fall back to title only when not.
    AUTO = "auto"
    #: Never use the abstract, even when present. Exists so the value of
    #: abstracts can be measured rather than assumed (docs/evaluation.md).
    TITLE_ONLY = "title_only"


@dataclass(frozen=True, slots=True)
class EmbeddingInput:
    text: str
    strategy: InputStrategy
    text_hash: str

    @property
    def is_empty(self) -> bool:
        return not self.text


def _clean(value: str | None) -> str:
    return (clean_display_text(value) or "").strip()


def usable_abstract(abstract: str | None) -> str | None:
    """The abstract if it carries real content, else None."""
    cleaned = _clean(abstract)
    if len(cleaned) < MIN_ABSTRACT_CHARS:
        return None
    return cleaned


def build_embedding_input(
    title: str | None,
    abstract: str | None,
    *,
    mode: InputMode = InputMode.AUTO,
) -> EmbeddingInput:
    """Build the model input for one paper.

    A missing abstract is the normal case, not an error: arXiv OAI records, many
    OpenAlex works and every sparse-metadata record have a title and little
    else. Those papers get a title-only embedding rather than being skipped,
    because a paper absent from the index cannot be discovered at all.

    The title-only form carries no trailing separator. An empty field after a
    separator tells the model 'there was an abstract and it was blank', which is
    not what we mean.
    """
    clean_title = _clean(strip_status_prefix(title or ""))
    abstract_text = None if mode is InputMode.TITLE_ONLY else usable_abstract(abstract)

    if abstract_text:
        text = f"{clean_title}{SEP_TOKEN}{abstract_text}"
        strategy = InputStrategy.TITLE_ABSTRACT
    else:
        text = clean_title
        strategy = InputStrategy.TITLE_ONLY

    return EmbeddingInput(text=text, strategy=strategy, text_hash=hash_text(text))


def hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
