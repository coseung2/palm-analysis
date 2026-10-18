#!/usr/bin/env python3
"""Phase 3 -- export & quantization. See ../plan.md.

    python export_onnx.py --checkpoint runs/exp1/checkpoints/best.pt --out exported/student.onnx

Produces:
    <out>                 fp32 ONNX, static 1x3xHxW input
    <out stem>_fp16.onnx  weights cast to fp16 (I/O stays fp32), ~2x smaller
    <out stem>_int8.onnx  dynamic-quantized, only with --int8

Verifies PyTorch vs onnxruntime(CPU) output parity for each variant it
produces. onnxruntime-web parity (browser) is a separate, JS-side check --
see the "Verification checklist" in ../plan.md; this script only covers the
Python-side half of that check.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import onnx
import onnxruntime as ort
import torch

from model import build_student_model


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--checkpoint", required=True)
    ap.add_argument("--out", default="exported/student.onnx")
    ap.add_argument("--img_size", type=int, default=None, help="override; default reads from checkpoint metadata")
    ap.add_argument("--encoder", default=None, help="override; default reads from checkpoint metadata")
    ap.add_argument("--opset", type=int, default=17)
    ap.add_argument("--fp16", action=argparse.BooleanOptionalAction, default=True)
    ap.add_argument("--int8", action=argparse.BooleanOptionalAction, default=False)
    ap.add_argument("--atol_fp32", type=float, default=1e-3)
    ap.add_argument("--atol_fp16", type=float, default=1e-2)
    ap.add_argument("--n_check_batches", type=int, default=4)
    return ap.parse_args()


def load_model(checkpoint_path: str, encoder_override: str | None, img_size_override: int | None):
    ckpt = torch.load(checkpoint_path, map_location="cpu")
    if isinstance(ckpt, dict) and "model" in ckpt:
        state = ckpt["model"]
        encoder = ckpt.get("encoder", "mit_b0")
        img_size = ckpt.get("img_size", 512)
    else:
        state = ckpt
        encoder = "mit_b0"
        img_size = 512
    encoder = encoder_override or encoder
    img_size = img_size_override or img_size

    model = build_student_model(encoder_name=encoder, encoder_weights=None)
    model.load_state_dict(state)
    model.eval()
    return model, encoder, img_size


def check_parity(pytorch_model: torch.nn.Module, onnx_path: Path, img_size: int, n_batches: int, atol: float) -> None:
    sess = ort.InferenceSession(str(onnx_path), providers=["CPUExecutionProvider"])
    input_name = sess.get_inputs()[0].name

    max_diff = 0.0
    with torch.no_grad():
        for i in range(n_batches):
            torch.manual_seed(i)
            x = torch.randn(1, 3, img_size, img_size)
            torch_out = pytorch_model(x).numpy()
            onnx_out = sess.run(None, {input_name: x.numpy()})[0]
            diff = float(np.max(np.abs(torch_out - onnx_out)))
            max_diff = max(max_diff, diff)

    status = "OK" if max_diff <= atol else "EXCEEDS TOLERANCE"
    print(f"  parity vs pytorch: max_abs_diff={max_diff:.6f} (atol={atol}) [{status}]")
    if max_diff > atol:
        print(f"  WARNING: {onnx_path.name} parity check exceeded tolerance -- inspect before shipping")


def main() -> None:
    args = parse_args()
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    model, encoder, img_size = load_model(args.checkpoint, args.encoder, args.img_size)
    print(f"loaded checkpoint: encoder={encoder} img_size={img_size}")

    dummy = torch.randn(1, 3, img_size, img_size)
    torch.onnx.export(
        model,
        dummy,
        str(out_path),
        opset_version=args.opset,
        input_names=["input"],
        output_names=["logits"],
        dynamic_axes=None,
        dynamo=False,  # legacy TorchScript-based exporter: no onnxscript dep, proven for SMP/timm encoders
    )
    onnx.checker.check_model(onnx.load(str(out_path)))
    size_mb = out_path.stat().st_size / 1e6
    print(f"exported fp32: {out_path} ({size_mb:.1f} MB)")
    check_parity(model, out_path, img_size, args.n_check_batches, args.atol_fp32)

    if args.fp16:
        from onnxconverter_common import float16

        fp16_path = out_path.with_name(f"{out_path.stem}_fp16{out_path.suffix}")
        fp32_model = onnx.load(str(out_path))
        fp16_model = float16.convert_float_to_float16(fp32_model, keep_io_types=True)
        onnx.save(fp16_model, str(fp16_path))
        size_mb = fp16_path.stat().st_size / 1e6
        print(f"exported fp16: {fp16_path} ({size_mb:.1f} MB)")
        check_parity(model, fp16_path, img_size, args.n_check_batches, args.atol_fp16)

    if args.int8:
        from onnxruntime.quantization import QuantType, quantize_dynamic

        int8_path = out_path.with_name(f"{out_path.stem}_int8{out_path.suffix}")
        quantize_dynamic(str(out_path), str(int8_path), weight_type=QuantType.QInt8)
        size_mb = int8_path.stat().st_size / 1e6
        print(f"exported int8: {int8_path} ({size_mb:.1f} MB)")
        check_parity(model, int8_path, img_size, args.n_check_batches, atol=5e-2)

    print("done.")


if __name__ == "__main__":
    main()
