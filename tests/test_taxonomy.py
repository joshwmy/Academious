"""The normalised subject taxonomy: one field vocabulary over four sources.

These tests are about the *mapping*, not about any one connector. A paper's
field is derived from whatever taxonomy its sources happened to supply, so the
same paper reaches the same field whether it arrived from OpenAlex with a
`field` key, from arXiv as `cs.LG`, or from bioRxiv as `neuroscience`.

The mapping is deliberately coarse and it is a judgement. What these tests
protect is that it is *stable*, *total over the vocabulary we have observed*,
and that an unrecognised label produces no field rather than a wrong one.
"""

from __future__ import annotations

import pytest

from academious.ingest.taxonomy import (
    FIELDS,
    Field,
    describe,
    field_slugs,
    fields_for,
    is_field,
    unmapped_topics,
)


def test_vocabulary_is_openalexs_twenty_six_fields():
    assert len(FIELDS) == 26
    assert len({f.slug for f in FIELDS}) == 26
    assert len({f.openalex_id for f in FIELDS}) == 26
    assert all(isinstance(f, Field) for f in FIELDS)


def test_slugs_are_url_safe_and_derived_from_the_label():
    for field in FIELDS:
        assert field.slug == field.slug.lower()
        assert " " not in field.slug
        assert set(field.slug) <= set("abcdefghijklmnopqrstuvwxyz-")


def test_is_field_accepts_the_vocabulary_and_nothing_else():
    assert is_field("computer-science")
    assert is_field("physics-and-astronomy")
    assert not is_field("Computer Science")
    assert not is_field("comp-sci")
    assert not is_field("")


def test_describe_is_json_safe_and_ordered_by_label():
    described = describe()
    assert [entry["label"] for entry in described] == sorted(f.label for f in FIELDS)
    assert described[0].keys() == {"slug", "label", "openalex_id"}


# --- OpenAlex: the field travels on the topic already -----------------------


def test_openalex_topic_maps_through_its_own_field_name():
    topics = [
        {"scheme": "openalex", "id": "T10211", "label": "Drug Discovery", "field": "Medicine"}
    ]
    assert fields_for(topics) == ("medicine",)


def test_openalex_field_matching_ignores_case_and_surrounding_space():
    topics = [{"scheme": "openalex", "field": "  computer science "}]
    assert fields_for(topics) == ("computer-science",)


def test_openalex_topic_without_a_field_contributes_nothing():
    # arXiv and bioRxiv records enriched by OpenAlex predate the field key, and
    # a topic can carry a null field. Neither is an error.
    assert fields_for([{"scheme": "openalex", "id": "T1", "field": None}]) == ()
    assert fields_for([{"scheme": "openalex", "id": "T1"}]) == ()


# --- arXiv: archive prefix, with subject-specific overrides ------------------


@pytest.mark.parametrize(
    ("category", "expected"),
    [
        ("cs.LG", "computer-science"),
        ("cs.CV", "computer-science"),
        ("math.AG", "mathematics"),
        ("math-ph", "physics-and-astronomy"),
        ("stat.ME", "mathematics"),
        ("econ.EM", "economics-econometrics-and-finance"),
        ("q-fin.RM", "economics-econometrics-and-finance"),
        ("eess.SP", "engineering"),
        ("astro-ph.SR", "physics-and-astronomy"),
        ("cond-mat.soft", "physics-and-astronomy"),
        ("hep-th", "physics-and-astronomy"),
        ("quant-ph", "physics-and-astronomy"),
        ("nlin.CD", "physics-and-astronomy"),
        ("q-bio.PE", "agricultural-and-biological-sciences"),
    ],
)
def test_arxiv_categories_map_by_archive(category, expected):
    assert fields_for([{"scheme": "arxiv", "id": category, "label": category}]) == (expected,)


@pytest.mark.parametrize(
    ("category", "expected"),
    [
        # A subcategory overrides its archive only where the archive would be
        # actively misleading, never to chase precision the vocabulary lacks.
        ("q-bio.NC", "neuroscience"),
        ("q-bio.BM", "biochemistry-genetics-and-molecular-biology"),
        ("q-bio.GN", "biochemistry-genetics-and-molecular-biology"),
        ("stat.ML", "computer-science"),
        ("physics.med-ph", "medicine"),
        ("physics.soc-ph", "social-sciences"),
        ("physics.chem-ph", "chemistry"),
        ("physics.geo-ph", "earth-and-planetary-sciences"),
        ("physics.ao-ph", "earth-and-planetary-sciences"),
        ("cond-mat.mtrl-sci", "materials-science"),
    ],
)
def test_arxiv_subcategory_overrides_win_over_the_archive(category, expected):
    assert fields_for([{"scheme": "arxiv", "id": category, "label": category}]) == (expected,)


def test_arxiv_category_case_and_whitespace_do_not_matter():
    assert fields_for([{"scheme": "arxiv", "id": " CS.LG "}]) == ("computer-science",)


def test_unknown_arxiv_archive_maps_to_nothing():
    assert fields_for([{"scheme": "arxiv", "id": "xyz.QQ"}]) == ()


# --- bioRxiv and medRxiv: one category label per paper ----------------------


@pytest.mark.parametrize(
    ("category", "expected"),
    [
        ("neuroscience", "neuroscience"),
        ("bioinformatics", "biochemistry-genetics-and-molecular-biology"),
        ("microbiology", "immunology-and-microbiology"),
        ("ecology", "agricultural-and-biological-sciences"),
        ("bioengineering", "engineering"),
        ("epidemiology", "medicine"),
        ("public and global health", "medicine"),
        ("health informatics", "health-professions"),
        ("pharmacology and toxicology", "pharmacology-toxicology-and-pharmaceutics"),
        ("dentistry and oral medicine", "dentistry"),
        ("nursing", "nursing"),
        ("health economics", "economics-econometrics-and-finance"),
        ("paleontology", "earth-and-planetary-sciences"),
        ("scientific communication and education", "social-sciences"),
    ],
)
def test_biorxiv_categories_map_by_label(category, expected):
    assert fields_for([{"scheme": "biorxiv", "id": category, "label": category}]) == (expected,)


def test_biorxiv_label_matching_ignores_case_and_space():
    assert fields_for([{"scheme": "biorxiv", "id": "  Cancer Biology  "}]) == (
        "biochemistry-genetics-and-molecular-biology",
    )


def test_every_biorxiv_category_seen_in_the_live_corpus_is_mapped():
    # Enumerated from the deployed corpus on 2026-09-02: 70 distinct category
    # labels across bioRxiv and medRxiv. A connector that starts returning a new
    # one should show up as an unmapped topic in the backfill report, not as a
    # silently unclassified paper - so this list is evidence, not aspiration.
    observed = [
        "neuroscience",
        "bioinformatics",
        "microbiology",
        "cancer biology",
        "ecology",
        "biophysics",
        "evolutionary biology",
        "cell biology",
        "plant biology",
        "molecular biology",
        "immunology",
        "biochemistry",
        "genomics",
        "epidemiology",
        "bioengineering",
        "neurology",
        "public and global health",
        "genetics",
        "cardiovascular medicine",
        "psychiatry and clinical psychology",
        "genetic and genomic medicine",
        "health informatics",
        "developmental biology",
        "physiology",
        "systems biology",
        "infectious diseases",
        "pharmacology and toxicology",
        "radiology and imaging",
        "animal behavior and cognition",
        "synthetic biology",
        "pathology",
        "oncology",
        "hiv aids",
        "rehabilitation medicine and physical therapy",
        "obstetrics and gynecology",
        "endocrinology",
        "surgery",
        "ophthalmology",
        "health policy",
        "sexual and reproductive health",
        "emergency medicine",
        "health economics",
        "medical education",
        "intensive care and critical care medicine",
        "orthopedics",
        "nephrology",
        "pediatrics",
        "health systems and quality improvement",
        "allergy and immunology",
        "respiratory medicine",
        "sports medicine",
        "occupational and environmental health",
        "geriatric medicine",
        "anesthesia",
        "pain medicine",
        "transplantation",
        "rheumatology",
        "nutrition",
        "paleontology",
        "pharmacology and therapeutics",
        "zoology",
        "nursing",
        "gastroenterology",
        "addiction medicine",
        "medical ethics",
        "toxicology",
        "dentistry and oral medicine",
        "primary care research",
        "scientific communication and education",
        "otolaryngology",
    ]
    assert len(observed) == 70
    unmapped = [label for label in observed if not fields_for([{"scheme": "biorxiv", "id": label}])]
    assert unmapped == []


# --- MeSH is deliberately unmapped ------------------------------------------


def test_mesh_descriptors_contribute_no_field():
    # Europe PMC supplies the descriptor term and not its tree number, so there
    # is no hierarchy to climb. See docs/adr/0009.
    topics = [{"scheme": "mesh", "id": "Neoplasms", "label": "Neoplasms"}]
    assert fields_for(topics) == ()


def test_mesh_is_reported_as_unmapped_rather_than_ignored():
    topics = [{"scheme": "mesh", "id": "Neoplasms"}]
    assert unmapped_topics(topics) == (("mesh", "Neoplasms"),)


# --- combining what several sources supplied --------------------------------


def test_fields_are_deduplicated_and_sorted():
    topics = [
        {"scheme": "arxiv", "id": "cs.LG"},
        {"scheme": "openalex", "field": "Computer Science"},
        {"scheme": "biorxiv", "id": "neuroscience"},
    ]
    assert fields_for(topics) == ("computer-science", "neuroscience")


def test_a_paper_with_no_topics_has_no_fields():
    assert fields_for([]) == ()
    assert fields_for(None) == ()


def test_malformed_topic_entries_are_survived():
    topics = [None, "neuroscience", 7, {"scheme": "arxiv"}, {"id": "cs.LG"}]
    assert fields_for(topics) == ()


def test_unmapped_reports_only_what_carried_a_value():
    topics = [
        {"scheme": "arxiv", "id": "cs.LG"},
        {"scheme": "arxiv", "id": "xyz.QQ"},
        {"scheme": "openalex", "id": "T1"},
        {"scheme": "biorxiv", "id": "quantum astrology"},
    ]
    assert unmapped_topics(topics) == (
        ("arxiv", "xyz.QQ"),
        ("biorxiv", "quantum astrology"),
    )


def test_field_slugs_is_the_filterable_vocabulary():
    assert field_slugs() == tuple(sorted(f.slug for f in FIELDS))
