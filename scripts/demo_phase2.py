"""Phase 2 acceptance demonstration.

Runs the real embedding pipeline and the real retrieval stack against a real
PostgreSQL with pgvector. Each numbered section corresponds to one Phase 2
acceptance criterion.

    docker compose up -d db
    python scripts/demo_phase2.py                    # uses SPECTER2
    python scripts/demo_phase2.py --backend hashing  # no torch needed

The corpus is a small hand-written set rather than a harvest, so that the right
answer to every query is checkable by eye and the demo needs no network. It
includes the awkward cases on purpose: a paper with no abstract, a retracted
paper and a corrected one.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

DEFAULT_URL = "postgresql+psycopg://academious:academious@localhost:5432/academious_demo2"


def banner(number: str, title: str) -> None:
    print(f"\n{'=' * 78}\n{number}. {title}\n{'=' * 78}")


def info(message: str) -> None:
    print(f"         {message}")


class CountingBackend:
    """Wraps a backend so the demo can prove no inference happened."""

    def __init__(self, inner):
        self._inner = inner
        self.model_id = inner.model_id
        self.dimension = inner.dimension
        self.max_sequence_length = inner.max_sequence_length
        self.documents_encoded = 0

    def encode_documents(self, texts):
        self.documents_encoded += len(texts)
        return self._inner.encode_documents(texts)

    def encode_queries(self, texts):
        return self._inner.encode_queries(texts)


PAPERS = [
    # (title, abstract, keywords, topics, published, preprint, oa, retraction)
    (
        "Deep learning models for pan-cancer driver mutation calling",
        "We train convolutional and transformer architectures on tumour whole-genome "
        "sequencing data to identify driver mutations across twenty cancer types, "
        "improving on published baselines for rare variants.",
        ["oncology", "sequencing"],
        [{"label": "Cancer Genomics", "field": "Medicine"}],
        date(2025, 3, 1), False, "gold", "none",
    ),
    (
        "Transcriptomic signatures predict recurrence in early breast cancer",
        "RNA sequencing of 1,200 tumours identifies an expression signature that "
        "stratifies patients by recurrence risk independently of stage and grade.",
        ["breast cancer", "biomarkers", "transcriptomics"],
        [{"label": "Breast Cancer", "field": "Medicine"}],
        date(2025, 5, 12), False, "hybrid", "none",
    ),
    (
        "Genome-wide association study of late-onset Alzheimer disease",
        "A meta-analysis across 80,000 cases and controls identifies novel risk loci "
        "for late-onset Alzheimer disease and implicates microglial pathways.",
        ["genetics", "neurodegeneration"],
        [{"label": "Alzheimer Disease", "field": "Medicine"}],
        date(2024, 11, 3), False, "green", "none",
    ),
    (
        "Self-supervised pretraining for chest radiograph interpretation",
        "We pretrain a vision transformer on unlabelled chest radiographs and show "
        "that it matches radiologist performance on pneumothorax detection.",
        ["medical imaging", "deep learning"],
        [{"label": "Medical Imaging", "field": "Medicine"}],
        date(2026, 1, 20), True, "green", "none",
    ),
    (
        "Population-scale prediction of type 2 diabetes onset from primary care records",
        "Gradient-boosted models over ten years of primary care records predict "
        "incident type 2 diabetes, with calibration assessed across deprivation "
        "deciles to check for inequitable performance.",
        ["public health", "risk prediction", "diabetes"],
        [{"label": "Epidemiology", "field": "Medicine"}],
        date(2025, 9, 8), False, "gold", "none",
    ),
    (
        "Generative models for small-molecule lead optimisation",
        "A diffusion model over molecular graphs proposes candidate ligands "
        "conditioned on binding pocket geometry, evaluated by docking and "
        "retrospective screening against known actives.",
        ["drug discovery", "generative models"],
        [{"label": "Computational Chemistry", "field": "Medicine"}],
        date(2026, 2, 14), True, "green", "none",
    ),
    (
        "Attention is all you need",
        "We propose the Transformer, a network architecture based solely on attention "
        "mechanisms, dispensing with recurrence and convolutions entirely.",
        ["attention", "sequence modelling"],
        [{"label": "Machine Translation", "field": "Computer Science"}],
        date(2024, 6, 1), True, "green", "none",
    ),
    (
        "Repository-level code synthesis with large language models",
        "We evaluate large language models on synthesising code that must compile "
        "against an existing repository, and find that retrieval of in-repo context "
        "matters more than model scale.",
        ["code generation", "language models"],
        [{"label": "Software Engineering", "field": "Computer Science"}],
        date(2026, 4, 2), True, "green", "none",
    ),
    (
        "Retrieval augmented generation for knowledge-intensive question answering",
        "Combining a dense retriever with a generative reader improves factual "
        "accuracy on open-domain question answering and makes provenance auditable.",
        ["retrieval", "question answering"],
        [{"label": "Information Retrieval", "field": "Computer Science"}],
        date(2025, 7, 19), False, "gold", "none",
    ),
    (
        "Sim-to-real transfer for dexterous manipulation via domain randomisation",
        "A policy trained purely in simulation with randomised dynamics transfers to "
        "a physical five-fingered hand without any real-world fine-tuning.",
        ["reinforcement learning", "robotics"],
        [{"label": "Robotics", "field": "Computer Science"}],
        date(2025, 10, 30), True, "green", "none",
    ),
    (
        "Graph neural networks for molecular property prediction",
        "Message passing over molecular graphs predicts quantum chemical properties "
        "at a fraction of the cost of density functional theory.",
        ["graphs", "chemistry"],
        [{"label": "Graph Learning", "field": "Computer Science"}],
        date(2025, 1, 10), False, "gold", "none",
    ),
    # No abstract at all. Real OAI records routinely look like this.
    (
        "Efficient transformer inference on commodity hardware",
        None,
        [],
        [{"label": "Systems", "field": "Computer Science"}],
        date(2026, 6, 1), True, "closed", "none",
    ),
    (
        "Hydroxychloroquine and mortality in hospitalised patients with COVID-19",
        "An observational analysis of treatment outcomes in hospitalised patients "
        "reporting an association between hydroxychloroquine and increased mortality.",
        ["covid-19"],
        [{"label": "Infectious Disease", "field": "Medicine"}],
        date(2020, 5, 22), False, "bronze", "retracted",
    ),
    (
        "Hydroxychloroquine dosing in a randomised controlled trial",
        "A randomised controlled trial of hydroxychloroquine dosing regimens, for "
        "which a correction to the reported dosing table was subsequently issued.",
        ["covid-19", "clinical trial"],
        [{"label": "Infectious Disease", "field": "Medicine"}],
        date(2021, 2, 1), False, "gold", "corrected",
    ),
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", default="specter2", choices=("specter2", "hashing"))
    parser.add_argument("--database-url", default=None)
    args = parser.parse_args()

    os.environ["ACADEMIOUS_DATABASE_URL"] = args.database_url or DEFAULT_URL
    os.environ.setdefault("ACADEMIOUS_LOG_LEVEL", "ERROR")

    from sqlalchemy import create_engine, func, select, text
    from sqlalchemy.orm import sessionmaker

    from academious.core.clock import utcnow
    from academious.core.config import get_settings
    from academious.core.text import normalise_title
    from academious.db.ddl import bootstrap_sql
    from academious.db.models import Base, Paper, PaperEmbedding
    from academious.db.models.ops import Job, JobStatus
    from academious.embeddings import jobs as embed_jobs
    from academious.embeddings import service as embedding_service
    from academious.embeddings.registry import EmbeddingProfile
    from academious.embeddings.text import InputMode
    from academious.eval import harness
    from academious.eval.queries import BenchmarkQuery, Domain
    from academious.jobs import queue
    from academious.retrieval.filters import PreprintPolicy, RetractionPolicy, SearchFilters
    from academious.retrieval.service import RetrievalService

    get_settings.cache_clear()
    settings = get_settings()

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
        for statement in bootstrap_sql():
            connection.execute(text(statement))
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    make_session = sessionmaker(bind=engine, expire_on_commit=False, future=True)

    if args.backend == "specter2":
        from academious.embeddings.specter2 import Specter2Backend

        inner = Specter2Backend(batch_size=8)
        profile = EmbeddingProfile(
            key="specter2-proximity@v1", backend_name="specter2", input_mode=InputMode.AUTO
        )
    else:
        from academious.embeddings.hashing import HashingBackend

        inner = HashingBackend()
        profile = EmbeddingProfile(
            key="hashing-bow@v1", backend_name="hashing", input_mode=InputMode.AUTO
        )
    backend = CountingBackend(inner)

    failures = 0

    def check(condition: bool, message: str) -> None:
        nonlocal failures
        if condition:
            print(f"  [PASS] {message}")
        else:
            failures += 1
            print(f"  [FAIL] {message}")

    # Seed the corpus. Ingestion itself is Phase 1, demonstrated by demo_phase1.
    with make_session() as session:
        for title, abstract, keywords, topics, published, preprint, oa, retraction in PAPERS:
            session.add(
                Paper(
                    title=title,
                    title_norm=normalise_title(title),
                    abstract=abstract,
                    authors=[],
                    keywords=list(keywords),
                    topics=list(topics),
                    published_date=published,
                    published_year=published.year,
                    is_preprint=preprint,
                    is_peer_reviewed=not preprint,
                    oa_status=oa,
                    retraction_status=retraction,
                    language="en",
                )
            )
        session.commit()

    # ---------------------------------------------------------------- 1
    banner("1", "An ingested paper without an embedding is detected")
    with make_session() as session:
        total = session.execute(select(func.count()).select_from(Paper)).scalar_one()
        pending = embedding_service.count_pending(session, profile.key)
        info(f"papers ingested: {total}")
        info(f"papers pending an embedding under {profile.key}: {pending}")
        check(pending == total, "every ingested paper is detected as needing an embedding")

    # ---------------------------------------------------------------- 2, 3
    banner("2", f"An embedding is generated ({backend.model_id}) and the vector persisted")
    with make_session() as session:
        embed_jobs.enqueue_pending(session, profile, batch_size=8)
        session.commit()
        queued = session.execute(
            select(func.count()).select_from(Job).where(Job.kind == embed_jobs.JOB_KIND)
        ).scalar_one()
        info(f"embedding jobs queued: {queued}")

    processed = 0
    while True:
        with make_session() as session:
            claimed = queue.claim(session, limit=1)
            job_id = claimed[0].id if claimed else None
            session.commit()
        if job_id is None:
            break
        with make_session() as session:
            job = session.get(Job, job_id)
            embed_jobs.handle(session, job, profile=profile, backend=backend)
            queue.complete(session, job)
            session.commit()
        processed += 1

    with make_session() as session:
        rows = (
            session.execute(
                select(PaperEmbedding).where(PaperEmbedding.model_key == profile.key)
            )
            .scalars()
            .all()
        )
        vector_ids = [r.paper_id for r in rows]
        sample = rows[0]
        info(f"jobs drained: {processed}   vectors written: {len(rows)}")
        info(f"dimension: {sample.dim}   stored as halfvec({sample.dim})")
        info(f"model_key: {sample.model_key}   strategy: {sample.input_strategy}")
        info(f"input hash: {sample.input_text_hash[:16]}...  tokens: {sample.token_count}")
        check(len(rows) == len(PAPERS), f"{len(rows)} vectors persisted, one per paper")
        check(sample.dim == 768, "vectors are 768-dimensional")
        check(
            embedding_service.count_pending(session, profile.key) == 0, "nothing remains pending"
        )

    # ---------------------------------------------------------------- 4
    banner("4", "Re-running does not duplicate work")
    encoded_before = backend.documents_encoded
    with make_session() as session:
        jobs_queued, _ = embed_jobs.enqueue_pending(session, profile, batch_size=8)
        session.commit()
        pending = embedding_service.select_pending_paper_ids(session, profile.key, limit=100)
        stats = embedding_service.embed_papers(
            session, vector_ids, profile=profile, backend=backend
        )
        session.commit()
        after = session.execute(select(func.count()).select_from(PaperEmbedding)).scalar_one()
    info(f"papers still pending: {len(pending)}   new jobs queued: {jobs_queued}")
    info(f"documents encoded on the first pass: {encoded_before}")
    info(f"documents encoded on the second pass: {backend.documents_encoded - encoded_before}")
    info(f"skipped as unchanged: {stats.skipped_unchanged}")
    check(backend.documents_encoded == encoded_before, "no model inference on the second pass")
    check(after == len(PAPERS), "no duplicate vectors created")

    # ---------------------------------------------------------------- 5
    banner("5", "A paper with no abstract still gets an embedding")
    with make_session() as session:
        no_abstract = session.execute(select(Paper).where(Paper.abstract.is_(None))).scalars().one()
        row = session.get(PaperEmbedding, (no_abstract.id, profile.key))
        info(f"paper: {no_abstract.title}")
        info(f"abstract: {no_abstract.abstract}")
        info(f"strategy recorded: {row.input_strategy}   tokens: {row.token_count}")
        check(row is not None, "a title-only paper is embedded rather than skipped")
        check(row.input_strategy == "title_only", "the fallback strategy is recorded on the row")

    service = RetrievalService(backend=backend, model_key=profile.key)

    def show(result, limit: int = 5) -> None:
        for hit in result.hits[:limit]:
            flag = "" if hit.retraction_status == "none" else f"  [{hit.retraction_status}]"
            info(f"{hit.rank:2}. {hit.score:7.4f}  {hit.title[:58]}{flag}")

    # ---------------------------------------------------------------- 6
    banner("6", "A semantic query retrieves plausible papers")
    with make_session() as session:
        for query in ("machine learning for cancer genomics", "LLMs for software engineering"):
            result = service.search_by_interest(session, query, limit=3, method="semantic")
            info(f"query: {query}")
            show(result, 3)
            info("")
        result = service.search_by_interest(
            session, "machine learning for cancer genomics", limit=3, method="semantic"
        )
        check(bool(result.hits), "semantic retrieval returns results")
        check(
            result.hits[0].score_kind == "cosine_similarity",
            "scores are raw cosine similarity, not a fabricated percentage",
        )

    # ---------------------------------------------------------------- 7
    banner("7", "Lexical search retrieves results")
    with make_session() as session:
        result = service.search_by_interest(
            session, "graph neural networks", limit=3, method="lexical"
        )
        info("query: graph neural networks")
        info(f"query mode: {result.detail['query_mode']}")
        show(result, 3)
        check(bool(result.hits), "lexical retrieval returns results")

        relaxed = service.search_by_interest(
            session, "public health diabetes risk prediction", limit=3, method="lexical"
        )
        info("")
        info("query: public health diabetes risk prediction")
        info(f"query mode: {relaxed.detail['query_mode']}")
        show(relaxed, 3)
        check(
            bool(relaxed.hits),
            "a multi-concept query still returns a baseline, via the relaxed pass",
        )

    # ---------------------------------------------------------------- 8
    banner("8", "Hybrid retrieval works")
    with make_session() as session:
        result = service.search_by_interest(
            session, "transformer models for protein structure", limit=5, method="hybrid"
        )
        show(result, 5)
        info("")
        for hit in result.hits[:2]:
            parts = ", ".join(f"{k}={v:.4f}" for k, v in sorted(hit.components.items()))
            info(f"rank {hit.rank} explained by: {parts}")
        check(bool(result.hits), "hybrid retrieval returns results")
        check(
            all(hit.components for hit in result.hits),
            "every hybrid hit records the per-method contribution behind its rank",
        )

    # ---------------------------------------------------------------- 9
    banner("9", "Retracted papers are excluded by default")
    with make_session() as session:
        default = service.search_by_interest(session, "hydroxychloroquine", limit=5)
        info("default policy (exclude_retracted):")
        show(default)
        statuses = {hit.retraction_status for hit in default.hits}

        included = service.search_by_interest(
            session,
            "hydroxychloroquine",
            limit=5,
            search_filters=SearchFilters(retraction=RetractionPolicy.INCLUDE_ALL),
        )
        info("")
        info("explicitly asking for everything (include_all):")
        show(included)

        flagged = service.search_by_interest(
            session,
            "hydroxychloroquine",
            limit=5,
            search_filters=SearchFilters(retraction=RetractionPolicy.ONLY_FLAGGED),
        )
        check("retracted" not in statuses, "no retracted paper appears in ordinary discovery")
        check(
            "corrected" in statuses,
            "a corrected paper is still returned, with its status attached",
        )
        check(
            any(hit.retraction_status == "retracted" for hit in included.hits),
            "the retracted paper is retrievable when explicitly requested",
        )
        check(len(flagged.hits) == 2, "only_flagged returns exactly the two flagged papers")

    # ---------------------------------------------------------------- 10
    banner("10", "Filters work")
    with make_session() as session:
        query = "machine learning"
        unfiltered = service.search_by_interest(session, query, limit=20)
        recent = service.search_by_interest(
            session,
            query,
            limit=20,
            search_filters=SearchFilters(published_from=date(2026, 1, 1)),
        )
        published_only = service.search_by_interest(
            session,
            query,
            limit=20,
            search_filters=SearchFilters(preprints=PreprintPolicy.EXCLUDE_PREPRINTS),
        )
        open_access = service.search_by_interest(
            session, query, limit=20, search_filters=SearchFilters(open_access_only=True)
        )
        computing = service.search_by_interest(
            session, query, limit=20, search_filters=SearchFilters(fields=("Computer Science",))
        )
        info(f"unfiltered:                 {len(unfiltered.hits)}")
        info(f"published 2026 onwards:     {len(recent.hits)}")
        info(f"excluding preprints:        {len(published_only.hits)}")
        info(f"open access only:           {len(open_access.hits)}")
        info(f"field = Computer Science:   {len(computing.hits)}")
        check(
            all(h.published_date >= date(2026, 1, 1) for h in recent.hits),
            "the date filter is respected by every returned hit",
        )
        check(
            not any(h.is_preprint for h in published_only.hits),
            "the preprint filter is respected",
        )
        check(
            all(
                h.oa_status in ("gold", "green", "hybrid", "bronze", "diamond")
                for h in open_access.hits
            ),
            "the open-access filter is respected",
        )
        check(
            0 < len(computing.hits) < len(unfiltered.hits),
            "the research-field filter narrows the result set",
        )

    # ---------------------------------------------------------------- 11
    banner("11", "Evaluation tooling produces inspectable comparison results")
    demo_queries = (
        BenchmarkQuery("d-01", "cancer genomics machine learning", Domain.BIOMEDICAL, "demo"),
        BenchmarkQuery("d-02", "graph neural networks", Domain.COMPUTING, "demo"),
        BenchmarkQuery("d-03", "AI safety evaluation", Domain.COMPUTING, "demo"),
    )
    with make_session() as session:
        report, pool = harness.evaluate(session, service, queries=demo_queries, depth=5)
    print(harness.render(report, show_hits=3))
    info(f"pooled papers to judge: {report.pooled}   judged so far: {report.judged}")
    check(len(report.runs) == 3, "every benchmark query ran through all three methods")
    check(
        all(set(run.results) == {"lexical", "semantic", "hybrid"} for run in report.runs),
        "each query produces a comparable ranking per method",
    )
    check(
        not report.has_metrics,
        "with no human judgments, NO quality metrics are reported (not even zeros)",
    )
    check(
        all(entry.retrieved_by for entry in pool),
        "each pooled paper records which methods retrieved it",
    )

    # ---------------------------------------------------------------- 12
    banner("12", "Worker interruption and retry is safe")
    late_title = "A paper ingested after the first embedding pass"
    with make_session() as session:
        session.add(
            Paper(
                title=late_title,
                title_norm=normalise_title(late_title),
                abstract="Its only purpose is to give the interrupted worker something to do.",
                authors=[],
                keywords=[],
                topics=[],
                language="en",
                published_date=date(2026, 7, 1),
                published_year=2026,
            )
        )
        session.flush()
        embed_jobs.enqueue_pending(session, profile, batch_size=8)
        session.commit()

    with make_session() as session:
        claimed = queue.claim(session, limit=1)[0]
        job_id = claimed.id
        session.commit()
        info(f"job {str(job_id)[:8]} claimed: status={claimed.status} attempts={claimed.attempts}")

    # The worker dies here: the row stays `running` and nobody reports back.
    with make_session() as session:
        stuck = session.get(Job, job_id)
        stuck.locked_at = utcnow() - timedelta(hours=2)
        session.commit()
        info("worker killed mid-job; the job is stranded in `running` with nobody holding it")
        check(
            not queue.claim(session, limit=5),
            "a stranded job is invisible to other workers until it is reaped",
        )

    with make_session() as session:
        reaped = queue.reap_stale(session, older_than=timedelta(minutes=30))
        session.commit()
        job = session.get(Job, job_id)
        info(f"jobs reaped: {reaped}   status is now: {job.status}")
        check(
            reaped == 1 and job.status == JobStatus.PENDING.value, "the job returns to the queue"
        )

    encoded_before = backend.documents_encoded
    with make_session() as session:
        queue.claim(session, limit=1)
        session.commit()
    with make_session() as session:
        job = session.get(Job, job_id)
        stats = embed_jobs.handle(session, job, profile=profile, backend=backend)
        queue.complete(session, job)
        session.commit()
    with make_session() as session:
        final = session.execute(select(func.count()).select_from(PaperEmbedding)).scalar_one()
        still_pending = embedding_service.count_pending(session, profile.key)
    info(f"on retry: embedded={stats.embedded}, skipped_unchanged={stats.skipped_unchanged}")
    info(f"documents re-encoded on retry: {backend.documents_encoded - encoded_before}")
    check(stats.embedded == 1, "the retry completes the work the dead worker did not")
    check(final == len(PAPERS) + 1, "exactly one new vector, no duplicates")
    check(still_pending == 0, "the corpus is fully embedded again")

    print(f"\n{'=' * 78}")
    if failures:
        print(f"RESULT: {failures} check(s) FAILED")
    else:
        print("RESULT: all acceptance checks passed")
    print(f"generated {datetime.now(UTC).isoformat()}")
    print(f"{'=' * 78}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
