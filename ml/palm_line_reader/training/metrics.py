"""Validation metrics — see ../plan.md, Phase 2, item 5.

Per-class Dice is the usual quality signal. Connected-component count is the
metric that tells you whether the topology losses (clDice + connectivity
regularizer) are actually working: the target is exactly one component per
present line class. Mean skeleton distance is the eval-time counterpart of
losses.skeleton_distance_loss: whether a predicted line, when there is one,
sits in the right place -- not just whether pixels overlap.
"""

from __future__ import annotations

import numpy as np
from typing import Dict, List, Sequence

import torch
from scipy import ndimage
from skimage.morphology import skeletonize

from losses import FOREGROUND_CLASSES, NUM_CLASSES


@torch.no_grad()
def dice_per_class(
    pred: torch.Tensor, target: torch.Tensor, num_classes: int = NUM_CLASSES, smooth: float = 1.0
) -> Dict[int, float]:
    out = {}
    for c in range(num_classes):
        p = (pred == c).float()
        t = (target == c).float()
        inter = (p * t).sum()
        denom = p.sum() + t.sum()
        out[c] = float((2 * inter + smooth) / (denom + smooth))
    return out


@torch.no_grad()
def component_counts(pred: torch.Tensor, classes: Sequence[int] = FOREGROUND_CLASSES) -> Dict[int, List[int]]:
    """Per-class connected-component count for each item in the batch.

    A class absent from a given prediction is skipped (not counted as a
    fragmentation failure) — this metric is about "when the model draws a
    line, is it one line", not about recall.
    """
    pred_np = pred.cpu().numpy()
    out: Dict[int, List[int]] = {c: [] for c in classes}
    for b in range(pred_np.shape[0]):
        for c in classes:
            binary = pred_np[b] == c
            if not binary.any():
                continue
            _, n = ndimage.label(binary)
            out[c].append(n)
    return out


def single_component_rate(counts: Dict[int, List[int]]) -> Dict[int, float]:
    rates = {}
    for c, vals in counts.items():
        rates[c] = (sum(1 for v in vals if v == 1) / len(vals)) if vals else float("nan")
    return rates


@torch.no_grad()
def mean_skeleton_distance_px(
    pred: torch.Tensor,
    target: torch.Tensor,
    classes: Sequence[int] = FOREGROUND_CLASSES,
    max_distance: float = 32.0,
) -> Dict[int, float]:
    """Average distance (px) from each predicted skeleton pixel to the
    nearest target skeleton pixel, per class. Samples where either skeleton
    is empty are skipped -- dice_per_class / single_component_rate already
    cover presence, this is purely about positional accuracy.
    """
    pred_np = pred.cpu().numpy()
    target_np = target.cpu().numpy()
    sums = {c: 0.0 for c in classes}
    counts = {c: 0 for c in classes}
    for b in range(pred_np.shape[0]):
        for c in classes:
            p_skel = skeletonize(pred_np[b] == c)
            t_skel = skeletonize(target_np[b] == c)
            if not p_skel.any() or not t_skel.any():
                continue
            dist_field = ndimage.distance_transform_edt(~t_skel)
            d = float(np.clip(dist_field[p_skel], 0, max_distance).mean())
            sums[c] += d
            counts[c] += 1
    return {c: (sums[c] / counts[c] if counts[c] else float("nan")) for c in classes}
