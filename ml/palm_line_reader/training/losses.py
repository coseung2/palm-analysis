"""Loss functions for palm-line student training — see ../plan.md, Phase 2.

The pseudo-labels are already single-component skeletons (thanks to the
teacher pipeline's post-processing), so the student is pushed to match that
topology and geometry, not just per-pixel overlap:

  - CE + Dice: standard multi-class pixelwise base.
  - clDice: differentiable soft-skeleton centerline Dice: rewards an
    unbroken predicted centerline rather than raw overlap, so a line
    predicted with a gap is penalized much harder than plain Dice would.
  - Skeleton distance loss: a one-directional, distance-transform-weighted
    Chamfer term that penalizes predicted skeleton mass by how far it sits
    from the nearest true skeleton pixel. Dice/clDice give equal credit to
    any overlapping pixel and are blind to *how wrong* a non-overlapping
    pixel is; this term makes a line predicted in roughly the right place
    cost less than one predicted with the wrong length or direction. It
    only looks at 1px-wide skeletons on both sides, so line thickness never
    factors in.
  - Connectivity regularizer: penalizes predicted probability mass that
    falls outside the largest connected component per line class, gated by
    a warmup so early noisy predictions aren't over-penalized.
"""

from __future__ import annotations

from typing import Sequence

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from scipy import ndimage

NUM_CLASSES = 4
FOREGROUND_CLASSES: Sequence[int] = (1, 2, 3)  # heart, head, life


def dice_loss(probs: torch.Tensor, target_onehot: torch.Tensor, smooth: float = 1.0) -> torch.Tensor:
    dims = (0, 2, 3)
    intersection = torch.sum(probs * target_onehot, dims)
    cardinality = torch.sum(probs + target_onehot, dims)
    dice = (2.0 * intersection + smooth) / (cardinality + smooth)
    return 1.0 - dice.mean()


def _soft_erode(img: torch.Tensor) -> torch.Tensor:
    p1 = -F.max_pool2d(-img, kernel_size=(3, 1), stride=1, padding=(1, 0))
    p2 = -F.max_pool2d(-img, kernel_size=(1, 3), stride=1, padding=(0, 1))
    return torch.min(p1, p2)


def _soft_dilate(img: torch.Tensor) -> torch.Tensor:
    return F.max_pool2d(img, kernel_size=3, stride=1, padding=1)


def _soft_open(img: torch.Tensor) -> torch.Tensor:
    return _soft_dilate(_soft_erode(img))


def soft_skeletonize(img: torch.Tensor, iterations: int = 10) -> torch.Tensor:
    """Iterative soft-morphology skeletonization (Shit et al., clDice 2021)."""
    img1 = _soft_open(img)
    skel = F.relu(img - img1)
    for _ in range(iterations):
        img = _soft_erode(img)
        img1 = _soft_open(img)
        delta = F.relu(img - img1)
        skel = skel + F.relu(delta - skel * delta)
    return skel


def cldice_loss(
    probs: torch.Tensor,
    target_onehot: torch.Tensor,
    classes: Sequence[int] = FOREGROUND_CLASSES,
    iterations: int = 10,
    smooth: float = 1.0,
) -> torch.Tensor:
    per_class = []
    for c in classes:
        p = probs[:, c : c + 1]
        t = target_onehot[:, c : c + 1]
        skel_p = soft_skeletonize(p, iterations)
        skel_t = soft_skeletonize(t, iterations)
        tprec = (torch.sum(skel_p * t) + smooth) / (torch.sum(skel_p) + smooth)
        tsens = (torch.sum(skel_t * p) + smooth) / (torch.sum(skel_t) + smooth)
        cl = 1.0 - 2.0 * (tprec * tsens) / (tprec + tsens + 1e-8)
        per_class.append(cl)
    return torch.stack(per_class).mean()


def _target_skeleton_distance_maps(skel_t: torch.Tensor, max_distance: float) -> torch.Tensor:
    """Euclidean distance transform to the nearest target-skeleton pixel.

    Built per-sample/class from the (thresholded) soft target skeleton via
    scipy on CPU -- non-differentiable by construction. Returned as a plain
    tensor so it can be used as a fixed weight against a differentiable
    prediction elsewhere (same trick as connectivity_regularizer).
    """
    skel_np = (skel_t.detach().cpu().numpy() > 0.5)
    out = np.empty(skel_np.shape, dtype=np.float32)
    for b in range(skel_np.shape[0]):
        for c in range(skel_np.shape[1]):
            if skel_np[b, c].any():
                out[b, c] = ndimage.distance_transform_edt(~skel_np[b, c])
            else:
                # no true line for this sample/class: any predicted mass is wrong
                out[b, c] = max_distance
    np.clip(out, 0, max_distance, out=out)
    return torch.from_numpy(out).to(skel_t.device)


def skeleton_distance_loss(
    probs: torch.Tensor,
    target_onehot: torch.Tensor,
    classes: Sequence[int] = FOREGROUND_CLASSES,
    iterations: int = 10,
    max_distance: float = 32.0,
) -> torch.Tensor:
    """Chamfer-style distance from predicted skeleton mass to the true line.

    Normalized to roughly [0, 1] (division by max_distance) so its weight is
    on a comparable scale to the Dice/clDice terms.
    """
    per_class = []
    for c in classes:
        p = probs[:, c : c + 1]
        t = target_onehot[:, c : c + 1]
        skel_p = soft_skeletonize(p, iterations)
        skel_t = soft_skeletonize(t, iterations)
        dist_map = _target_skeleton_distance_maps(skel_t, max_distance)
        weighted = (skel_p * dist_map).sum(dim=(1, 2, 3))
        norm = skel_p.sum(dim=(1, 2, 3)) + 1.0
        per_class.append((weighted / norm).mean() / max_distance)
    return torch.stack(per_class).mean()


def connectivity_regularizer(
    probs: torch.Tensor,
    classes: Sequence[int] = FOREGROUND_CLASSES,
    threshold: float = 0.5,
) -> torch.Tensor:
    """Penalize probability mass on non-largest connected components.

    Component labeling is non-differentiable and runs on CPU via scipy; the
    loss is the mean predicted probability at pixels flagged as fragments,
    so gradients still flow through the softmax probabilities even though
    the labeling itself doesn't participate in backprop.
    """
    device = probs.device
    probs_np = probs.detach().cpu().numpy()
    frag_terms = []
    for b in range(probs_np.shape[0]):
        for c in classes:
            binary = probs_np[b, c] > threshold
            if not binary.any():
                continue
            labeled, n = ndimage.label(binary)
            if n <= 1:
                continue
            sizes = ndimage.sum(binary, labeled, index=np.arange(1, n + 1))
            largest = int(np.argmax(sizes)) + 1
            fragment = binary & (labeled != largest)
            if not fragment.any():
                continue
            idx = torch.from_numpy(fragment).to(device)
            frag_terms.append(probs[b, c][idx].mean())
    if not frag_terms:
        return probs.new_zeros(())
    return torch.stack(frag_terms).mean()


class PalmLineLoss(nn.Module):
    """CE + Dice, with clDice, a skeleton distance term, and a connectivity
    regularizer phased in after warmup."""

    def __init__(
        self,
        num_classes: int = NUM_CLASSES,
        foreground_classes: Sequence[int] = FOREGROUND_CLASSES,
        cldice_weight: float = 0.5,
        distance_weight: float = 0.3,
        distance_warmup_epochs: int = 0,
        distance_max_px: float = 32.0,
        connectivity_weight: float = 0.1,
        connectivity_warmup_epochs: int = 5,
        skeleton_iterations: int = 10,
    ) -> None:
        super().__init__()
        self.num_classes = num_classes
        self.foreground_classes = foreground_classes
        self.cldice_weight = cldice_weight
        self.distance_weight = distance_weight
        self.distance_warmup_epochs = distance_warmup_epochs
        self.distance_max_px = distance_max_px
        self.connectivity_weight = connectivity_weight
        self.connectivity_warmup_epochs = connectivity_warmup_epochs
        self.skeleton_iterations = skeleton_iterations
        self.ce = nn.CrossEntropyLoss()
        self.epoch = 0

    def set_epoch(self, epoch: int) -> None:
        self.epoch = epoch

    def forward(self, logits: torch.Tensor, target: torch.Tensor) -> dict[str, torch.Tensor]:
        probs = torch.softmax(logits, dim=1)
        target_onehot = F.one_hot(target, self.num_classes).permute(0, 3, 1, 2).float()

        ce = self.ce(logits, target)
        dice = dice_loss(probs, target_onehot)
        cldice = cldice_loss(probs, target_onehot, self.foreground_classes, self.skeleton_iterations)

        total = ce + dice + self.cldice_weight * cldice

        dist = probs.new_zeros(())
        if self.distance_weight > 0 and self.epoch >= self.distance_warmup_epochs:
            dist = skeleton_distance_loss(
                probs, target_onehot, self.foreground_classes, self.skeleton_iterations, self.distance_max_px
            )
            total = total + self.distance_weight * dist

        conn = probs.new_zeros(())
        if self.connectivity_weight > 0 and self.epoch >= self.connectivity_warmup_epochs:
            conn = connectivity_regularizer(probs, self.foreground_classes)
            total = total + self.connectivity_weight * conn

        return {
            "total": total,
            "ce": ce.detach(),
            "dice": dice.detach(),
            "cldice": cldice.detach(),
            "distance": dist.detach(),
            "connectivity": conn.detach(),
        }
