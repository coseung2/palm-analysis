"""Optional local tracer as the source of drawn line positions.

The tracer (line_tracer + a hash-pinned lines-01 evidence model) places the polylines and decides
which of life/head/heart are visible; the language model confirms fate and writes descriptions. Any failure returns None so the
caller keeps its previous behaviour; a missing crease is never filled with a template.
"""
import hashlib
import io
from functools import lru_cache
from pathlib import Path
from threading import Lock

from PIL import Image, ImageDraw

from .models import LINE_NAMES, Observation

CHECKPOINT_SHA256 = 'c19e0056210198964cb22fdb6305d5d677703f719a3acd56a51dea6bbc4d98ce'
MAX_POINTS = 24
COLORS = {'life': (230, 40, 40), 'head': (30, 110, 255), 'heart': (0, 170, 90), 'fate': (170, 60, 220)}
# Lines whose traced visibility stands on its own. On 103 PLSU validation photos lines-01 drew
# life/head/heart where no crease was labelled 4/0/0 times but fate 34 times, so a traced fate
# line is still drawn only when the language model confirms it.
TRUSTED = ('life', 'head', 'heart')
_LOCK = Lock()


@lru_cache(maxsize=1)
def _evidence(path):
    from palm_training.line_model import CanonicalLineEvidence

    checkpoint = Path(path)
    if hashlib.sha256(checkpoint.read_bytes()).hexdigest() != CHECKPOINT_SHA256:
        raise ValueError('Unverified palm-line tracer checkpoint')
    return CanonicalLineEvidence(checkpoint)


def resample(points, limit=MAX_POINTS):
    """Evenly spaced subset that keeps both ends, within the observation trace limit."""
    if len(points) <= limit:
        return list(points)
    step = (len(points) - 1) / (limit - 1)
    return [points[round(i * step)] for i in range(limit)]


def trace_lines(photo: bytes, model_path: str) -> dict | None:
    """{line: [(x, y)] normalized to `photo`} for traced lines; None when tracing failed."""
    try:
        from .line_tracer import trace_palm

        with _LOCK:
            model = _evidence(model_path)
            with Image.open(io.BytesIO(photo)) as source:
                traced = trace_palm(source.convert('RGB'), evidence_model=model, minor=False)
    except Exception:
        return None  # Optional dependencies, the detector or the model must not fail a session.
    if traced is None:
        return None
    return {name: resample(line.points) for name, line in traced.lines.items()
            if name in LINE_NAMES and line.visible and len(line.points) >= 2}


def warm_up(model_path: str) -> None:
    """Pay imports, model load and detector start-up (~15 s cold) before the first booth photo."""
    blank = io.BytesIO()
    Image.new('RGB', (256, 256), 'white').save(blank, format='JPEG')
    trace_lines(blank.getvalue(), model_path)


def render_traces(photo: bytes, lines: dict) -> bytes:
    with Image.open(io.BytesIO(photo)) as source:
        image = source.convert('RGB')
    image.thumbnail((1024, 1024))
    draw = ImageDraw.Draw(image)
    width = max(3, round(max(image.size) / 250))
    for name, points in lines.items():
        xy = [(x * (image.width - 1), y * (image.height - 1)) for x, y in points]
        draw.line(xy, fill=COLORS[name], width=width, joint='curve')
        x, y = xy[0]
        draw.text((x + width, y + width), name, fill=COLORS[name], stroke_width=2, stroke_fill='white')
    output = io.BytesIO()
    image.save(output, format='PNG')
    return output.getvalue()


def apply_traces(observation: Observation, lines: dict | None) -> Observation:
    """Replace model-drawn coordinates with traced ones; visible-but-untraced lines draw nothing.

    A traced TRUSTED line is visible whatever the model judged; fate needs both to agree.
    """
    if lines is None:
        return observation
    data = observation.model_dump()
    for line in data['lines']:
        traced = lines.get(line['name'], [])
        if traced and line['name'] in TRUSTED:
            line['visibility'] = 'visible'
        line['trace'] = [{'x': x, 'y': y} for x, y in traced] if line['visibility'] == 'visible' else []
    return Observation.model_validate(data)
