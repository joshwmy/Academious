"""The ONNX Runtime embedding backend (RETR-005).

Most of this needs neither the graphs nor a model: what it checks is that the
backend refuses to be ambiguous about which weights produced a vector, and that
it fails loudly when the graphs are missing rather than silently falling back to
something else.

The tests that do load graphs are marked `model` and skip when they are not on
disk, because they are build artefacts under `data/onnx/` rather than anything
committed. They assert the property the whole measurement rests on: the fp32
export reproduces PyTorch, so a difference measured against int8 is quantisation
error and not an export bug.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from academious.embeddings.backend import EmbeddingBackend
from academious.embeddings.onnx_specter2 import (
    PRECISIONS,
    OnnxSpecter2Backend,
    graph_path,
)
from academious.embeddings.registry import (
    PROFILES,
    SPECTER2_AUTO,
    SPECTER2_ONNX_FP32,
    SPECTER2_ONNX_INT8,
    build_backend,
)
from academious.embeddings.specter2 import DOCUMENT_ADAPTER_NAME, QUERY_ADAPTER_NAME

GRAPH_DIR = Path("data/onnx")


def graphs_present(precision: str) -> bool:
    return all(
        graph_path(GRAPH_DIR, adapter, precision).exists()
        for adapter in (DOCUMENT_ADAPTER_NAME, QUERY_ADAPTER_NAME)
    )


# ------------------------------------------------------------------- identity


@pytest.mark.parametrize("precision", PRECISIONS)
def test_the_model_id_names_the_precision(precision):
    """A stored vector has to say which weights produced it.

    int8 and fp32 vectors of the same paper are different vectors. If both
    reported the same model_id they would be indistinguishable once written, and
    the corpus would hold two incompatible notions of distance under one name.
    """
    backend = OnnxSpecter2Backend(precision=precision)
    assert backend.model_id.endswith(f"onnx-{precision}")


def test_the_two_precisions_do_not_share_a_model_id():
    assert (
        OnnxSpecter2Backend(precision="fp32").model_id
        != OnnxSpecter2Backend(precision="int8").model_id
    )


def test_an_unknown_precision_is_rejected_at_construction():
    # Not at first encode: a typo should fail before anything is embedded with it.
    with pytest.raises(ValueError, match="precision must be one of"):
        OnnxSpecter2Backend(precision="int4")


def test_the_backend_satisfies_the_embedding_protocol():
    assert isinstance(OnnxSpecter2Backend(precision="int8"), EmbeddingBackend)


# -------------------------------------------------------------------- profiles


def test_the_int8_profile_has_its_own_key():
    """Quantised vectors are never mixed with production ones."""
    assert SPECTER2_ONNX_INT8.key != SPECTER2_AUTO.key
    assert SPECTER2_ONNX_INT8.key in PROFILES


def test_the_fp32_profile_shares_the_production_key():
    """The fp32 graph reproduces PyTorch, so its vectors *are* the production vectors.

    A separate key would fragment one corpus into two that cannot be searched
    together, for a difference the measurement says does not exist.
    """
    assert SPECTER2_ONNX_FP32.key == SPECTER2_AUTO.key


def test_the_default_profile_is_still_torch():
    """int8 is available, not adopted. See docs/performance.md for why."""
    assert PROFILES[SPECTER2_AUTO.key].backend_name == "specter2"


@pytest.mark.parametrize(
    ("backend_name", "precision"), [("onnx-fp32", "fp32"), ("onnx-int8", "int8")]
)
def test_the_registry_builds_each_precision(backend_name, precision):
    profile = SPECTER2_ONNX_FP32 if precision == "fp32" else SPECTER2_ONNX_INT8
    assert profile.backend_name == backend_name

    backend = build_backend(profile, model_dir=GRAPH_DIR)
    assert isinstance(backend, OnnxSpecter2Backend)
    assert backend.precision == precision


# -------------------------------------------------------------------- loading


def test_missing_graphs_fail_with_the_command_that_creates_them(tmp_path):
    """An empty directory is a missing build step, not a reason to guess."""
    backend = OnnxSpecter2Backend(precision="int8", model_dir=tmp_path)
    with pytest.raises(FileNotFoundError, match="scripts/export_onnx.py"):
        backend.load()


def test_encoding_nothing_needs_no_graphs_at_all(tmp_path):
    backend = OnnxSpecter2Backend(precision="int8", model_dir=tmp_path)
    batch = backend.encode_documents([])
    assert batch.vectors.shape == (0, backend.dimension)
    assert len(batch) == 0


# ---------------------------------------------------------------- integration


@pytest.mark.model
@pytest.mark.skipif(not graphs_present("fp32"), reason="run scripts/export_onnx.py first")
def test_the_fp32_export_reproduces_pytorch():
    """The measurement in docs/performance.md depends on this being true.

    If the export were wrong, the int8 numbers would be measuring an export bug
    and quantisation error together, with no way to tell them apart.
    """
    from academious.embeddings.specter2 import Specter2Backend

    texts = [
        "Neural message passing on molecular graphs [SEP] We introduce a scheme "
        "that predicts chemical properties from structure.",
        "Transcriptomic biomarkers in breast cancer [SEP] We identify expression "
        "signatures associated with survival.",
    ]

    torch_vectors = Specter2Backend(batch_size=2).encode_documents(texts).vectors
    onnx_vectors = (
        OnnxSpecter2Backend(precision="fp32", model_dir=GRAPH_DIR, batch_size=2)
        .encode_documents(texts)
        .vectors
    )

    # Both are L2-normalised, so a row-wise dot product is cosine similarity.
    similarities = np.sum(torch_vectors * onnx_vectors, axis=1)
    assert similarities.min() > 0.9999


@pytest.mark.model
@pytest.mark.skipif(not graphs_present("int8"), reason="run scripts/export_onnx.py first")
def test_the_two_adapters_are_genuinely_different_graphs():
    """Guards a failure that would be invisible in every other measurement.

    An export that lost the active adapter would produce two identical graphs.
    Documents and queries would still encode, agreement between them would still
    look perfect, and SPECTER2's asymmetric design - the thing the model card
    says makes ad-hoc search work - would silently be gone.
    """
    backend = OnnxSpecter2Backend(precision="int8", model_dir=GRAPH_DIR, batch_size=1)
    text = ["graph neural networks for molecular property prediction"]

    as_document = backend.encode_documents(text).vectors[0]
    as_query = backend.encode_queries(text).vectors[0]

    assert float(np.dot(as_document, as_query)) < 0.999, (
        "document and query adapters produced the same vector; the export "
        "probably ran with no adapter active"
    )
