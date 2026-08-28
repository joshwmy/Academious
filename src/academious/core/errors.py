"""Exception hierarchy. Every failure mode a caller may reasonably branch on."""

from __future__ import annotations


class AcademiousError(Exception):
    """Base for every error this application raises deliberately."""


class ConfigError(AcademiousError):
    """Configuration is missing or internally inconsistent."""


class SourceError(AcademiousError):
    """A scholarly source failed. Carries the source key for logging."""

    def __init__(self, source: str, message: str) -> None:
        super().__init__(f"[{source}] {message}")
        self.source = source
        self.message = message


class RateLimitedError(SourceError):
    """Source signalled 429 or an explicit quota exhaustion."""

    def __init__(self, source: str, message: str, retry_after: float | None = None) -> None:
        super().__init__(source, message)
        self.retry_after = retry_after


class TransientSourceError(SourceError):
    """Network failure or 5xx. Retrying later is reasonable."""


class PermanentSourceError(SourceError):
    """4xx other than 429, or an unparseable payload. Retrying will not help."""


class NormalisationError(AcademiousError):
    """A raw record could not be turned into a PaperCandidate."""
