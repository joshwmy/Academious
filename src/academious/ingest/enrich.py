"""Fill in what one source left out, by asking another about papers we hold.

Harvesting answers *what is new*. This module answers a different question:
*what do we already hold that a source could describe better than the source it
came from?* The two are not the same pass, because the paper is already here -
there is no window to widen that would reach it.

**The gap this exists for.** 48,520 papers in the live corpus carried no subject
field on 2026-09-03, and every one of them came from Europe PMC. Not a mapping
defect: Europe PMC carries MeSH, and MEDLINE only assigns MeSH months after
publication, so the paper arrives long before its classification does. No amount
of work on `ingest/taxonomy.py` reaches a paper that was never classified, and
`scripts/backfill_fields.py` re-derives fields from stored topics, so it cannot
reach one either. What reaches it is a source that classifies on publication -
OpenAlex, where a topic already carries the `field` the vocabulary is built
from. A DOI is the join, and it reaches about 60% of that slice: the part
MEDLINE has indexed, which is the part with a publisher behind it. The rest is
Europe PMC's `PMC` subset, which carries a PMCID and frequently no DOI at all -
DATA-007. Measured on 2026-09-05, the pass took field coverage from 53.5% to
73.8% and left 25,815 papers, 25,480 of them that identifier gap.

**It is ordinary ingestion, not a special path.** A looked-up work goes through
`IngestPipeline.process_record` exactly as a harvested one does, so it is
deduplicated onto the paper it describes, merged under the same field
precedence, scope-checked by the same policy and stored as the same
`SourceRecord`. The consequence worth stating plainly: enrichment does not only
add topics. It merges everything OpenAlex knows - citation counts, open-access
locations, a venue, sometimes a better abstract - because that is what merging
an OpenAlex record means, and pretending otherwise would mean a second, weaker
copy of `merge.apply_candidate`.

**Asking twice is the thing to avoid.** A DOI OpenAlex has never heard of costs
a slot in every future run, and so does one whose work carries no topics. Both
are answered by the same exclusion: a paper that already has an OpenAlex
`SourceRecord` has been asked, so it is not asked again. That makes repeated
runs incremental rather than a re-scan, and `recheck=True` is the deliberate way
to ask again after upstream has had time to catch up.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field

from sqlalchemy import Select, exists, func, inspect, select
from sqlalchemy.orm import Session

from academious.core.logging import get_logger
from academious.db.models.paper import Paper
from academious.db.models.support import SourceRecord
from academious.ingest.pipeline import IngestPipeline, RunCounters
from academious.sources.openalex.client import (
    MAX_OR_VALUES,
    SOURCE_KEY,
    OpenAlexClient,
    is_filterable_doi,
)
from academious.sources.openalex.connector import OpenAlexConnector

log = get_logger(__name__)


@dataclass
class EnrichmentReport:
    """What a pass asked for, what came back, and what it changed.

    The counts that matter are the last two. `gained_fields` is the measurement
    the whole exercise exists to move; `still_without_fields` is the residue,
    and it is reported rather than inferred because a field facet is only
    honest if the share of the corpus it cannot reach is a number.
    """

    #: Papers selected as candidates: no field, a DOI, not yet asked about.
    candidates: int = 0
    #: Candidates whose DOI cannot go in an OR filter without changing it.
    unfilterable_dois: int = 0
    #: DOIs actually sent to OpenAlex.
    requested: int = 0
    #: Works OpenAlex returned. Never more than `requested`, often fewer.
    returned: int = 0
    #: Returned works the ingestion pipeline declined - out of scope, or a
    #: repository deposit with nothing to corroborate it.
    rejected: int = 0
    #: Returned works that founded a *new* paper instead of enriching one.
    #:
    #: Reported rather than prevented. It should be zero: every DOI sent came
    #: out of the corpus, so the work that comes back should match the paper it
    #: was asked about. It can fail to - OpenAlex may answer under a different
    #: canonical DOI, and the title fallback may then not match either - and a
    #: pass that quietly grew the corpus while claiming to classify it would be
    #: worth knowing about. Refusing outright means threading a flag through
    #: `process_record`, which is not worth doing before the number is known to
    #: be anything but zero.
    founded: int = 0
    #: Candidates that had no field before the pass and have one after.
    gained_fields: int = 0
    #: Candidates still carrying no field once the pass had finished with them.
    still_without_fields: int = 0
    #: Candidates that stopped existing during their own batch, because the
    #: work OpenAlex returned carried a second identifier belonging to another
    #: paper we hold and the two were folded together. The row is gone, so it
    #: can be neither counted as classified nor as unclassified - but it is a
    #: real outcome and silently dropping it would make the totals not add up.
    merged_away: int = 0
    per_field: dict[str, int] = field(default_factory=dict)

    @property
    def unmatched(self) -> int:
        """DOIs OpenAlex returned nothing for: it does not index the work."""
        return max(0, self.requested - self.returned)

    def observe(self, had_fields: dict[uuid.UUID, bool], papers: list[Paper]) -> None:
        """Score a batch after its flush. Must run before the commit or rollback.

        A paper can be *gone* by this point: deduplication merges papers, and a
        looked-up work carrying an identifier that belongs to a second paper we
        hold folds the two together - which can delete the very candidate the
        lookup was for. Touching its attributes would raise, so the deleted
        case is checked before anything is read from the row.
        """
        for paper in papers:
            if inspect(paper).deleted:
                self.merged_away += 1
                continue
            if paper.fields:
                if not had_fields.get(paper.id, False):
                    self.gained_fields += 1
                    for slug in paper.fields:
                        self.per_field[slug] = self.per_field.get(slug, 0) + 1
            else:
                self.still_without_fields += 1

    def print(self, *, applied: bool) -> None:
        print()
        print(f"candidates                {self.candidates}")
        if self.unfilterable_dois:
            print(f"  DOI unusable in filter  {self.unfilterable_dois}")
        print(f"DOIs looked up            {self.requested}")
        print(f"  works returned          {self.returned}")
        print(f"  not indexed by OpenAlex {self.unmatched}")
        if self.rejected:
            print(f"  declined by ingestion   {self.rejected}")
        if self.founded:
            print(f"  founded a NEW paper     {self.founded}  <- expected 0")
        verb = "gained a field" if applied else "would gain a field"
        print(f"{verb:<25} {self.gained_fields}")
        print(f"still without a field     {self.still_without_fields}")
        if self.merged_away:
            print(f"merged into another paper {self.merged_away}")

        if self.per_field:
            print()
            print("fields gained (papers)")
            for slug, count in sorted(self.per_field.items(), key=lambda kv: -kv[1]):
                print(f"  {count:>8}  {slug}")


def candidates(*, recheck: bool = False) -> Select[tuple[Paper]]:
    """Papers with a DOI and no field, ordered by id so paging is keyset-stable.

    Keyset rather than offset because applying the pass removes rows from this
    very query: a paper that gains a field stops being a candidate, and an
    offset would then step over the papers that shuffled down into its place.
    """
    stmt = (
        select(Paper)
        .where(Paper.canonical_doi.is_not(None))
        .where(func.cardinality(Paper.fields) == 0)
        .order_by(Paper.id)
    )
    if recheck:
        return stmt
    return stmt.where(
        ~exists().where(
            SourceRecord.paper_id == Paper.id,
            SourceRecord.source_key == SOURCE_KEY,
        )
    )


def count_candidates(session: Session, *, recheck: bool = False) -> int:
    """How many papers the next pass would consider, without fetching them."""
    stmt = candidates(recheck=recheck).order_by(None).with_only_columns(Paper.id)
    return int(session.scalar(select(func.count()).select_from(stmt.subquery())) or 0)


def _pages(
    session: Session, *, recheck: bool, batch_size: int, limit: int | None
) -> Iterator[list[Paper]]:
    after: uuid.UUID | None = None
    taken = 0
    while limit is None or taken < limit:
        size = batch_size if limit is None else min(batch_size, limit - taken)
        stmt = candidates(recheck=recheck).limit(size)
        if after is not None:
            stmt = stmt.where(Paper.id > after)
        batch = list(session.scalars(stmt))
        if not batch:
            return
        after = batch[-1].id
        taken += len(batch)
        yield batch


def enrich_missing_fields(
    session: Session,
    *,
    apply: bool,
    batch_size: int = MAX_OR_VALUES,
    limit: int | None = None,
    recheck: bool = False,
    client: OpenAlexClient | None = None,
    pipeline: IngestPipeline | None = None,
) -> EnrichmentReport:
    """Look up candidate papers in OpenAlex and fold what comes back into them.

    A dry run still makes the requests - it has to, because what a pass would
    change is a fact about OpenAlex's answer rather than about our database -
    and then rolls the transaction back. `readmit_orphaned.py` reads the same
    way, and for the same reason.
    """
    report = EnrichmentReport()
    connector = OpenAlexConnector(client)
    runner = pipeline or IngestPipeline()

    try:
        for batch in _pages(session, recheck=recheck, batch_size=batch_size, limit=limit):
            report.candidates += len(batch)
            had_fields = {paper.id: bool(paper.fields) for paper in batch}

            dois = [paper.canonical_doi for paper in batch if paper.canonical_doi]
            usable = [doi for doi in dois if is_filterable_doi(doi)]
            report.unfilterable_dois += len(dois) - len(usable)
            report.requested += len(set(usable))

            counters = RunCounters()
            for raw in connector.fetch_by_doi(usable):
                report.returned += 1
                declined = counters.records_skipped
                runner.process_record(session, connector, raw, counters)
                if counters.records_skipped > declined:
                    report.rejected += 1
            report.founded += counters.papers_created

            # Flush so the merged topics and the fields derived from them are
            # visible on these objects; the commit or rollback below decides
            # whether they outlive the batch.
            session.flush()
            report.observe(had_fields, batch)

            if apply:
                session.commit()
            else:
                session.rollback()

            log.info(
                "enrich.batch",
                candidates=report.candidates,
                returned=report.returned,
                gained=report.gained_fields,
            )
    finally:
        if client is None:
            connector.close()

    return report
