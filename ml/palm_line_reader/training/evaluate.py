#!/usr/bin/env python3
"""Per-line metrics for an exported ONNX model on a held-out (ideally hard) set.

The published 0.81 is the mean foreground Dice over all lines on a validation
split drawn from the same distribution as training. That average hid a weak
life line, and the split has none of the framings that broke the model on real
booth photos. Keep a separate hard set and report every line on its own:

    python evaluate.py --model exported/student.onnx --data_dir hard_set \
        --tags hard_set/tags.csv --mirror_tta

hard_set/ uses the training layout (images/<stem>.png, masks/<stem>.png).
tags.csv (optional) has columns stem,tag (e.g. closeup, dark, blur, rotated) and
adds a per-tag breakdown, so a regression on close-ups is visible on its own.

Metrics per line: Dice, centreline Dice (clDice on hard skeletons), and the
rate at which the line comes out as exactly one connected component.
"""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np
from scipy import ndimage
from skimage.morphology import skeletonize

MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)
LINES = {1: "heart", 2: "head", 3: "life", 4: "fate"}


def predict(session, image_rgb: np.ndarray, size: int, mirror_tta: bool) -> np.ndarray:
    resized = cv2.resize(image_rgb, (size, size), interpolation=cv2.INTER_LINEAR)
    name = session.get_inputs()[0].name

    def run(img):
        x = ((img.astype(np.float32) / 255 - MEAN) / STD).transpose(2, 0, 1)[None]
        logits = session.run(None, {name: x.astype(np.float32)})[0][0]
        p = np.exp(logits - logits.max(axis=0))
        return p / p.sum(axis=0)

    probs = run(resized)
    if mirror_tta:
        probs = (probs + run(resized[:, ::-1])[:, :, ::-1]) / 2
    return probs.argmax(axis=0).astype(np.uint8)


def line_metrics(pred: np.ndarray, target: np.ndarray, cls: int) -> dict[str, float] | None:
    p, t = pred == cls, target == cls
    if not t.any() and not p.any():
        return None  # nothing to score for this line on this image
    dice = 2 * (p & t).sum() / (p.sum() + t.sum())
    sp, st = skeletonize(p), skeletonize(t)
    tprec = (sp & t).sum() / sp.sum() if sp.any() else 0.0
    tsens = (st & p).sum() / st.sum() if st.any() else 0.0
    cldice = 2 * tprec * tsens / (tprec + tsens) if tprec + tsens else 0.0
    single = float(ndimage.label(p, structure=np.ones((3, 3)))[1] == 1) if p.any() else 0.0
    return {"dice": float(dice), "cldice": float(cldice), "single": single}


def summarize(per_image: list[dict], classes) -> dict[str, dict[str, float]]:
    out = {}
    for c in classes:
        vals = [r[c] for r in per_image if r.get(c) is not None]
        if vals:
            out[LINES[c]] = {k: float(np.mean([v[k] for v in vals])) for k in ("dice", "cldice", "single")}
            out[LINES[c]]["n"] = len(vals)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--model", required=True)
    ap.add_argument("--data_dir", required=True)
    ap.add_argument("--tags", default=None)
    ap.add_argument("--mirror_tta", action="store_true", help="average with the mirrored prediction")
    ap.add_argument("--out", default=None, help="optional per-image CSV")
    args = ap.parse_args()

    import onnxruntime as ort

    session = ort.InferenceSession(args.model, providers=["CPUExecutionProvider"])
    shape = session.get_inputs()[0].shape
    size = int(shape[-1])
    classes = tuple(range(1, int(session.get_outputs()[0].shape[1])))

    tags = defaultdict(set)
    if args.tags:
        with open(args.tags, newline="") as f:
            for row in csv.DictReader(f):
                tags[row["stem"]].add(row["tag"])

    data = Path(args.data_dir)
    per_image = []
    for image_path in sorted((data / "images").glob("*.png")):
        mask = cv2.imread(str(data / "masks" / image_path.name), cv2.IMREAD_GRAYSCALE)
        if mask is None:
            continue
        image = cv2.cvtColor(cv2.imread(str(image_path)), cv2.COLOR_BGR2RGB)
        pred = predict(session, image, size, args.mirror_tta)
        target = cv2.resize(mask, (size, size), interpolation=cv2.INTER_NEAREST)
        row = {"stem": image_path.stem, **{c: line_metrics(pred, target, c) for c in classes}}
        per_image.append(row)

    groups = {"all": per_image}
    for tag in sorted({t for ts in tags.values() for t in ts}):
        groups[tag] = [r for r in per_image if tag in tags[r["stem"]]]
    for name, rows in groups.items():
        print(f"[{name}] {len(rows)} images")
        for line, m in summarize(rows, classes).items():
            print(f"  {line:6s} dice={m['dice']:.3f} cldice={m['cldice']:.3f} single={m['single']:.2f} (n={m['n']})")

    if args.out:
        with open(args.out, "w", newline="") as f:
            fields = ["stem", *[f"{LINES[c]}_{k}" for c in classes for k in ("dice", "cldice", "single")]]
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            for r in per_image:
                flat = {"stem": r["stem"]}
                for c in classes:
                    for k in ("dice", "cldice", "single"):
                        flat[f"{LINES[c]}_{k}"] = "" if r[c] is None else f"{r[c][k]:.4f}"
                writer.writerow(flat)


if __name__ == "__main__":
    main()
