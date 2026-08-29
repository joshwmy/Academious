"""Embedding profiles: the binding between a model_key and how to reproduce it.

A `model_key` stored on a row has to be enough, on its own, to answer "what
would we have to do to recompute this?". A profile is that answer: which
backend, which input mode, which input-builder version. Everything that changes
the resulting vector is in the key, so two vectors sharing a key are comparable
and two vectors with different keys are never mixed in one search.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from academious.embeddings.backend import EmbeddingBackend
from academious.embeddings.text import INPUT_VERSION, InputMode


@dataclass(frozen=True, slots=True)
class EmbeddingProfile:
    key: str
    backend_name: str
    input_mode: InputMode
    input_version: str = INPUT_VERSION
    description: str = ""


#: Production profile: SPECTER2 proximity vectors over title + abstract, falling
#: back to title alone when there is no abstract.
SPECTER2_AUTO = EmbeddingProfile(
    key=f"specter2-proximity@{INPUT_VERSION}",
    backend_name="specter2",
    input_mode=InputMode.AUTO,
    description="SPECTER2 proximity, title[SEP]abstract with title-only fallback",
)

#: Ablation profile. Exists so 'do abstracts actually help retrieval?' can be
#: measured against the same corpus rather than assumed (docs/evaluation.md).
SPECTER2_TITLE_ONLY = EmbeddingProfile(
    key=f"specter2-title-only@{INPUT_VERSION}",
    backend_name="specter2",
    input_mode=InputMode.TITLE_ONLY,
    description="SPECTER2 proximity, titles only - ablation baseline",
)

#: Used by the test suite and by anyone exercising retrieval without torch.
HASHING_AUTO = EmbeddingProfile(
    key=f"hashing-bow@{INPUT_VERSION}",
    backend_name="hashing",
    input_mode=InputMode.AUTO,
    description="Deterministic hashed bag of words - tests and smoke runs only",
)

PROFILES: dict[str, EmbeddingProfile] = {
    profile.key: profile
    for profile in (SPECTER2_AUTO, SPECTER2_TITLE_ONLY, HASHING_AUTO)
}

DEFAULT_PROFILE_KEY = SPECTER2_AUTO.key


def get_profile(key: str) -> EmbeddingProfile:
    try:
        return PROFILES[key]
    except KeyError:
        known = ", ".join(sorted(PROFILES))
        raise KeyError(f"unknown embedding profile {key!r}; known profiles: {known}") from None


def _build_specter2(**kwargs: object) -> EmbeddingBackend:
    from academious.embeddings.specter2 import Specter2Backend

    return Specter2Backend(**kwargs)  # type: ignore[arg-type]


def _build_hashing(**kwargs: object) -> EmbeddingBackend:
    from academious.embeddings.hashing import HashingBackend

    return HashingBackend()


_BUILDERS: dict[str, Callable[..., EmbeddingBackend]] = {
    "specter2": _build_specter2,
    "hashing": _build_hashing,
}


def build_backend(profile: EmbeddingProfile, **kwargs: object) -> EmbeddingBackend:
    """Instantiate the backend a profile names. Weights are loaded lazily."""
    try:
        builder = _BUILDERS[profile.backend_name]
    except KeyError:
        raise KeyError(f"unknown embedding backend {profile.backend_name!r}") from None
    return builder(**kwargs)
