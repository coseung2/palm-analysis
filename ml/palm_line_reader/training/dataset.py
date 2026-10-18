"""Dataset for RGB palm-line student training — see ../plan.md, Phase 2.

Expects the directory generate_pseudo_labels.py produces:
    data_dir/images/<stem>.png     RGB crop, already resized to img_size
    data_dir/masks/<stem>.png      single-channel class-index mask (0..3, or
                                    0..4 when the fate line is labelled)
    data_dir/manifest.csv          stem, pass_filter, ... (rows with
                                    pass_filter != True are skipped, unless
                                    overridden by reviewed.csv below)
    data_dir/reviewed.csv          optional, written by ../label_tool.py:
                                    stem, status (edited/approved/rejected).
                                    "edited"/"approved" include a stem even
                                    if the heuristic filter rejected it;
                                    "rejected" excludes it even if the
                                    heuristic filter passed it -- a human
                                    verdict always overrides the heuristic.

Augmentation is heavy on photometric transforms (webcam white balance varies
wildly) and a horizontal flip since geometry, not left/right hand identity, is
what defines each line class. Normalization matches the mit_b0 encoder's
imagenet pretraining stats.

Geometric jitter is wide on purpose (build_train_transform(strong=True)). The
shipped model only saw scale 0.85-1.0 / +-10 degree jitter and fell apart on
phone photos framed differently from MediaPipe crops: a palm-only close-up
returned almost nothing until it was padded back out to whole-hand framing.
So training now mixes in zoomed-out (padded) hands, palm-only close-ups,
larger rotation, and the blur/noise/JPEG/exposure artefacts of booth cameras.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import List, Optional, Tuple

import albumentations as A
import cv2
import numpy as np
from albumentations.pytorch import ToTensorV2
from torch.utils.data import Dataset

IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD = (0.229, 0.224, 0.225)


def _load_manifest_allowlist(manifest_path: Path) -> Optional[set]:
    if not manifest_path.exists():
        return None
    allowed = set()
    with open(manifest_path, newline="") as f:
        for row in csv.DictReader(f):
            if row.get("pass_filter", "True").strip().lower() in ("true", "1"):
                allowed.add(row["stem"])
    return allowed


def _load_reviewed_status(data_dir: Path) -> dict:
    path = data_dir / "reviewed.csv"
    if not path.exists():
        return {}
    status = {}
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            status[row["stem"]] = row["status"]
    return status


def _usable_stems(data_dir: Path) -> List[str]:
    allowlist = _load_manifest_allowlist(data_dir / "manifest.csv")
    reviewed = _load_reviewed_status(data_dir)
    all_stems = sorted(p.stem for p in (data_dir / "images").glob("*.png"))

    stems = []
    for s in all_stems:
        verdict = reviewed.get(s)
        if verdict == "rejected":
            continue
        if verdict in ("edited", "approved") or allowlist is None or s in allowlist:
            stems.append(s)

    if not stems:
        raise RuntimeError(
            f"no usable samples in {data_dir} (found {len(all_stems)} images, "
            f"{len(allowlist) if allowlist is not None else 'no'} pass manifest filter, "
            f"{len(reviewed)} reviewed)"
        )
    return stems


def split_stems(data_dir: str, val_fraction: float = 0.1, seed: int = 0) -> Tuple[List[str], List[str]]:
    stems = _usable_stems(Path(data_dir))
    rng = np.random.default_rng(seed)
    stems = list(stems)
    rng.shuffle(stems)
    n_val = max(1, int(len(stems) * val_fraction)) if len(stems) > 1 else 0
    return stems[n_val:], stems[:n_val]


def build_train_transform(img_size: int = 512, strong: bool = True) -> A.Compose:
    if not strong:  # the original exp2 recipe, kept for ablations
        geometric = [
            A.HorizontalFlip(p=0.5),
            A.Rotate(limit=10, border_mode=cv2.BORDER_CONSTANT, value=0, mask_value=0, p=0.7),
            A.RandomResizedCrop(height=img_size, width=img_size, scale=(0.85, 1.0), ratio=(0.95, 1.05), p=0.5),
        ]
        degradations = []
    else:
        pad = dict(mode=cv2.BORDER_CONSTANT, cval=0, cval_mask=0)
        geometric = [
            A.HorizontalFlip(p=0.5),
            A.OneOf(
                [
                    # zoomed-out: hand small in frame, background padding around it
                    A.Affine(scale=(0.55, 0.9), translate_percent=(-0.1, 0.1), rotate=(-25, 25), **pad),
                    # roughly the training framing, wider rotation than before
                    A.Affine(scale=(0.9, 1.15), translate_percent=(-0.05, 0.05), rotate=(-25, 25), **pad),
                    # palm-only close-up: fingers and wrist cropped away
                    A.RandomResizedCrop(size=(img_size, img_size), scale=(0.3, 0.6), ratio=(0.8, 1.25)),
                ],
                p=0.85,
            ),
        ]
        degradations = [
            A.OneOf([A.MotionBlur(blur_limit=7), A.GaussianBlur(blur_limit=(3, 7)), A.Defocus(radius=(1, 3))], p=0.3),
            A.GaussNoise(var_limit=(5.0, 40.0), p=0.25),
            A.ImageCompression(quality_range=(35, 95), p=0.3),
            # Soft exposure changes only: RandomShadow's hard-edged polygons look like creases.
            A.OneOf([A.RandomGamma(gamma_limit=(70, 140)), A.RandomBrightnessContrast(0.25, 0.25)], p=0.3),
            A.CLAHE(clip_limit=2.0, p=0.1),
        ]
    return A.Compose(
        [
            *geometric,
            A.ColorJitter(brightness=0.3, contrast=0.3, saturation=0.3, hue=0.05, p=0.8),
            A.RGBShift(r_shift_limit=15, g_shift_limit=15, b_shift_limit=15, p=0.5),
            *degradations,
            A.Resize(img_size, img_size),
            A.Normalize(mean=IMAGENET_MEAN, std=IMAGENET_STD),
            ToTensorV2(),
        ]
    )


def build_val_transform(img_size: int = 512) -> A.Compose:
    return A.Compose(
        [
            A.Resize(img_size, img_size),
            A.Normalize(mean=IMAGENET_MEAN, std=IMAGENET_STD),
            ToTensorV2(),
        ]
    )


class PalmLineDataset(Dataset):
    def __init__(self, data_dir: str, transform: A.Compose, stems: Optional[List[str]] = None):
        self.data_dir = Path(data_dir)
        self.images_dir = self.data_dir / "images"
        self.masks_dir = self.data_dir / "masks"
        self.transform = transform
        self.stems = stems if stems is not None else _usable_stems(self.data_dir)

    def __len__(self) -> int:
        return len(self.stems)

    def __getitem__(self, idx: int):
        stem = self.stems[idx]
        image = cv2.cvtColor(cv2.imread(str(self.images_dir / f"{stem}.png")), cv2.COLOR_BGR2RGB)
        mask = cv2.imread(str(self.masks_dir / f"{stem}.png"), cv2.IMREAD_GRAYSCALE)
        out = self.transform(image=image, mask=mask)
        return out["image"], out["mask"].long()
