"""Application settings. Environment only; nothing is hardcoded or committed."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ACADEMIOUS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    log_format: Literal["json", "console"] = "json"

    database_url: str = "postgresql+psycopg://academious:academious@localhost:5432/academious"

    # Sent in the User-Agent of every outbound request. Sources require a
    # reachable address; several of them ban anonymous traffic.
    contact_email: str = "unset@example.com"

    openalex_api_key: str = ""
    openalex_filters: str = "primary_topic.domain.id:1|primary_topic.field.id:17"
    # Which date field drives incremental harvesting. `updated_date` is the one
    # we want - it catches corrections and late metadata on records we already
    # hold - but OpenAlex moved it behind a Premium/Institutional/Partner plan
    # and answers a free-tier request for it with 429 and a "Plan upgrade
    # required" body, which reads as a rate limit and is not one.
    #
    # `publication_date` is available on every tier and is the honest fallback:
    # new papers still arrive, but an existing record that gains a DOI or an
    # abstract next week is not re-fetched. Set this back to `updated_date` if
    # the account is ever on a paid plan.
    openalex_incremental_field: str = "publication_date"
    arxiv_sets: str = "cs,stat"
    biorxiv_servers: str = "biorxiv,medrxiv"
    # `;`-separated Europe PMC query expressions, each harvested separately
    # over the update window. The default is the open-access subset, which is
    # what Europe PMC's terms exist to serve; see docs/sources.md before
    # widening it.
    europepmc_queries: str = "OPEN_ACCESS:Y"

    initial_backfill_days: int = 7
    retractionwatch_url: str = "https://api.labs.crossref.org/data/retractionwatch"

    # Fuzzy-dedup thresholds. Deliberately conservative: a missed merge shows a
    # duplicate, a wrong merge destroys a distinct paper. See docs/data-model.md.
    dedup_trigram_block_threshold: float = Field(default=0.60, ge=0.0, le=1.0)
    dedup_title_similarity_threshold: float = Field(default=0.92, ge=0.0, le=1.0)
    dedup_author_jaccard_threshold: float = Field(default=0.50, ge=0.0, le=1.0)

    # --- Embeddings and retrieval (Phase 2) -------------------------------
    # Which stored vectors the read path uses. Changing this switches retrieval
    # to a different model or preprocessing version; see embeddings/registry.py.
    embedding_profile: str = "specter2-proximity@v1"
    # Inference batch. 16 is the measured sweet spot on 4 cores: larger batches
    # stop improving throughput and grow peak RSS (docs/performance.md).
    embedding_batch_size: int = 16
    # 0 leaves torch to pick. Pin it below the core count when embedding shares
    # a machine with the API, so inference cannot starve request handling.
    embedding_torch_threads: int = 0
    # Papers per queued job. Bounds how much work one crash can cost.
    embedding_job_batch_size: int = 32
    # Where HuggingFace weights are cached. Empty uses the HuggingFace default.
    embedding_cache_dir: str = ""
    # Minutes a job may sit in `running` before a worker is presumed dead.
    job_stale_after_minutes: int = 30

    retrieval_default_limit: int = 20
    # Which method the public API searches with. The Phase 2 benchmark makes
    # semantic the strongest single-method aggregate (NDCG@10 0.490 against
    # lexical 0.366 and hybrid 0.472), but it wins 2 of 6 queries, not all of
    # them - so this is an implementation default that env can move, not a
    # settled architectural claim. It is deliberately not a query parameter:
    # see docs/security.md on not exposing retrieval internals.
    retrieval_default_method: Literal["lexical", "semantic", "hybrid"] = "semantic"

    # --- Public API surface (Phase 2 public read API) ---------------------
    # Page sizes are rejected above the maximum rather than clamped: a clamped
    # page silently returns something other than what was asked for, and a
    # client cannot tell that from a short last page.
    api_max_page_size: int = 100
    api_default_page_size: int = 20
    api_max_offset: int = 10_000
    api_max_search_results: int = 50
    # Longest accepted `q`. A research-interest description is a phrase or a
    # sentence; SPECTER2 truncates at 512 *tokens* regardless. Rejecting beyond
    # this keeps oversized input away from the tokeniser entirely.
    api_max_query_length: int = 512

    # Rate limiting. Process-local: correct for the single-container deployment
    # in docs/deployment.md, and documented as such in docs/security.md.
    rate_limit_enabled: bool = True
    rate_limit_read_requests: int = 120
    rate_limit_read_window_seconds: int = 60
    # Search costs ~160 ms of CPU against ~5 ms for a read, so it gets its own,
    # far stricter budget.
    rate_limit_search_requests: int = 20
    rate_limit_search_window_seconds: int = 60

    # How many searches may be inside the retrieval/model path at once. The
    # deployment target is 4 vCPU and one query encode is ~160 ms of largely
    # CPU-bound work, so 2 leaves room for request handling and database reads.
    search_max_concurrency: int = 2
    # How long a request will wait for one of those slots before giving up with
    # 503. Bounds the queue: beyond roughly this many seconds of backlog the
    # honest answer is "busy", not a request that will time out anyway.
    search_queue_timeout_seconds: float = 2.0

    # Trust `X-Forwarded-For` only when the app really is behind this many
    # trusted proxies. 0 means the socket peer is the client, which is the safe
    # default: a spoofed header must never be able to reset a rate limit.
    trusted_proxy_count: int = 0
    # Comma-separated. Empty means "no browser origin is allowed", which is the
    # correct default for an API with no frontend deployed yet.
    cors_allowed_origins: str = ""
    # Comma-separated Host values. Empty disables host checking (development).
    allowed_hosts: str = ""
    # HSTS belongs at the TLS terminator. Enable here only if FastAPI is itself
    # the edge, which the approved topology says it is not.
    security_hsts_enabled: bool = False

    http_timeout_seconds: float = 30.0
    http_max_attempts: int = 5

    @field_validator("arxiv_sets", "biorxiv_servers")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must list at least one value")
        return v

    @property
    def arxiv_set_list(self) -> list[str]:
        return [s.strip() for s in self.arxiv_sets.split(",") if s.strip()]

    @property
    def biorxiv_server_list(self) -> list[str]:
        return [s.strip() for s in self.biorxiv_servers.split(",") if s.strip()]

    @property
    def europepmc_query_list(self) -> list[str]:
        return [q.strip() for q in self.europepmc_queries.split(";") if q.strip()]

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_allowed_origins.split(",") if o.strip()]

    @property
    def allowed_host_list(self) -> list[str]:
        return [h.strip() for h in self.allowed_hosts.split(",") if h.strip()]

    @property
    def user_agent(self) -> str:
        return (
            "Academious/0.1 (+https://github.com/joshwmy/Academious; "
            f"mailto:{self.contact_email})"
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
