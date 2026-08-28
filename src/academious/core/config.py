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
    arxiv_sets: str = "cs,stat"
    biorxiv_servers: str = "biorxiv,medrxiv"

    initial_backfill_days: int = 7
    retractionwatch_url: str = "https://api.labs.crossref.org/data/retractionwatch"

    # Fuzzy-dedup thresholds. Deliberately conservative: a missed merge shows a
    # duplicate, a wrong merge destroys a distinct paper. See docs/data-model.md.
    dedup_trigram_block_threshold: float = Field(default=0.60, ge=0.0, le=1.0)
    dedup_title_similarity_threshold: float = Field(default=0.92, ge=0.0, le=1.0)
    dedup_author_jaccard_threshold: float = Field(default=0.50, ge=0.0, le=1.0)

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
    def user_agent(self) -> str:
        return (
            "Academious/0.1 (+https://github.com/joshwmy/Academious; "
            f"mailto:{self.contact_email})"
        )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
