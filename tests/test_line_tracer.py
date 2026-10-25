import numpy as np
import pytest

pytest.importorskip('cv2')
pytest.importorskip('skimage')
pytest.importorskip('scipy')

import cv2  # noqa: E402

from palm_backend.line_tracer import (  # noqa: E402
    CANON,
    SIZE,
    Frame,
    _local_dp,
    canonicalize,
    trace_canonical,
    trace_minor,
)


def canonical_points():
    cp = np.zeros((21, 2), np.float32)
    for index, (x, y) in CANON.items():
        cp[index] = (x * SIZE, y * SIZE)
    cp[1] = (.70 * SIZE, .80 * SIZE)  # thumb CMC
    cp[2] = (.86 * SIZE, .62 * SIZE)  # thumb MCP
    return cp


def synthetic_palm(curves):
    """Skin-toned palm on a grey background with dark creases along (u, v) curves."""
    cp = canonical_points()
    frame = Frame(cp)
    image = np.full((SIZE, SIZE, 3), (90, 95, 100), np.uint8)
    palm = np.int32([frame.xy(-.12, -.05), frame.xy(1.05, -.07), cp[2], cp[1],
                     frame.xy(.85, 1.05), frame.xy(.08, 1.05), frame.xy(-.16, .55)])
    cv2.fillPoly(image, [cv2.convexHull(palm)], (214, 168, 150))
    for curve in curves:
        points = np.int32([frame.xy(u, v) for u, v in curve])
        cv2.polylines(image, [points], False, (150, 100, 90), 4, cv2.LINE_AA)
    rng = np.random.default_rng(0)
    noisy = image.astype(np.int16) + rng.integers(-4, 5, image.shape)
    return np.clip(noisy, 0, 255).astype(np.uint8), cp


HEART = [(-.08, .10), (.25, .08), (.55, .03), (.72, -.04)]
HEAD = [(1.0, .19), (.70, .24), (.40, .30), (.12, .36)]
LIFE = [(.98, .26), (.82, .40), (.70, .58), (.64, .80), (.64, .98)]


def nearest_v(frame, points, u):
    uv = np.linalg.solve(np.stack([frame.U, frame.V], 1), (np.float32(points) - frame.o).T).T
    return uv[np.argmin(np.abs(uv[:, 0] - u)), 1]


def test_local_dp_follows_a_continuous_ridge_and_ignores_noise():
    strip = np.zeros((21, 120), np.float32)
    strip[8, 10:100] = 1
    strip[3, 50:55] = .9
    track = _local_dp(strip, .3, np.zeros(21))
    assert set(track[:, 0]) == {8}
    assert track[0, 1] == 10 and track[-1, 1] == 99


def test_traces_three_major_lines_into_their_own_names():
    image, cp = synthetic_palm([HEART, HEAD, LIFE])
    lines, _ = trace_canonical(image, cp)
    frame = Frame(cp)
    assert lines['heart'].visible and lines['head'].visible and lines['life'].visible
    assert abs(nearest_v(frame, lines['heart'].canonical, .3) - .075) < .05
    assert abs(nearest_v(frame, lines['head'].canonical, .5) - .28) < .05
    assert not lines['fate'].visible
    assert not lines['sun'].visible


def test_blank_palm_reports_no_visible_lines():
    image, cp = synthetic_palm([])
    lines, _ = trace_canonical(image, cp)
    assert not any(line.visible for line in lines.values())


def test_left_and_right_hands_share_the_canonical_frame():
    rng = np.random.default_rng(1)
    photo = rng.integers(0, 255, (400, 300, 3), dtype=np.uint8)
    right = np.float32([[150, 380]] + [[0, 0]] * 4 + [[220, 150]] + [[0, 0]] * 3 + [[160, 140]]
                       + [[0, 0]] * 3 + [[110, 145]] + [[0, 0]] * 3 + [[70, 160]] + [[0, 0]] * 3)
    left = right.copy()
    left[:, 0] = 299 - left[:, 0]
    _, cp_right, _, mirrored_right, _, _ = canonicalize(photo, right)
    _, cp_left, _, mirrored_left, _, _ = canonicalize(photo[:, ::-1], left)
    assert mirrored_right != mirrored_left
    assert np.allclose(cp_right[[0, 5, 9, 13, 17]], cp_left[[0, 5, 9, 13, 17]], atol=1)
    assert cp_right[5][0] > cp_right[17][0]  # index finger on the right, thumb side


def test_heart_never_rides_the_head_crease():
    image, cp = synthetic_palm([HEAD, LIFE])
    lines, _ = trace_canonical(image, cp)
    assert lines['head'].visible
    assert not lines['heart'].visible


def test_obstacle_creases_on_the_thumb_mount_are_found_separately():
    obstacles = [[(.80, .55), (.98, .52)], [(.78, .70), (.97, .66)]]
    image, cp = synthetic_palm([HEART, HEAD, LIFE] + obstacles)
    lines, _ = trace_canonical(image, cp)
    minor = trace_minor(image, cp, lines)
    assert len(minor['obstacle']) == 2
    assert minor['marriage'] == []


def test_blank_palm_has_no_minor_lines():
    image, cp = synthetic_palm([])
    lines, _ = trace_canonical(image, cp)
    assert trace_minor(image, cp, lines) == {'obstacle': [], 'marriage': []}
