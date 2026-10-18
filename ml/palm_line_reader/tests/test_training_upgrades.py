import sys
from pathlib import Path

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "training"))

from audit_labels import audit_mask, straightness  # noqa: E402


def mask_with(curves, size=512):
    mask = np.zeros((size, size), np.uint8)
    for cls, pts in curves.items():
        cv2.polylines(mask, [np.array(pts, np.int32)], False, cls, 9)
    return mask


HEART = [(330, 150), (250, 190), (140, 230)]
HEAD = [(120, 240), (250, 290), (360, 330)]
LIFE = [(140, 250), (170, 360), (260, 460)]


def test_straightness_separates_arc_from_segment():
    arc = mask_with({3: LIFE}) == 3
    line = mask_with({3: [(260, 300), (264, 420)]}) == 3
    from skimage.morphology import skeletonize

    assert straightness(skeletonize(arc)) > 0.1
    assert straightness(skeletonize(line)) < 0.03


def test_audit_accepts_plausible_mask():
    score, flags, lengths = audit_mask(mask_with({1: HEART, 2: HEAD, 3: LIFE}))
    assert not [f for f in flags if f.startswith("life_") or f.startswith("missing_")]
    assert lengths[3] > 100


def test_audit_flags_centre_vertical_life_line_first():
    # The exp2 failure: the vertical fate-position crease painted as "life".
    score, flags, _ = audit_mask(mask_with({1: HEART, 2: HEAD, 3: [(262, 300), (264, 380)]}))
    assert {"life_short", "life_straight", "life_far_from_head"} <= set(flags)
    assert score >= 6


def test_audit_flags_missing_lines_but_not_optional_fate():
    _, flags, _ = audit_mask(mask_with({1: HEART, 2: HEAD}))
    assert "missing_life" in flags and "missing_fate" not in flags


def test_class_weights_change_only_weighted_lines():
    torch = pytest.importorskip("torch")
    from losses import PalmLineLoss, line_classes

    assert line_classes(3) == (4, (1, 2, 3)) and line_classes(4) == (5, (1, 2, 3, 4))
    with pytest.raises(ValueError):
        PalmLineLoss(class_weights=[1, 1, 1])
    torch.manual_seed(0)
    logits = torch.randn(2, 4, 32, 32)
    target = torch.zeros(2, 32, 32, dtype=torch.long)
    target[:, 10:12, :] = 1
    target[:, 20:22, :] = 3
    plain = PalmLineLoss(connectivity_weight=0, distance_weight=0)(logits, target)
    life = PalmLineLoss(connectivity_weight=0, distance_weight=0, class_weights=[1, 1, 1, 3])(logits, target)
    assert torch.isfinite(life["total"]) and not torch.isclose(plain["total"], life["total"])
    same = PalmLineLoss(connectivity_weight=0, distance_weight=0, class_weights=[1, 1, 1, 1])(logits, target)
    assert torch.allclose(plain["dice"], same["dice"]) and torch.allclose(plain["cldice"], same["cldice"])


def test_strong_augmentation_keeps_size_and_label_values():
    pytest.importorskip("albumentations")
    pytest.importorskip("torch")
    from dataset import build_train_transform

    image = np.full((512, 512, 3), 180, np.uint8)
    mask = mask_with({1: HEART, 2: HEAD, 3: LIFE, 4: [(280, 470), (270, 300)]})
    transform = build_train_transform(512, strong=True)
    seen = set()
    for _ in range(40):
        out = transform(image=image, mask=mask)
        assert tuple(out["image"].shape) == (3, 512, 512)
        seen |= set(np.unique(out["mask"].numpy()).tolist())
    assert seen <= {0, 1, 2, 3, 4}
