"""All ORM models. Importing this module registers every table on Base.metadata."""

from academious.db.base import Base
from academious.db.models.ops import (
    IngestionRun,
    Job,
    JobStatus,
    RunStatus,
    SourceCursor,
)
from academious.db.models.paper import (
    FullTextStatus,
    Paper,
    PaperIdentifier,
    PaperMerge,
    PaperRelation,
    RelationType,
    RetractionStatus,
)
from academious.db.models.support import (
    HostType,
    OaLocation,
    OaVersion,
    RetractionRecord,
    SourceRecord,
    Venue,
)

__all__ = [
    "Base",
    "FullTextStatus",
    "HostType",
    "IngestionRun",
    "Job",
    "JobStatus",
    "OaLocation",
    "OaVersion",
    "Paper",
    "PaperIdentifier",
    "PaperMerge",
    "PaperRelation",
    "RelationType",
    "RetractionRecord",
    "RetractionStatus",
    "RunStatus",
    "SourceCursor",
    "SourceRecord",
    "Venue",
]
