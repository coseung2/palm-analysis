#!/usr/bin/env python3
"""Rank pseudo-label masks by how suspicious they look, worst first.

The teacher draws the life line short on ordinary RGB photos (plan.md, Phase 1),
and the shipped student inherited that: on real photos it often painted the
vertical crease in the palm centre (where a fate line runs) as "life". This
script finds the masks most likely to teach exactly that, so review time in
label_tool.py goes to them first:

    python audit_labels.py --data_dir data --out audit.csv

Flags (a mask can have several):
  missing_<line>     class absent
  fragmented_<line>  more than one connected component
  life_short         life skeleton shorter than --life_ratio x the longer of heart/head
  life_straight      life line nearly straight (a real life line arcs round the thumb)
  life_far_from_head life line nowhere near either end of the head line (they usually
                     start together between thumb and index finger)

Nothing is changed on disk. Feed the top of audit.csv to label_tool.py and mark
each mask edited/approved/rejected there; dataset.py honours that verdict.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import cv2
import numpy as np
from scipy import ndimage
from skimage.morphology import skeletonize

LINES = {1: "heart", 2: "head", 3: "life", 4: "fate"}


def _skeleton(mask: np.ndarray, cls: int) -> np.ndarray:
    return skeletonize(mask == cls)


def _endpoints(skel: np.ndarray) -> np.ndarray:
    kernel = np.ones((3, 3), dtype=np.uint8)
    kernel[1, 1] = 0
    neighbours = ndimage.convolve(skel.astype(np.uint8), kernel, mode="constant")
    ys, xs = np.nonzero(skel & (neighbours == 1))
    return np.stack([ys, xs], axis=1)


def straightness(skel: np.ndarray) -> float:
    """Max distance of skeleton pixels from the chord between its farthest endpoints,
    relative to chord length. ~0 for a straight segment, larger for an arc."""
    ys, xs = np.nonzero(skel)
    if len(ys) < 2:
        return 0.0
    ends = _endpoints(skel)
    pts = ends if len(ends) >= 2 else np.stack([ys, xs], axis=1)
    d = np.linalg.norm(pts[:, None, :] - pts[None, :, :], axis=-1)
    i, j = np.unravel_index(np.argmax(d), d.shape)
    a, b = pts[i].astype(float), pts[j].astype(float)
    chord = np.linalg.norm(b - a)
    if chord < 1:
        return 0.0
    p = np.stack([ys, xs], axis=1).astype(float)
    cross = np.abs((b[0] - a[0]) * (p[:, 1] - a[1]) - (b[1] - a[1]) * (p[:, 0] - a[0]))
    return float((cross / chord).max() / chord)


def audit_mask(mask: np.ndarray, life_ratio: float = 0.6, straight_max: float = 0.06, near_frac: float = 0.15):
    size = max(mask.shape)
    skels = {c: _skeleton(mask, c) for c in LINES if c <= max(3, int(mask.max()))}
    lengths = {c: int(s.sum()) for c, s in skels.items()}
    flags = []
    for c, skel in skels.items():
        if c == 4 and not skel.any():
            continue  # the fate line is optional in labels
        if not skel.any():
            flags.append(f"missing_{LINES[c]}")
            continue
        _, n = ndimage.label(mask == c, structure=np.ones((3, 3)))
        if n > 1:
            flags.append(f"fragmented_{LINES[c]}")
    life, head = skels.get(3), skels.get(2)
    if life is not None and life.any():
        if lengths[3] < life_ratio * max(lengths.get(1, 0), lengths.get(2, 0)):
            flags.append("life_short")
        if straightness(life) < straight_max:
            flags.append("life_straight")
        if head is not None and head.any():
            head_ends = _endpoints(head)
            if len(head_ends):
                dist = ndimage.distance_transform_edt(~life)
                if min(dist[y, x] for y, x in head_ends) > near_frac * size:
                    flags.append("life_far_from_head")
    # Life-line problems are the known failure, so they weigh more than generic ones.
    score = sum(2 if f.startswith("life_") or f == "missing_life" else 1 for f in flags)
    return score, flags, lengths


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data_dir", default="data")
    ap.add_argument("--out", default="audit.csv")
    ap.add_argument("--life_ratio", type=float, default=0.6)
    ap.add_argument("--straight_max", type=float, default=0.06)
    ap.add_argument("--near_frac", type=float, default=0.15)
    args = ap.parse_args()

    rows = []
    for path in sorted((Path(args.data_dir) / "masks").glob("*.png")):
        mask = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if mask is None:
            continue
        score, flags, lengths = audit_mask(mask, args.life_ratio, args.straight_max, args.near_frac)
        rows.append(
            {
                "stem": path.stem,
                "score": score,
                "flags": " ".join(flags),
                **{f"len_{LINES[c]}": lengths.get(c, 0) for c in LINES},
            }
        )
    rows.sort(key=lambda r: (-r["score"], r["stem"]))
    with open(args.out, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["stem", "score", "flags", *[f"len_{n}" for n in LINES.values()]])
        writer.writeheader()
        writer.writerows(rows)
    flagged = sum(1 for r in rows if r["score"])
    print(f"{len(rows)} masks audited, {flagged} flagged -> {args.out}")


if __name__ == "__main__":
    main()
