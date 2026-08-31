"""Export SPECTER2 to ONNX, and quantise the export to int8.

RETR-005. The stack runs stock PyTorch fp32 at a measured 1.29-1.41 papers per
second; published int8 speedups for BERT-base run 2.7-3.4x, which makes this the
largest known lever on embedding throughput and the difference between a
backfill that fits on the deployment box and one that does not.

Two graphs are exported, not one. SPECTER2 is a shared encoder plus two task
adapters - `proximity` for documents, `adhoc_query` for short queries - switched
in place at run time. An ONNX graph is static, so an adapter that is chosen per
call cannot be a graph input: each active adapter becomes its own file.

What is exported is a wrapper that returns the CLS vector, not the full hidden
state. The pooling is part of the model's documented contract, and returning a
(batch, 768) tensor rather than (batch, sequence, 768) removes the largest
output copy from every call.

The output is written under `data/onnx/`, which is not tracked: these are build
artefacts derived from pinned upstream revisions, reproducible by re-running
this script, and too large to commit. The revisions are the ones in
`embeddings/specter2.py`, so an export always corresponds to known weights.

    python scripts/export_onnx.py                    # fp32 and int8
    python scripts/export_onnx.py --skip-quantise    # fp32 only
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from academious.embeddings.specter2 import (  # noqa: E402
    BASE_MODEL,
    BASE_MODEL_REVISION,
    DIMENSION,
    DOCUMENT_ADAPTER_NAME,
    MAX_SEQUENCE_LENGTH,
    PROXIMITY_ADAPTER,
    PROXIMITY_ADAPTER_REVISION,
    QUERY_ADAPTER,
    QUERY_ADAPTER_NAME,
    QUERY_ADAPTER_REVISION,
)

DEFAULT_OUTPUT_DIR = REPO_ROOT / "data" / "onnx"

#: 17 covers every operator bert-base needs and is what onnxruntime's own
#: transformer tooling targets. Raising it buys nothing here.
OPSET = 17

#: Enough tokens to exercise attention properly during tracing. The graph is
#: dynamic on both axes, so this is a tracing input, not a limit.
TRACE_SEQUENCE_LENGTH = 64

#: bert-base. The fusion pass needs the head count to recognise attention.
NUM_ATTENTION_HEADS = 12


def _wrapper(model, torch):
    """Wrap the adapter model so its output is the CLS vector alone."""

    class ClsEncoder(torch.nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.model = model

        def forward(self, input_ids, attention_mask):  # noqa: ANN001, ANN201
            output = self.model(input_ids=input_ids, attention_mask=attention_mask)
            # SPECTER2 pools by taking the CLS position, per the model card.
            return output.last_hidden_state[:, 0, :]

    return ClsEncoder().eval()


def export_adapter(model, tokenizer, adapter: str, destination: Path, torch) -> Path:
    """Trace one active adapter into its own ONNX graph."""
    model.set_active_adapters(adapter)
    wrapper = _wrapper(model, torch)

    example = tokenizer(
        ["title [SEP] abstract"] * 2,
        padding="max_length",
        truncation=True,
        max_length=TRACE_SEQUENCE_LENGTH,
        return_tensors="pt",
        return_token_type_ids=False,
    )

    destination.parent.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    with torch.inference_mode():
        torch.onnx.export(
            wrapper,
            (example["input_ids"], example["attention_mask"]),
            str(destination),
            input_names=["input_ids", "attention_mask"],
            output_names=["embedding"],
            dynamic_axes={
                "input_ids": {0: "batch", 1: "sequence"},
                "attention_mask": {0: "batch", 1: "sequence"},
                "embedding": {0: "batch"},
            },
            opset_version=OPSET,
            do_constant_folding=True,
            dynamo=False,
        )
    size_mb = destination.stat().st_size / 1e6
    print(f"  {adapter:12} -> {destination.name}  {size_mb:7.1f} MB  "
          f"({time.perf_counter() - started:.1f}s)")
    return destination


def fuse(source: Path, destination: Path) -> Path:
    """Transformer-aware graph fusion, before quantisation.

    A traced export is a flat graph of primitive operators. ONNX Runtime's
    transformer optimiser recognises the attention and layer-norm patterns in it
    and replaces each with one fused kernel. Published int8 speedups for
    bert-base assume this has happened: quantising the unfused graph leaves most
    of the win on the table, because what remains is per-operator overhead that
    quantisation does not touch.
    """
    from onnxruntime.transformers import optimizer

    started = time.perf_counter()
    optimised = optimizer.optimize_model(
        str(source),
        model_type="bert",
        num_heads=NUM_ATTENTION_HEADS,
        hidden_size=DIMENSION,
        opt_level=1,
    )
    optimised.save_model_to_file(str(destination))
    size_mb = destination.stat().st_size / 1e6
    print(
        f"  fused        -> {destination.name}  {size_mb:7.1f} MB  "
        f"({time.perf_counter() - started:.1f}s)"
    )
    return destination


def quantise(source: Path, destination: Path) -> Path:
    """Dynamic int8 quantisation: weights int8, activations quantised per call.

    Dynamic rather than static because static needs a calibration corpus and a
    decision about what is representative of it. Dynamic quantisation of a
    transformer's MatMul weights is where the speedup overwhelmingly comes from,
    and it needs no calibration data to be honest about.

    `per_channel` is off: a per-tensor scale is what the fused int8 MatMul
    kernels are written for, and per-channel costs more than the accuracy it
    buys on an encoder this size.
    """
    import onnx
    from onnxruntime.quantization import QuantType, quantize_dynamic

    started = time.perf_counter()
    quantize_dynamic(
        model_input=str(source),
        model_output=str(destination),
        weight_type=QuantType.QInt8,
        per_channel=False,
        reduce_range=False,
        extra_options={
            "MatMulConstBOnly": True,
            # Fusion replaces standard operators with ORT's own, and shape
            # inference cannot type the tensors flowing between them. Without
            # this the quantiser stops at the first fused MatMul.
            "DefaultTensorType": onnx.TensorProto.FLOAT,
        },
    )
    size_mb = destination.stat().st_size / 1e6
    print(f"  int8         -> {destination.name}  {size_mb:7.1f} MB  "
          f"({time.perf_counter() - started:.1f}s)")
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--skip-quantise", action="store_true")
    parser.add_argument(
        "--reuse-fp32",
        action="store_true",
        help="skip tracing and fuse/quantise the fp32 graphs already on disk",
    )
    parser.add_argument("--cache-dir", default=None, help="HuggingFace cache directory")
    args = parser.parse_args()

    import torch
    from adapters import AutoAdapterModel
    from transformers import AutoTokenizer

    print(f"Loading {BASE_MODEL} at {BASE_MODEL_REVISION[:12]}")
    tokenizer = AutoTokenizer.from_pretrained(
        BASE_MODEL, revision=BASE_MODEL_REVISION, cache_dir=args.cache_dir
    )
    model = AutoAdapterModel.from_pretrained(
        BASE_MODEL, revision=BASE_MODEL_REVISION, cache_dir=args.cache_dir
    )
    model.load_adapter(
        PROXIMITY_ADAPTER,
        source="hf",
        revision=PROXIMITY_ADAPTER_REVISION,
        load_as=DOCUMENT_ADAPTER_NAME,
        set_active=True,
    )
    model.load_adapter(
        QUERY_ADAPTER,
        source="hf",
        revision=QUERY_ADAPTER_REVISION,
        load_as=QUERY_ADAPTER_NAME,
        set_active=False,
    )
    model.eval()

    hidden = int(model.config.hidden_size)
    if hidden != DIMENSION:
        raise RuntimeError(f"expected {DIMENSION}-d embeddings, model reports {hidden}")

    exported: dict[str, Path] = {}
    if args.reuse_fp32:
        print("\nReusing the fp32 graphs on disk")
        for adapter in (DOCUMENT_ADAPTER_NAME, QUERY_ADAPTER_NAME):
            path = args.output_dir / f"specter2-{adapter}-fp32.onnx"
            if not path.exists():
                raise FileNotFoundError(f"{path} does not exist; run without --reuse-fp32")
            exported[adapter] = path
    else:
        print(f"\nExporting fp32 (opset {OPSET}, max sequence {MAX_SEQUENCE_LENGTH})")
        for adapter in (DOCUMENT_ADAPTER_NAME, QUERY_ADAPTER_NAME):
            exported[adapter] = export_adapter(
                model, tokenizer, adapter, args.output_dir / f"specter2-{adapter}-fp32.onnx", torch
            )

    if args.skip_quantise:
        print("\nSkipping fusion and quantisation.")
        return 0

    print("\nFusing, then quantising to int8")
    for adapter, source in exported.items():
        fused = fuse(source, args.output_dir / f"specter2-{adapter}-fused.onnx")
        quantise(fused, args.output_dir / f"specter2-{adapter}-int8.onnx")

    print(f"\nWritten to {args.output_dir}")
    print("Verify fidelity and throughput before using these: scripts/benchmark_onnx.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
