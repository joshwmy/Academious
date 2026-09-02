"""One subject vocabulary over four source taxonomies.

Every source classifies its papers, and no two of them agree. OpenAlex carries
a topic hierarchy whose middle level is a *field*; arXiv carries archive
categories such as `cs.LG`; bioRxiv and medRxiv carry a single free-text
category per preprint; Europe PMC carries MeSH descriptors. A field filter that
passed any one of those through would filter one slice of the corpus and hide
the rest - which is the failure this module exists to prevent.

**The vocabulary is OpenAlex's 26 fields.** Not because it is the best taxonomy
in the world, but because it is already the largest one in the corpus, it is
stable, it has ids, and it is broad enough to hold physics and dentistry in the
same list. Every other source is mapped onto it.

Three properties this mapping is built for, in order:

* **Total over what we have observed.** The bioRxiv table covers all 70 category
  labels present in the deployed corpus, and the arXiv table covers every
  archive. New labels appear as *unmapped*, never as a guess.
* **Coarse on purpose.** `cs.LG` and `cs.DB` are both Computer Science. A finer
  mapping would be inventing precision the source vocabulary does not carry, and
  a field facet is a browsing aid, not a classification system.
* **Silent on what it cannot map.** MeSH descriptors reach us as terms rather
  than tree numbers, so there is no hierarchy to climb; a MeSH-only paper gets
  no field rather than a guessed one, and `unmapped_topics` reports it so the
  gap is measurable instead of invisible. See ADR 0009.

A paper's fields are derived from its merged topics and stored on `paper.fields`
so that filtering is one indexed array overlap rather than a mapping table
joined at query time.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class Field:
    """One entry in the shared vocabulary."""

    #: URL-safe identifier. This is what the API accepts and the frontend sends.
    slug: str
    #: OpenAlex's display name, shown to a reader unchanged.
    label: str
    #: OpenAlex field id, so the vocabulary can be re-derived from upstream.
    openalex_id: str


#: OpenAlex's field level, fetched from `api.openalex.org/fields` (26 entries,
#: ids 11-36). Ordered by id, which is also ASJC's ordering.
FIELDS: tuple[Field, ...] = (
    Field("agricultural-and-biological-sciences", "Agricultural and Biological Sciences", "11"),
    Field("arts-and-humanities", "Arts and Humanities", "12"),
    Field(
        "biochemistry-genetics-and-molecular-biology",
        "Biochemistry, Genetics and Molecular Biology",
        "13",
    ),
    Field("business-management-and-accounting", "Business, Management and Accounting", "14"),
    Field("chemical-engineering", "Chemical Engineering", "15"),
    Field("chemistry", "Chemistry", "16"),
    Field("computer-science", "Computer Science", "17"),
    Field("decision-sciences", "Decision Sciences", "18"),
    Field("earth-and-planetary-sciences", "Earth and Planetary Sciences", "19"),
    Field("economics-econometrics-and-finance", "Economics, Econometrics and Finance", "20"),
    Field("energy", "Energy", "21"),
    Field("engineering", "Engineering", "22"),
    Field("environmental-science", "Environmental Science", "23"),
    Field("immunology-and-microbiology", "Immunology and Microbiology", "24"),
    Field("materials-science", "Materials Science", "25"),
    Field("mathematics", "Mathematics", "26"),
    Field("medicine", "Medicine", "27"),
    Field("neuroscience", "Neuroscience", "28"),
    Field("nursing", "Nursing", "29"),
    Field(
        "pharmacology-toxicology-and-pharmaceutics",
        "Pharmacology, Toxicology and Pharmaceutics",
        "30",
    ),
    Field("physics-and-astronomy", "Physics and Astronomy", "31"),
    Field("psychology", "Psychology", "32"),
    Field("social-sciences", "Social Sciences", "33"),
    Field("veterinary", "Veterinary", "34"),
    Field("dentistry", "Dentistry", "35"),
    Field("health-professions", "Health Professions", "36"),
)

BY_SLUG: dict[str, Field] = {field.slug: field for field in FIELDS}

#: OpenAlex display name, casefolded, to slug. The `field` key on an OpenAlex
#: topic is the display name, so this is the whole of that mapping.
_BY_LABEL: dict[str, str] = {field.label.casefold(): field.slug for field in FIELDS}

# --- arXiv -------------------------------------------------------------------

#: Archive prefix to field. An arXiv category is `archive.subcategory`, or a
#: bare archive for the older ones (`hep-th`, `quant-ph`, `math-ph`).
_ARXIV_ARCHIVES: dict[str, str] = {
    "astro-ph": "physics-and-astronomy",
    "cond-mat": "physics-and-astronomy",
    "cs": "computer-science",
    "econ": "economics-econometrics-and-finance",
    "eess": "engineering",
    "gr-qc": "physics-and-astronomy",
    "hep-ex": "physics-and-astronomy",
    "hep-lat": "physics-and-astronomy",
    "hep-ph": "physics-and-astronomy",
    "hep-th": "physics-and-astronomy",
    "math": "mathematics",
    "math-ph": "physics-and-astronomy",
    "nlin": "physics-and-astronomy",
    "nucl-ex": "physics-and-astronomy",
    "nucl-th": "physics-and-astronomy",
    "physics": "physics-and-astronomy",
    "q-bio": "agricultural-and-biological-sciences",
    "q-fin": "economics-econometrics-and-finance",
    "quant-ph": "physics-and-astronomy",
    "stat": "mathematics",
}

#: Subcategories whose archive would be actively misleading. Kept short on
#: purpose: an override earns its place by moving a category into a field a
#: reader would look for it under, not by being more specific.
_ARXIV_CATEGORIES: dict[str, str] = {
    "cond-mat.mtrl-sci": "materials-science",
    "physics.ao-ph": "earth-and-planetary-sciences",
    "physics.chem-ph": "chemistry",
    "physics.geo-ph": "earth-and-planetary-sciences",
    "physics.med-ph": "medicine",
    "physics.soc-ph": "social-sciences",
    "q-bio.BM": "biochemistry-genetics-and-molecular-biology",
    "q-bio.CB": "biochemistry-genetics-and-molecular-biology",
    "q-bio.GN": "biochemistry-genetics-and-molecular-biology",
    "q-bio.MN": "biochemistry-genetics-and-molecular-biology",
    "q-bio.NC": "neuroscience",
    "q-bio.SC": "biochemistry-genetics-and-molecular-biology",
    "stat.ML": "computer-science",
}

# --- bioRxiv and medRxiv -----------------------------------------------------

#: Category label to field. Both servers write into the same `biorxiv` scheme,
#: so one table covers them. Every label observed in the deployed corpus on
#: 2026-09-02 is here, plus the medRxiv categories that had not yet appeared.
_BIORXIV_CATEGORIES: dict[str, str] = {
    # bioRxiv
    "animal behavior and cognition": "agricultural-and-biological-sciences",
    "biochemistry": "biochemistry-genetics-and-molecular-biology",
    "bioengineering": "engineering",
    "bioinformatics": "biochemistry-genetics-and-molecular-biology",
    "biophysics": "biochemistry-genetics-and-molecular-biology",
    "cancer biology": "biochemistry-genetics-and-molecular-biology",
    "cell biology": "biochemistry-genetics-and-molecular-biology",
    "clinical trials": "medicine",
    "developmental biology": "biochemistry-genetics-and-molecular-biology",
    "ecology": "agricultural-and-biological-sciences",
    "evolutionary biology": "agricultural-and-biological-sciences",
    "genetics": "biochemistry-genetics-and-molecular-biology",
    "genomics": "biochemistry-genetics-and-molecular-biology",
    "immunology": "immunology-and-microbiology",
    "microbiology": "immunology-and-microbiology",
    "molecular biology": "biochemistry-genetics-and-molecular-biology",
    "neuroscience": "neuroscience",
    "paleontology": "earth-and-planetary-sciences",
    "pathology": "medicine",
    "pharmacology and toxicology": "pharmacology-toxicology-and-pharmaceutics",
    "physiology": "biochemistry-genetics-and-molecular-biology",
    "plant biology": "agricultural-and-biological-sciences",
    "scientific communication and education": "social-sciences",
    "synthetic biology": "biochemistry-genetics-and-molecular-biology",
    "systems biology": "biochemistry-genetics-and-molecular-biology",
    "zoology": "agricultural-and-biological-sciences",
    # medRxiv. Clinical specialties are Medicine; the ones that are a
    # profession, an economy or a social system are not.
    "addiction medicine": "medicine",
    "allergy and immunology": "immunology-and-microbiology",
    "anesthesia": "medicine",
    "cardiovascular medicine": "medicine",
    "dentistry and oral medicine": "dentistry",
    "dermatology": "medicine",
    "emergency medicine": "medicine",
    "endocrinology": "medicine",
    "epidemiology": "medicine",
    "forensic medicine": "medicine",
    "gastroenterology": "medicine",
    "genetic and genomic medicine": "medicine",
    "geriatric medicine": "medicine",
    "health economics": "economics-econometrics-and-finance",
    "health informatics": "health-professions",
    "health policy": "medicine",
    "health systems and quality improvement": "health-professions",
    "hematology": "medicine",
    "hiv aids": "medicine",
    "infectious diseases": "medicine",
    "intensive care and critical care medicine": "medicine",
    "medical education": "medicine",
    "medical ethics": "medicine",
    "nephrology": "medicine",
    "neurology": "medicine",
    "nursing": "nursing",
    "nutrition": "medicine",
    "obstetrics and gynecology": "medicine",
    "occupational and environmental health": "medicine",
    "oncology": "medicine",
    "ophthalmology": "medicine",
    "orthopedics": "medicine",
    "otolaryngology": "medicine",
    "pain medicine": "medicine",
    "palliative medicine": "medicine",
    "pediatrics": "medicine",
    "pharmacology and therapeutics": "pharmacology-toxicology-and-pharmaceutics",
    "primary care research": "medicine",
    "psychiatry and clinical psychology": "medicine",
    "public and global health": "medicine",
    "radiology and imaging": "medicine",
    "rehabilitation medicine and physical therapy": "health-professions",
    "respiratory medicine": "medicine",
    "rheumatology": "medicine",
    "sexual and reproductive health": "medicine",
    "sports medicine": "medicine",
    "surgery": "medicine",
    "toxicology": "pharmacology-toxicology-and-pharmaceutics",
    "transplantation": "medicine",
    "urology": "medicine",
}

#: Schemes carrying a taxonomy this module does not map. Listed rather than
#: implied, so that a paper classified only in MeSH is a *measured* gap.
UNMAPPED_SCHEMES: frozenset[str] = frozenset({"mesh"})


def is_field(slug: str) -> bool:
    """Whether `slug` names a field in the shared vocabulary."""
    return slug in BY_SLUG


def field_slugs() -> tuple[str, ...]:
    """Every filterable field slug, sorted."""
    return tuple(sorted(BY_SLUG))


def describe() -> list[dict[str, str]]:
    """The vocabulary as JSON-safe rows, ordered by label."""
    return [
        {"slug": field.slug, "label": field.label, "openalex_id": field.openalex_id}
        for field in sorted(FIELDS, key=lambda f: f.label)
    ]


def fields_for(topics: Iterable[Any] | None) -> tuple[str, ...]:
    """Derive a paper's fields from its merged topics.

    Deduplicated and sorted, so the stored value is stable and two papers with
    the same subjects compare equal regardless of the order their sources
    arrived in.
    """
    slugs: set[str] = set()
    for topic in topics or ():
        slug = _field_of(topic)
        if slug is not None:
            slugs.add(slug)
    return tuple(sorted(slugs))


def unmapped_topics(topics: Iterable[Any] | None) -> tuple[tuple[str, str], ...]:
    """`(scheme, value)` for every topic that carried a value but mapped to no field.

    This is the measurement half of the module: it is what a backfill or an
    ingestion metric reports so that an unrecognised category shows up as a
    number rather than as a quietly unclassified paper.
    """
    missing: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for topic in topics or ():
        if not isinstance(topic, Mapping):
            continue
        scheme = _text(topic.get("scheme"))
        value = _unmapped_value(topic, scheme)
        if not scheme or not value or _field_of(topic) is not None:
            continue
        key = (scheme, value)
        if key not in seen:
            seen.add(key)
            missing.append(key)
    return tuple(missing)


def _unmapped_value(topic: Mapping[str, Any], scheme: str) -> str:
    """What an unmapped topic should be reported *as*.

    For arXiv and bioRxiv that is the category, which is the thing a mapping
    table would gain an entry for. For OpenAlex it is the field name: a topic
    carrying no field at all is a gap in the record rather than a vocabulary we
    failed to recognise, and reporting its topic id would fill the report with
    ids nobody can act on.
    """
    if scheme.casefold() == "openalex":
        return _text(topic.get("field"))
    return _topic_value(topic)


def _field_of(topic: Any) -> str | None:
    if not isinstance(topic, Mapping):
        return None
    scheme = _text(topic.get("scheme")).casefold()
    if scheme == "openalex":
        label = _text(topic.get("field"))
        return _BY_LABEL.get(label.casefold()) if label else None
    if scheme == "arxiv":
        return _arxiv_field(_topic_value(topic))
    if scheme == "biorxiv":
        category = _topic_value(topic)
        return _BIORXIV_CATEGORIES.get(category.casefold()) if category else None
    return None


def _arxiv_field(category: str) -> str | None:
    if not category:
        return None
    override = _ARXIV_CATEGORIES.get(_canonical_arxiv(category))
    if override is not None:
        return override
    archive = category.split(".", 1)[0].casefold()
    return _ARXIV_ARCHIVES.get(archive)


def _canonical_arxiv(category: str) -> str:
    """Normalise an arXiv category for the override table.

    Archives are lower-case; subcategories are upper-case except where they are
    not (`cond-mat.mtrl-sci`, `physics.med-ph`). Match the archive
    case-insensitively and try the subcategory both as written and upper-cased.
    """
    archive, _, subcategory = category.partition(".")
    if not subcategory:
        return archive.casefold()
    lowered = f"{archive.casefold()}.{subcategory.casefold()}"
    if lowered in _ARXIV_CATEGORIES:
        return lowered
    return f"{archive.casefold()}.{subcategory.upper()}"


def _topic_value(topic: Mapping[str, Any]) -> str:
    """The category a non-OpenAlex source classified under.

    `id` and `label` are the same string for arXiv and bioRxiv, but `id` is
    what the connector writes first, so it is what is trusted.
    """
    return _text(topic.get("id")) or _text(topic.get("label"))


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""
