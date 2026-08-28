"""Phase 1 acceptance demonstration.

Runs the real pipeline, against a real PostgreSQL, over payloads captured from
the live OpenAlex, arXiv, bioRxiv and Retraction Watch APIs during Phase 0. No
network access is needed to reproduce it.

    docker compose up -d db
    export ACADEMIOUS_DATABASE_URL=postgresql+psycopg://user:pass@localhost/academious_demo
    python scripts/demo_phase1.py

Each numbered section corresponds to one Phase 1 acceptance criterion.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

FIXTURES = ROOT / "tests" / "fixtures"
WHEN = datetime(2026, 8, 28, tzinfo=UTC)
LANCET_DOI = "10.1016/s0140-6736(20)31180-6"


def banner(number: str, title: str) -> None:
    print(f"\n{'=' * 78}\n{number}. {title}\n{'=' * 78}")


def ok(message: str) -> None:
    print(f"  [PASS] {message}")


def info(message: str) -> None:
    print(f"         {message}")


def load_json(*parts: str):
    return json.loads(FIXTURES.joinpath(*parts).read_text(encoding="utf-8"))


def load_text(*parts: str) -> str:
    return FIXTURES.joinpath(*parts).read_text(encoding="utf-8")


def main() -> int:
    os.environ.setdefault(
        "ACADEMIOUS_DATABASE_URL",
        "postgresql+psycopg://academious:academious@localhost:5432/academious_demo",
    )
    os.environ.setdefault("ACADEMIOUS_LOG_LEVEL", "WARNING")

    from sqlalchemy import create_engine, func, select, text

    from academious.core.config import get_settings
    from academious.db.models import Base, OaLocation, Paper, PaperRelation, SourceRecord
    from academious.ingest import retractions
    from academious.ingest.pipeline import IngestPipeline, load_cursor
    from academious.sources.arxiv.client import parse_list_records
    from academious.sources.arxiv.normalise import normalise as normalise_arxiv
    from academious.sources.base import RawRecord
    from academious.sources.biorxiv.normalise import normalise as normalise_biorxiv
    from academious.sources.openalex.normalise import normalise as normalise_openalex
    from academious.sources.retractionwatch.client import parse_csv

    sys.path.insert(0, str(ROOT))
    from tests.factories import StubConnector

    settings = get_settings()

    # Create the demo database if it is not there yet, so the script is a
    # one-command reproduction from a bare `docker compose up -d db`.
    admin_url = settings.database_url.rsplit("/", 1)[0] + "/postgres"
    database_name = settings.database_url.rsplit("/", 1)[1]
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        exists = connection.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": database_name}
        ).first()
        if not exists:
            connection.execute(text(f'CREATE DATABASE "{database_name}"'))
    admin.dispose()

    engine = create_engine(settings.database_url)
    with engine.begin() as connection:
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)

    from sqlalchemy.orm import sessionmaker

    make_session = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    pipeline = IngestPipeline(settings)

    def raw(source: str, source_id: str, payload: dict) -> RawRecord:
        return RawRecord(source, source_id, payload, WHEN)

    def openalex_raw(name: str) -> RawRecord:
        work = load_json("openalex", f"{name}.json")
        return raw("openalex", work["id"], work)

    def arxiv_raw() -> RawRecord:
        records, _ = parse_list_records(load_text("arxiv", "getrecord_1706.03762.xml"))
        return raw("arxiv", records[0]["id"], records[0])

    def biorxiv_raw() -> RawRecord:
        payload = load_json("biorxiv", "details_integron.json")["collection"][-1]
        return raw("biorxiv", "10.1101/2022.09.11.507474v2", {**payload, "server": "biorxiv"})

    failures = 0

    def check(condition: bool, message: str) -> None:
        nonlocal failures
        if condition:
            ok(message)
        else:
            failures += 1
            print(f"  [FAIL] {message}")

    # ---------------------------------------------------------------- 1
    banner("1", "Ingest a paper")
    with make_session() as session:
        run = pipeline.run(
            session,
            StubConnector(
                "openalex", [[openalex_raw("work_published_integron")]], normalise_openalex
            ),
            since=None,
        )
        session.commit()
        paper = session.execute(select(Paper)).scalars().one()
        info(f"title:   {paper.title[:66]}")
        info(f"doi:     {paper.canonical_doi}")
        info(f"venue:   {session.get(type(paper), paper.id).venue_id is not None}")
        info(f"authors: {len(paper.authors)}  first surname: {paper.first_author_surname}")
        check(run.status == "succeeded", f"run status is {run.status}")
        check(run.papers_created == 1, "one paper created")
        check(paper.canonical_doi == "10.1038/s41564-023-01548-y", "canonical DOI stored")

    # ---------------------------------------------------------------- 2
    banner("2", "Ingest the same paper from a second source, and recognise it as one paper")
    with make_session() as session:
        before = session.execute(select(func.count()).select_from(Paper)).scalar_one()
        pubmed_style = {
            "id": "https://openalex.org/W_DUPLICATE",
            "doi": "https://doi.org/10.1038/S41564-023-01548-Y",
            "title": "Integron cassettes integrate into bacterial genomes via attG sites",
            "type": "article",
            "publication_date": "2024-01-03",
            "abstract_inverted_index": {"Integrons": [0], "are": [1], "mobile": [2]},
            "ids": {"pmid": "https://pubmed.ncbi.nlm.nih.gov/38172619"},
            "authorships": [{"author": {"display_name": "Céline Loot"}}],
            "open_access": {"oa_status": "green"},
        }
        pipeline.run(
            session,
            StubConnector(
                "openalex", [[raw("openalex", pubmed_style["id"], pubmed_style)]],
                normalise_openalex,
            ),
            since=None,
        )
        session.commit()
        after = session.execute(select(func.count()).select_from(Paper)).scalar_one()
        paper = session.execute(select(Paper)).scalars().one()
        identifiers = sorted((i.id_type, i.value) for i in paper.identifiers)
        info(f"papers before: {before}   after: {after}")
        for id_type, value in identifiers:
            info(f"identifier: {id_type:9} {value}")
        info(f"abstract now present: {paper.abstract is not None}")
        check(after == 1, "the second source did not create a duplicate")
        check(
            ("doi", "10.1038/s41564-023-01548-y") in identifiers
            and ("pmid", "38172619") in identifiers,
            "identifiers from both sources attached to one canonical paper",
        )

    # ---------------------------------------------------------------- 3
    banner("3", "Connect a preprint to its published version")
    with make_session() as session:
        pipeline.run(
            session, StubConnector("biorxiv", [[biorxiv_raw()]], normalise_biorxiv), since=None
        )
        session.commit()
        relation = session.execute(select(PaperRelation)).scalars().first()
        papers = session.execute(select(Paper)).scalars().all()
        info(f"papers now: {len(papers)} (preprint and published are separate records)")
        if relation is not None:
            preprint = session.get(Paper, relation.from_paper_id)
            published = session.get(Paper, relation.to_paper_id)
            info(f"preprint : {preprint.canonical_doi}  ({preprint.title[:44]})")
            info(f"published: {published.canonical_doi}  ({published.title[:44]})")
            info(f"relation : {relation.relation_type} (from {relation.source_key})")
            info(f"published.is_preprint is now {published.is_preprint}")
        check(len(papers) == 2, "preprint and published version kept as separate records")
        check(relation is not None, "preprint_of relation created")
        check(
            relation is not None
            and session.get(Paper, relation.from_paper_id).canonical_doi
            == "10.1101/2022.09.11.507474",
            "relation points from the bioRxiv preprint to the Nature Microbiology article",
        )

    # ---------------------------------------------------------------- 4
    banner("4", "Capture open-access metadata")
    with make_session() as session:
        pipeline.run(
            session,
            StubConnector(
                "openalex",
                [[openalex_raw("work_retracted_lancet")]],
                normalise_openalex,
            ),
            since=None,
        )
        session.commit()
        lancet = session.execute(
            select(Paper).where(Paper.canonical_doi == LANCET_DOI)
        ).scalars().one()
        locations = session.execute(
            select(OaLocation).where(OaLocation.paper_id == lancet.id)
        ).scalars().all()
        info(f"oa_status: {lancet.oa_status}   fulltext_status: {lancet.fulltext_status}")
        for location in locations:
            marker = "*" if location.is_best else " "
            info(f" {marker} [{location.host_type}/{location.version}] {location.url[:56]}")
        check(lancet.oa_status == "bronze", "OA status recorded from the source")
        check(len(locations) >= 1, f"{len(locations)} OA location(s) stored")
        best_count = sum(1 for location in locations if location.is_best)
        check(best_count == 1, "exactly one best location elected")

    # ---------------------------------------------------------------- 5
    banner("5", "Identify known retraction information")
    with make_session() as session:
        notices = list(parse_csv(load_text("retractionwatch", "sample.csv")))
        created, _ = retractions.import_notices(session, notices)
        session.flush()
        changed = retractions.apply_to_papers(session)
        session.commit()

        lancet = session.execute(
            select(Paper).where(Paper.canonical_doi == LANCET_DOI)
        ).scalars().one()
        lancet_notices = [n for n in notices if n.original_doi == lancet.canonical_doi]
        info(f"notices imported: {created}")
        for notice in lancet_notices:
            info(f"  {notice.retraction_date}  {notice.nature:22} -> {notice.status}")
        info(f"resolved status: {lancet.retraction_status}")
        info(f"notice url: {(lancet.retraction_notice_url or '(none)')[:60]}")
        check(
            len(lancet_notices) >= 3,
            "the paper carries several notices of differing severity",
        )
        check(lancet.retraction_status == "retracted", "most severe notice wins")
        check(changed >= 1, "retraction status applied to an ingested paper")

    # ---------------------------------------------------------------- 6
    banner("6", "Survive a source failure without losing what was already ingested")
    with make_session() as session:
        before = session.execute(select(func.count()).select_from(Paper)).scalar_one()
        connector = StubConnector(
            "arxiv",
            [[arxiv_raw()], [openalex_raw("work_preprint_integron")]],
            normalise_arxiv,
            fail_after_pages=1,
            cursors=["arxiv-cursor-1", "arxiv-cursor-2"],
        )
        run = pipeline.run(session, connector, since=None)
        session.commit()
        after = session.execute(select(func.count()).select_from(Paper)).scalar_one()
        info(f"run status: {run.status}   errors: {run.errors}")
        info(f"error sample: {run.detail['error_samples'][0][:64]}")
        info(f"papers before failure: {before}   after: {after}")
        info(f"stored cursor after a failed run: {load_cursor(session, 'arxiv')!r}")
        check(run.status == "failed", "the run is recorded as failed")
        check(after == before + 1, "records ingested before the failure were kept")
        check(load_cursor(session, "arxiv") is None, "cursor not advanced, so the run is retried")

    # ---------------------------------------------------------------- 7
    banner("7", "Rerun ingestion idempotently")
    with make_session() as session:
        papers_before = session.execute(select(func.count()).select_from(Paper)).scalar_one()
        records_before = session.execute(
            select(func.count()).select_from(SourceRecord)
        ).scalar_one()

        replay = [
            ("openalex", [[openalex_raw("work_published_integron")]], normalise_openalex),
            ("openalex", [[openalex_raw("work_retracted_lancet")]], normalise_openalex),
            ("biorxiv", [[biorxiv_raw()]], normalise_biorxiv),
        ]
        skipped = 0
        created = 0
        for key, pages, normaliser in replay:
            run = pipeline.run(session, StubConnector(key, pages, normaliser), since=None)
            skipped += run.records_skipped
            created += run.papers_created
        session.commit()

        papers_after = session.execute(select(func.count()).select_from(Paper)).scalar_one()
        records_after = session.execute(
            select(func.count()).select_from(SourceRecord)
        ).scalar_one()
        info(f"papers:        {papers_before} -> {papers_after}")
        info(f"source records: {records_before} -> {records_after}")
        info(f"records skipped as unchanged: {skipped}   papers created: {created}")
        check(papers_after == papers_before, "no duplicate papers created on replay")
        check(records_after == records_before, "no duplicate source records created on replay")
        check(skipped == 3, "every replayed record recognised as unchanged")

    # ---------------------------------------------------------------- 8
    banner("8", "Ingestion metrics")
    with make_session() as session:
        from academious.db.models.ops import IngestionRun

        runs = session.execute(
            select(IngestionRun).order_by(IngestionRun.started_at)
        ).scalars().all()
        header = (
            f"  {'source':10} {'status':10} {'fetch':>5} {'skip':>5} {'new':>4} "
            f"{'upd':>4} {'merge':>5} {'rel':>4} {'oa':>3} {'err':>4}"
        )
        print(header)
        print("  " + "-" * (len(header) - 2))
        for run in runs:
            print(
                f"  {run.source_key:10} {run.status:10} {run.records_fetched:5} "
                f"{run.records_skipped:5} {run.papers_created:4} {run.papers_updated:4} "
                f"{run.papers_merged:5} {run.relations_created:4} "
                f"{run.oa_locations_created:3} {run.errors:4}"
            )
        check(len(runs) >= 8, f"{len(runs)} ingestion runs recorded with per-run metrics")

    print(f"\n{'=' * 78}")
    if failures:
        print(f"RESULT: {failures} check(s) FAILED")
    else:
        print("RESULT: all acceptance checks passed")
    print(f"{'=' * 78}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
