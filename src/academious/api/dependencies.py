"""Request-scoped dependencies.

The retrieval service is a process-wide singleton built on first use, not per
request. Constructing one loads SPECTER2 - hundreds of megabytes of weights and
several seconds - so building it per request would make the first search of
every request pay for the model, and building it at import time would make the
API impossible to start (or test) without the model stack installed.

Both are `Depends` overridable, which is what lets endpoint tests exercise the
HTTP contract against a stub instead of running real inference.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator

from sqlalchemy.orm import Session

from academious.core.config import get_settings
from academious.db.session import session_scope
from academious.retrieval.service import RetrievalService

_service: RetrievalService | None = None
_service_lock = threading.Lock()


def get_session() -> Iterator[Session]:
    """A read transaction for one request."""
    with session_scope() as session:
        yield session


def get_retrieval_service() -> RetrievalService:
    """The shared retrieval service, built on first use."""
    global _service
    if _service is None:
        with _service_lock:
            if _service is None:
                from academious.workers import embed as embed_worker

                settings = get_settings()
                profile = embed_worker.resolve_profile(settings.embedding_profile)
                _service = RetrievalService(
                    backend=embed_worker.build(profile), model_key=profile.key
                )
    return _service


def reset_retrieval_service() -> None:
    """Drop the cached service. For tests and for a profile change in a REPL."""
    global _service
    _service = None
