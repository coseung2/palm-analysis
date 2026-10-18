"""Optional local palm localization; never a photo acceptance or crease classifier."""
import math

from PIL import Image

PALM_POINTS = (0, 1, 2, 5, 9, 13, 17)


def palm_box(hands, width, height):
    boxes = []
    for landmarks in hands:
        points = [(landmarks[i].x * width, landmarks[i].y * height) for i in PALM_POINTS]
        if not all(math.isfinite(v) for point in points for v in point):
            continue
        xs, ys = zip(*points, strict=True)
        left, top, right, bottom = min(xs), min(ys), max(xs), max(ys)
        span = max(right - left, bottom - top)
        if span < 64:
            continue
        # Preserve thumb base and major creases; do not rotate or enhance line contrast.
        margin = span * .3
        box = (max(0, int(left - margin)), max(0, int(top - margin)),
               min(width, math.ceil(right + margin)), min(height, math.ceil(bottom + margin)))
        if box[2] > box[0] and box[3] > box[1]:
            boxes.append(box)
    boxes.sort(key=lambda b: (b[2] - b[0]) * (b[3] - b[1]), reverse=True)
    if not boxes:
        return None
    def area(box):
        return (box[2] - box[0]) * (box[3] - box[1])
    if len(boxes) > 1 and area(boxes[0]) < 1.6 * area(boxes[1]):
        return None
    if area(boxes[0]) >= .85 * width * height:
        return None
    return boxes[0]


def locate_palm(image: Image.Image):
    try:
        import mediapipe as mp
        import numpy as np
    except ImportError:
        return None
    preview = image.copy()
    preview.thumbnail((1024, 1024))
    # Per-call lifecycle avoids sharing a non-thread-safe graph and retaining photo frames.
    with mp.solutions.hands.Hands(static_image_mode=True, max_num_hands=2,
                                  model_complexity=1, min_detection_confidence=.5) as detector:
        result = detector.process(np.asarray(preview))
    return palm_box(result.multi_hand_landmarks and [h.landmark for h in result.multi_hand_landmarks] or [],
                    image.width, image.height)
