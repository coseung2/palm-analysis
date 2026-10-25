import numpy as np
import pytest

pytest.importorskip('cv2')
pytest.importorskip('skimage')
pytest.importorskip('scipy')

from palm_training.pseudolabel import grow_along_crease  # noqa: E402


def test_traced_seed_claims_its_whole_crease_but_not_a_separate_one():
    crease = np.zeros((64, 64), bool)
    crease[10, 5:60] = True      # one long crease, only partly traced
    crease[40, 5:60] = True      # an unrelated crease nobody traced
    seeds = np.zeros((64, 64), np.int32)
    seeds[10, 25:35] = 1
    grown = grow_along_crease(crease, seeds, 2, reach=40)
    assert grown[0][10, 5:60].all()
    assert not grown[0][40].any()
    assert not grown[1].any()


def test_touching_lines_split_at_the_junction_and_respect_reach():
    crease = np.zeros((64, 64), bool)
    crease[30, 0:64] = True
    seeds = np.zeros((64, 64), np.int32)
    seeds[30, 2:6] = 1
    seeds[30, 58:62] = 2
    grown = grow_along_crease(crease, seeds, 2, reach=20)
    assert grown[0][30, 10] and grown[1][30, 54]
    assert not (grown[0] & grown[1]).any()
    assert not grown[:, 30, 32].any()  # farther than `reach` from both seeds
