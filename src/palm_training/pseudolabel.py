"""Turn binary crease masks (e.g. PLSU) into per-line canonical training labels.

The reviewed crease mask replaces the photo filter as tracer evidence, and an optional teacher
model only decides which crease belongs to which line. Each line label keeps only reviewed
crease pixels along the traced path, so class assignment can be wrong but pixels are never
invented. Lines the tracer cannot follow are written as unknown, not as absent.
"""
import io
import json
from pathlib import Path

import numpy as np
from PIL import Image

from palm_backend.line_tracer import ORDER, SIZE, Frame, canonicalize, trace_canonical

CHANNELS = ORDER + ('crease',)


def grow_along_crease(crease, seeds, count, reach):
    """Give each crease pixel the label of the geodesically nearest traced seed (within reach)."""
    from skimage.graph import MCP_Geometric

    region = crease | (seeds > 0)
    cost = np.where(region, 1.0, np.inf)
    out = np.zeros((count,) + crease.shape, np.uint8)
    distances = []
    for i in range(1, count + 1):
        start = np.argwhere(seeds == i)
        if not len(start):
            distances.append(np.full(crease.shape, np.inf))
            continue
        dist, _ = MCP_Geometric(cost).find_costs(start)
        distances.append(dist)
    distances = np.stack(distances)
    nearest = distances.argmin(0)
    reached = region & (distances.min(0) <= reach)
    for i in range(count):
        out[i] = reached & (nearest == i)
    return out


def canonical_label(photo, crease_mask, landmarks, teacher=None):
    import cv2

    rgb = np.asarray(photo.convert('RGB'))
    warped, cp, matrix, mirrored, oriented, points = canonicalize(rgb, landmarks)
    mask = np.asarray(crease_mask.convert('L')) > 127
    if mirrored:
        mask = mask[:, ::-1]
    crease = cv2.warpAffine(mask.astype(np.uint8) * 255, matrix, (SIZE, SIZE),
                            flags=cv2.INTER_LINEAR) > 64
    # Thin labels drawn at full resolution; blur gives the tracer a continuous ridge to follow.
    evidence = cv2.GaussianBlur(crease.astype(np.float32), (0, 0), 2.0)
    evidence = np.clip(evidence / max(float(evidence.max()), 1e-6) * 1.6, 0, 1)
    teacher_maps = teacher(oriented, points, matrix, warped) if teacher else None
    lines, _ = trace_canonical(warped, cp, teacher_maps, evidence, crease_weight=1.0)
    labels = np.zeros((len(CHANNELS), SIZE, SIZE), np.uint8)
    known = np.zeros(len(CHANNELS), bool)
    seeds = np.zeros((SIZE, SIZE), np.int32)
    near = cv2.dilate(crease.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    for i, name in enumerate(ORDER):
        line = lines[name]
        if not line.visible:
            continue
        band = np.zeros((SIZE, SIZE), np.uint8)
        cv2.polylines(band, [np.int32(np.round(line.canonical))], False, 1, 7)
        seeds[(band > 0) & near & (seeds == 0)] = i + 1
        known[i] = True
    labels[:len(ORDER)] = grow_along_crease(crease, seeds, len(ORDER), .35 * Frame(cp).W)
    labels[-1] = crease
    known[-1] = True
    return warped, labels, known, {n: lines[n].visible for n in ORDER}


def build_plsu(root, out, teacher=None, limit=None, shard=(0, 1)):
    """root: PLSU directory with img/*.jpg and Mask/*.png. Writes canonical samples to out.

    Resumable: samples already written are kept, so an interrupted run can be repeated.
    """
    from palm_backend.line_tracer import _hand_landmarks

    root, out = Path(root), Path(out)
    (out / 'samples').mkdir(parents=True, exist_ok=True)
    images = sorted((root / 'img').glob('*.jpg'))[:limit][shard[0]::shard[1]]
    for count, path in enumerate(images, 1):
        mask_path = root / 'Mask' / f'{path.stem}.png'
        meta = out / 'samples' / f'{path.stem}.json'
        if meta.exists() or not mask_path.exists():
            continue
        with Image.open(path) as photo, Image.open(mask_path) as crease:
            photo.load()
            crease.load()
            landmarks = _hand_landmarks(photo)
            if landmarks is None:
                meta.write_text(json.dumps({'id': path.stem, 'skipped': 'no hand'}))
                continue
            warped, labels, known, visible = canonical_label(photo, crease, landmarks, teacher)
        buffer = io.BytesIO()
        Image.fromarray(warped).save(buffer, format='JPEG', quality=95)
        (out / 'samples' / f'{path.stem}.jpg').write_bytes(buffer.getvalue())
        np.savez_compressed(out / 'samples' / f'{path.stem}.npz', labels=np.packbits(labels, axis=-1),
                            known=known)
        meta.write_text(json.dumps({'id': path.stem, 'visible': visible,
                                    'landmarks': np.asarray(landmarks).tolist()}))
        if count % 100 == 0:
            print(f'{count}/{len(images)} processed', flush=True)
    index = [json.loads(p.read_text()) for p in sorted((out / 'samples').glob('*.json'))]
    index = [entry for entry in index if 'visible' in entry]
    (out / 'index.json').write_text(json.dumps({'channels': CHANNELS, 'size': SIZE,
                                                'samples': index}, indent=1))
    return index
