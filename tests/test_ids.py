"""Identifier normalisation is the primary dedup path, so it is tested hardest."""

from __future__ import annotations

import pytest

from academious.core import ids
from academious.core.ids import IdType


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://doi.org/10.1038/S41564-023-01548-Y", "10.1038/s41564-023-01548-y"),
        ("doi:10.1101/2022.09.11.507474", "10.1101/2022.09.11.507474"),
        ("10.1016/S0140-6736(20)31180-6", "10.1016/s0140-6736(20)31180-6"),
        ("  10.1234/abc.  ", "10.1234/abc"),
        ("http://dx.doi.org/10.1234/xyz)", "10.1234/xyz"),
        ("not a doi", None),
        ("", None),
        (None, None),
    ],
)
def test_normalise_doi(raw, expected):
    assert ids.normalise_doi(raw) == expected


def test_doi_normalisation_is_idempotent():
    once = ids.normalise_doi("https://doi.org/10.1038/S41564-023-01548-Y")
    assert ids.normalise_doi(once) == once


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2401.12345", "2401.12345"),
        ("2401.12345v3", "2401.12345"),
        ("arXiv:1706.03762", "1706.03762"),
        ("oai:arXiv.org:1706.03762", "1706.03762"),
        ("https://arxiv.org/abs/1706.03762v5", "1706.03762"),
        ("https://arxiv.org/pdf/2401.12345", "2401.12345"),
        ("10.48550/arXiv.1706.03762", "1706.03762"),
        ("math/0211159", "math/0211159"),
        ("cond-mat/9803029v2", "cond-mat/9803029"),
        ("nonsense", None),
    ],
)
def test_normalise_arxiv(raw, expected):
    assert ids.normalise_arxiv(raw) == expected


def test_arxiv_versions_collapse_to_one_paper():
    assert ids.normalise_arxiv("2401.12345v1") == ids.normalise_arxiv("2401.12345v7")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://pubmed.ncbi.nlm.nih.gov/38172619", "38172619"),
        ("38172619", "38172619"),
        (38172619, "38172619"),
        ("0", None),
        (None, None),
    ],
)
def test_normalise_pmid(raw, expected):
    assert ids.normalise_pmid(raw) == expected


def test_normalise_pmcid():
    assert ids.normalise_pmcid("PMC1234567") == "PMC1234567"
    assert ids.normalise_pmcid("1234567") == "PMC1234567"
    assert ids.normalise_pmcid(None) is None


def test_normalise_openalex():
    assert ids.normalise_openalex("https://openalex.org/W4390571678") == "W4390571678"
    assert ids.normalise_openalex("w4390571678") == "W4390571678"
    assert ids.normalise_openalex("nope") is None


def test_arxiv_id_from_url_ignores_non_arxiv_hosts():
    biorxiv_url = "https://www.biorxiv.org/content/10.1101/2022.09.11.507474"
    assert ids.arxiv_id_from_url(biorxiv_url) is None
    assert ids.arxiv_id_from_url("https://arxiv.org/abs/2401.12345") == "2401.12345"
    assert ids.arxiv_id_from_url(None) is None


def test_dispatch_matches_direct_calls():
    assert ids.normalise(IdType.DOI, "https://doi.org/10.1/A") == ids.normalise_doi(
        "https://doi.org/10.1/A"
    )
