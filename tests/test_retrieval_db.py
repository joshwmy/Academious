"""Lexical, semantic and hybrid retrieval, plus filtering and retraction policy.

The corpus is deliberately tiny and hand-written so that the correct answer to
each query is obvious by inspection. Vectors come from HashingBackend, which is
driven by vocabulary overlap - enough to verify that the semantic path stores,
queries and orders correctly, but it is not a semantic model and nothing here
asserts that it understands anything.
"""

from __future__ import annotations

from datetime import date

import pytest

from academious.embeddings import service as embedding_service
from academious.embeddings.hashing import HashingBackend
from academious.embeddings.registry import HASHING_AUTO
from academious.retrieval import hybrid, lexical, semantic
from academious.retrieval.filters import PreprintPolicy, RetractionPolicy, SearchFilters
from academious.retrieval.service import RetrievalService
from academious.retrieval.types import ScoreKind
from tests.factories import make_paper

pytestmark = pytest.mark.db

PROFILE = HASHING_AUTO


@pytest.fixture
def corpus(session):
    """Eight papers chosen so that every assertion below has one right answer."""
    papers = {
        "cancer": make_paper(
            session,
            "Deep learning for cancer genomics",
            abstract=(
                "We train convolutional networks on tumour sequencing data to predict "
                "driver mutations across many cancer types."
            ),
            keywords=["oncology", "sequencing"],
            topics=[{"label": "Cancer Genomics", "field": "Medicine"}],
            published_date=date(2025, 3, 1),
            oa_status="gold",
        ),
        "transformer": make_paper(
            session,
            "Attention is all you need",
            abstract=(
                "We propose the Transformer, a network architecture based solely on "
                "attention mechanisms, dispensing with recurrence entirely."
            ),
            keywords=["attention", "sequence modelling"],
            topics=[{"label": "Machine Translation", "field": "Computer Science"}],
            published_date=date(2024, 6, 1),
            is_preprint=True,
            is_peer_reviewed=False,
            oa_status="green",
        ),
        "alzheimer": make_paper(
            session,
            "Genome-wide association study of late-onset Alzheimer disease",
            abstract="We identify novel risk loci for late-onset Alzheimer disease.",
            keywords=["genetics"],
            topics=[{"label": "Neurodegeneration", "field": "Medicine"}],
            published_date=date(2023, 1, 15),
            oa_status="closed",
        ),
        "retracted": make_paper(
            session,
            "Hydroxychloroquine and mortality in hospitalised patients",
            abstract="An observational study of hydroxychloroquine treatment outcomes.",
            published_date=date(2020, 5, 22),
            retraction_status="retracted",
            oa_status="bronze",
        ),
        "corrected": make_paper(
            session,
            "Hydroxychloroquine dosing in a randomised trial",
            abstract="A randomised trial of hydroxychloroquine dosing, since corrected.",
            published_date=date(2021, 2, 1),
            retraction_status="corrected",
            oa_status="gold",
        ),
        "graphnn": make_paper(
            session,
            "Graph neural networks for molecular property prediction",
            abstract="Message passing over molecular graphs predicts chemical properties.",
            keywords=["graphs"],
            topics=[{"label": "Graph Learning", "field": "Computer Science"}],
            published_date=date(2025, 1, 10),
            oa_status="gold",
        ),
        "titleonly": make_paper(
            session,
            "Efficient transformer inference on commodity hardware",
            published_date=date(2025, 6, 1),
            topics=[{"label": "Systems", "field": "Computer Science"}],
            oa_status="closed",
        ),
        "unrelated": make_paper(
            session,
            "Sediment transport in braided rivers",
            abstract="Field measurements of bedload flux in a braided alluvial channel.",
            published_date=date(2022, 8, 1),
            oa_status="closed",
        ),
    }
    session.flush()

    pending = embedding_service.select_pending_paper_ids(session, PROFILE.key, limit=100)
    embedding_service.embed_papers(session, pending, profile=PROFILE, backend=HashingBackend())
    session.commit()
    return papers


def ids(result):
    return result.paper_ids()


# ------------------------------------------------------------------ lexical


def test_lexical_search_finds_the_matching_paper(session, corpus):
    result = lexical.search(session, "cancer genomics", limit=10)
    assert result.hits
    assert result.hits[0].paper_id == corpus["cancer"].id
    assert result.hits[0].score_kind == ScoreKind.TS_RANK_CD


def test_lexical_search_matches_on_the_abstract_as_well_as_the_title(session, corpus):
    result = lexical.search(session, "bedload flux", limit=10)
    assert ids(result) == [corpus["unrelated"].id]


def test_lexical_search_matches_on_keywords(session, corpus):
    result = lexical.search(session, "oncology", limit=10)
    assert corpus["cancer"].id in ids(result)


def test_lexical_search_matches_on_topic_labels(session, corpus):
    """Topic labels are indexed even though topics is a JSONB column."""
    result = lexical.search(session, "neurodegeneration", limit=10)
    assert ids(result) == [corpus["alzheimer"].id]


def test_a_title_hit_outranks_an_abstract_only_hit(session, corpus):
    result = lexical.search(session, "transformer", limit=10)
    assert result.hits[0].paper_id == corpus["titleonly"].id


def test_lexical_search_returns_nothing_for_a_term_in_no_paper(session, corpus):
    assert lexical.search(session, "xenotransplantation", limit=10).hits == []


def test_a_malformed_query_does_not_raise(session, corpus):
    """websearch_to_tsquery is chosen precisely because it tolerates junk."""
    assert lexical.search(session, 'the "unclosed quote AND OR -', limit=10) is not None


# ----------------------------------------------------------------- semantic


def test_semantic_search_ranks_by_cosine_similarity(session, corpus):
    result = semantic.search_text(
        session, "cancer genomics", backend=HashingBackend(), model_key=PROFILE.key, limit=10
    )
    assert result.hits[0].paper_id == corpus["cancer"].id
    assert result.hits[0].score_kind == ScoreKind.COSINE_SIMILARITY
    assert -1.0 <= result.hits[0].score <= 1.0


def test_semantic_scores_are_ordered_descending(session, corpus):
    result = semantic.search_text(
        session, "molecular graphs", backend=HashingBackend(), model_key=PROFILE.key, limit=8
    )
    scores = [hit.score for hit in result.hits]
    assert scores == sorted(scores, reverse=True)


def test_semantic_search_only_sees_vectors_for_the_requested_model(session, corpus):
    result = semantic.search_text(
        session,
        "cancer genomics",
        backend=HashingBackend(),
        model_key="a-model-nobody-embedded@v1",
        limit=10,
    )
    assert result.hits == []


def test_a_paper_with_no_abstract_is_still_retrievable(session, corpus):
    result = semantic.search_text(
        session,
        "efficient transformer inference",
        backend=HashingBackend(),
        model_key=PROFILE.key,
        limit=10,
    )
    assert corpus["titleonly"].id in ids(result)


# ------------------------------------------------------------------- hybrid


def test_hybrid_fusion_combines_both_methods(session, corpus):
    components = {
        "lexical": lexical.search(session, "cancer genomics", limit=20),
        "semantic": semantic.search_text(
            session, "cancer genomics", backend=HashingBackend(), model_key=PROFILE.key, limit=20
        ),
    }
    fused = hybrid.fuse(session, components, limit=10, query="cancer genomics")

    assert fused.hits[0].paper_id == corpus["cancer"].id
    assert fused.hits[0].score_kind == ScoreKind.RRF
    assert set(fused.hits[0].components) == {"lexical", "semantic"}


def test_hybrid_surfaces_a_paper_only_one_method_found(session, corpus):
    only_semantic = semantic.search_text(
        session, "sediment transport", backend=HashingBackend(), model_key=PROFILE.key, limit=20
    )
    fused = hybrid.fuse(
        session,
        {"lexical": lexical.search(session, "zzz nothing", limit=20), "semantic": only_semantic},
        limit=10,
    )
    assert corpus["unrelated"].id in ids(fused)


def test_hybrid_ranking_is_deterministic(session, corpus):
    def run():
        components = {
            "lexical": lexical.search(session, "transformer attention", limit=20),
            "semantic": semantic.search_text(
                session,
                "transformer attention",
                backend=HashingBackend(),
                model_key=PROFILE.key,
                limit=20,
            ),
        }
        return ids(hybrid.fuse(session, components, limit=10))

    assert run() == run()


def test_weighted_fusion_is_available_as_an_alternative(session, corpus):
    components = {
        "lexical": lexical.search(session, "cancer genomics", limit=20),
        "semantic": semantic.search_text(
            session, "cancer genomics", backend=HashingBackend(), model_key=PROFILE.key, limit=20
        ),
    }
    fused = hybrid.fuse(session, components, limit=10, method=hybrid.FusionMethod.WEIGHTED)
    assert fused.hits[0].paper_id == corpus["cancer"].id
    assert fused.hits[0].score_kind == ScoreKind.WEIGHTED


# ------------------------------------------------------------------ filters


def test_a_date_floor_excludes_older_papers(session, corpus):
    result = lexical.search(
        session,
        "transformer attention",
        limit=10,
        search_filters=SearchFilters(published_from=date(2025, 1, 1)),
    )
    assert corpus["transformer"].id not in ids(result)
    assert corpus["titleonly"].id in ids(result)


def test_a_date_ceiling_excludes_newer_papers(session, corpus):
    result = lexical.search(
        session,
        "transformer attention",
        limit=10,
        search_filters=SearchFilters(published_to=date(2024, 12, 31)),
    )
    assert ids(result) == [corpus["transformer"].id]


def test_preprints_can_be_excluded(session, corpus):
    result = lexical.search(
        session,
        "attention",
        limit=10,
        search_filters=SearchFilters(preprints=PreprintPolicy.EXCLUDE_PREPRINTS),
    )
    assert corpus["transformer"].id not in ids(result)


def test_preprints_can_be_the_only_thing_returned(session, corpus):
    result = lexical.search(
        session,
        "attention",
        limit=10,
        search_filters=SearchFilters(preprints=PreprintPolicy.ONLY_PREPRINTS),
    )
    assert ids(result) == [corpus["transformer"].id]


def test_peer_reviewed_only_drops_the_preprint(session, corpus):
    result = lexical.search(
        session, "attention", limit=10, search_filters=SearchFilters(peer_reviewed_only=True)
    )
    assert corpus["transformer"].id not in ids(result)


def test_open_access_only_drops_closed_papers(session, corpus):
    result = lexical.search(
        session,
        "transformer attention",
        limit=10,
        search_filters=SearchFilters(open_access_only=True),
    )
    assert corpus["titleonly"].id not in ids(result)
    assert corpus["transformer"].id in ids(result)


def test_filtering_by_research_field(session, corpus):
    result = lexical.search(
        session,
        "prediction",
        limit=10,
        search_filters=SearchFilters(fields=("Computer Science",)),
    )
    assert corpus["graphnn"].id in ids(result)
    assert corpus["cancer"].id not in ids(result)


def test_filters_apply_to_semantic_search_too(session, corpus):
    result = semantic.search_text(
        session,
        "cancer genomics",
        backend=HashingBackend(),
        model_key=PROFILE.key,
        limit=10,
        search_filters=SearchFilters(published_from=date(2025, 6, 1)),
    )
    assert ids(result) == [corpus["titleonly"].id]


# --------------------------------------------------------------- retractions


def test_retracted_papers_are_excluded_by_default(session, corpus):
    result = lexical.search(session, "hydroxychloroquine", limit=10)
    assert corpus["retracted"].id not in ids(result)


def test_a_corrected_paper_is_returned_with_its_status_visible(session, corpus):
    result = lexical.search(session, "hydroxychloroquine", limit=10)
    assert ids(result) == [corpus["corrected"].id]
    assert result.hits[0].retraction_status == "corrected"


def test_retracted_papers_can_be_asked_for_explicitly(session, corpus):
    result = lexical.search(
        session,
        "hydroxychloroquine",
        limit=10,
        search_filters=SearchFilters(retraction=RetractionPolicy.INCLUDE_ALL),
    )
    assert corpus["retracted"].id in ids(result)
    assert corpus["corrected"].id in ids(result)


def test_only_flagged_returns_papers_carrying_a_notice(session, corpus):
    result = lexical.search(
        session,
        "hydroxychloroquine trial study",
        limit=10,
        search_filters=SearchFilters(retraction=RetractionPolicy.ONLY_FLAGGED),
    )
    assert set(ids(result)) == {corpus["retracted"].id, corpus["corrected"].id}


def test_retraction_exclusion_applies_to_semantic_search(session, corpus):
    result = semantic.search_text(
        session,
        "hydroxychloroquine mortality",
        backend=HashingBackend(),
        model_key=PROFILE.key,
        limit=10,
    )
    assert corpus["retracted"].id not in ids(result)


# ------------------------------------------------------------------ service


def test_search_by_interest_runs_every_method(session, corpus):
    service = RetrievalService(backend=HashingBackend(), model_key=PROFILE.key)
    for method in ("lexical", "semantic", "hybrid"):
        result = service.search_by_interest(session, "cancer genomics", limit=5, method=method)
        assert result.hits, method
        assert len(result.hits) <= 5


def test_search_by_interest_rejects_an_unknown_method(session, corpus):
    service = RetrievalService(backend=HashingBackend(), model_key=PROFILE.key)
    with pytest.raises(ValueError, match="unknown retrieval method"):
        service.search_by_interest(session, "anything", method="magic")


def test_search_all_methods_returns_one_result_per_method(session, corpus):
    service = RetrievalService(backend=HashingBackend(), model_key=PROFILE.key)
    results = service.search_all_methods(session, "graph neural networks", limit=5)
    assert set(results) == {"lexical", "semantic", "hybrid"}
    assert all(len(result.hits) <= 5 for result in results.values())


# --------------------------------------------------- strict vs relaxed query


def test_a_query_whose_terms_all_appear_uses_the_strict_conjunction(session, corpus):
    result = lexical.search(session, "cancer genomics", limit=10)
    assert result.detail["query_mode"] == lexical.STRICT
    assert ids(result) == [corpus["cancer"].id]


def test_a_multi_concept_query_falls_back_to_disjunction(session, corpus):
    """No paper has all five terms, so a strict-only baseline would return nothing."""
    strict_only = lexical.search(
        session, "public health diabetes risk prediction", limit=10, allow_relaxed=False
    )
    assert strict_only.hits == []

    relaxed = lexical.search(session, "public health diabetes risk prediction", limit=10)
    assert relaxed.detail["query_mode"] == lexical.RELAXED
    assert relaxed.hits


def test_the_relaxed_pass_still_ranks_by_how_much_matched(session, corpus):
    result = lexical.search(session, "graph neural networks quantum chemistry", limit=10)
    assert result.detail["query_mode"] == lexical.RELAXED
    assert result.hits[0].paper_id == corpus["graphnn"].id


def test_an_exclusion_is_never_relaxed_into_a_disjunction(session, corpus):
    """Relaxing `a & !b` to `a | !b` would invert what the minus sign means."""
    result = lexical.search(session, "sequencing -tumour -cancer -driver", limit=10)
    assert result.detail["query_mode"] == lexical.STRICT
    assert corpus["cancer"].id not in ids(result)
