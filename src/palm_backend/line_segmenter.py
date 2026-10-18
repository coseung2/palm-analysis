"""Optional heart/head/life crease candidates. Auxiliary evidence only.

Never decides acceptance, never labels the fate line, never replaces the photograph.
Model: samuelwbarber/palm-line-reader student (MIT); see third_party/palm_line_reader/NOTICE.md.
"""
import hashlib
import io
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from threading import Lock

from PIL import Image

# Only the published student files are accepted; anything else is treated as absent.
MODEL_SHA256 = {
    'e2c9f826676b3aaf0a715f3087fcd4fc0b4dccd8c53de05fd26696a8399f8dd6',  # student_fp16.onnx
    '3c02b88b82e54889d0ab2bf2ba108aec554a1b50759f7c7aaa45f2f114ed24ff',  # student_fp32.onnx
}
INPUT_SIZE = 512
MEAN = (0.485, 0.456, 0.406)
STD = (0.229, 0.224, 0.225)
LINES = {1: 'heart', 2: 'head', 3: 'life'}
COLORS = {1: (255, 40, 40), 2: (40, 110, 255), 3: (30, 210, 60)}
# A candidate needs enough pixels and mean softmax mass to be shown at all. These are
# display gates on an uncalibrated model, not accuracy guarantees.
MIN_PIXELS = 120
MIN_CONFIDENCE = .55
STRONG_CONFIDENCE = .75
OVERLAY_MAX_EDGE = 1024
ZOOM_OUT = 1.5
PAD_COLOR = (30, 30, 30)
_LOCK = Lock()


@dataclass(frozen=True)
class LineCandidate:
    name: str
    strength: str  # 'strong' | 'weak'


@dataclass(frozen=True)
class Segmentation:
    overlay: bytes
    lines: tuple[LineCandidate, ...]


@lru_cache(maxsize=1)
def _session(path):
    import onnxruntime as ort

    model = Path(path).read_bytes()
    if hashlib.sha256(model).hexdigest() not in MODEL_SHA256:
        raise ValueError('Unverified palm-line segmenter')
    options = ort.SessionOptions()
    options.intra_op_num_threads = 2
    return ort.InferenceSession(model, options, providers=['CPUExecutionProvider'])


def hand_view(palm_box, width, height):
    """Square, hand-shaped window around a palm box, extended toward the fingers.

    The model was trained on whole-hand crops (fingers up, small margin). The ROI box
    covers the palm only, so feeding it directly loses the context the model expects;
    extending it upward and padding beyond the photo also zooms out close-up shots.
    """
    left, top, right, bottom = (palm_box[0] * width, palm_box[1] * height,
                                palm_box[2] * width, palm_box[3] * height)
    w, h = right - left, bottom - top
    left, right = left - .1 * w, right + .1 * w
    top, bottom = top - .5 * h, bottom + .05 * h
    side = max(right - left, bottom - top)
    cx, cy = (left + right) / 2, (top + bottom) / 2
    return (round(cx - side / 2), round(cy - side / 2), round(cx + side / 2), round(cy + side / 2))


def zoomed_out(width, height):
    """Whole photo shrunk inside a padded square: a close-up palm (no fingers, so no ROI)
    then resembles the whole-hand framing the model was trained on."""
    side = round(max(width, height) * ZOOM_OUT)
    left, top = (width - side) // 2, (height - side) // 2
    return (left, top, left + side, top + side)


def _views(image, palm_box):
    views = [(0, 0, image.width, image.height)]
    if palm_box:
        views.append(hand_view(palm_box, image.width, image.height))
    else:
        views.append(zoomed_out(image.width, image.height))
    return views


def _crop(image, box):
    # Pads outside the photo instead of clamping so the window keeps its aspect and scale.
    canvas = Image.new('RGB', (box[2] - box[0], box[3] - box[1]), PAD_COLOR)
    canvas.paste(image, (-box[0], -box[1]))
    return canvas


def _infer(session, image, mirror):
    import numpy as np

    view = image.resize((INPUT_SIZE, INPUT_SIZE), Image.Resampling.BILINEAR)
    if mirror:
        view = view.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    array = (np.asarray(view, dtype=np.float32) / 255 - MEAN) / STD
    tensor = array.transpose(2, 0, 1)[None].astype(np.float32)
    logits = session.run(None, {session.get_inputs()[0].name: tensor})[0][0]
    if logits.shape != (4, INPUT_SIZE, INPUT_SIZE) or not np.isfinite(logits).all():
        return None
    probs = np.exp(logits - logits.max(axis=0))
    probs /= probs.sum(axis=0)
    if mirror:
        probs = probs[:, :, ::-1]
    return probs


def _score(probs):
    """Per-line mean probability over pixels the model assigns to that line."""
    labels = probs.argmax(axis=0)
    scores = {}
    for index in LINES:
        region = labels == index
        if region.sum() >= MIN_PIXELS:
            scores[index] = float(probs[index][region].mean())
    return labels, scores


def _render(image, box, labels, keep):
    import numpy as np

    color = np.zeros((*labels.shape, 3), dtype=np.uint8)
    alpha = np.zeros(labels.shape, dtype=np.uint8)
    for index in keep:
        color[labels == index] = COLORS[index]
        alpha[labels == index] = 220
    size = (box[2] - box[0], box[3] - box[1])
    color_full = Image.new('RGB', image.size)
    alpha_full = Image.new('L', image.size, 0)
    color_full.paste(Image.fromarray(color).resize(size, Image.Resampling.NEAREST), box[:2])
    alpha_full.paste(Image.fromarray(alpha).resize(size, Image.Resampling.NEAREST), box[:2])
    overlay = Image.composite(color_full, image, alpha_full)
    output = io.BytesIO()
    overlay.save(output, format='PNG')
    return output.getvalue()


def _candidate(session, image, box, mirror):
    probs = _infer(session, _crop(image, box), mirror)
    if probs is None:
        return None
    labels, scores = _score(probs)
    kept = {i: v for i, v in scores.items() if v >= MIN_CONFIDENCE}
    if not kept:
        return None
    return ((len(kept), sum(kept.values())), box, labels, kept)


def _better(current, candidate):
    if candidate is None or (current is not None and candidate[0] <= current[0]):
        return current
    return candidate


def segment_lines(photo: bytes, palm_box, model_path: str | None) -> Segmentation | None:
    """Best of (whole photo, hand window or zoomed-out photo) x (as-is, mirrored), drawn
    on the overview frame.

    One view is chosen for all lines so a crease is never painted as two different lines.
    Mirroring covers the unknown hand side: the model was trained on one canonical side.
    """
    if not model_path:
        return None
    try:
        with _LOCK:
            session = _session(model_path)
            with Image.open(io.BytesIO(photo)) as source:
                image = source.convert('RGB')
            image.thumbnail((OVERLAY_MAX_EDGE, OVERLAY_MAX_EDGE))
            best = None
            # Each view once, then only the best view mirrored: 3 CPU passes instead of 4.
            # Mirror every view only when nothing was found as-is.
            views = _views(image, palm_box)
            for box in views:
                best = _better(best, _candidate(session, image, box, False))
            for box in [best[1]] if best else views:
                best = _better(best, _candidate(session, image, box, True))
        if best is None:
            return None
        _, box, labels, kept = best
        lines = tuple(
            LineCandidate(LINES[i], 'strong' if kept[i] >= STRONG_CONFIDENCE else 'weak')
            for i in sorted(kept)
        )
        return Segmentation(_render(image, box, labels, kept), lines)
    except Exception:
        return None  # Auxiliary evidence must never fail or reject the analysis.
