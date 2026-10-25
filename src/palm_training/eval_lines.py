"""Compare tracer evidence configurations on the held-out pseudo-label split.

Ground truth here is reviewed crease pixels with machine-assigned line classes, and PLSU photos
of one person may fall on both sides of the split, so the scores are a relative comparison of
configurations, not a validated accuracy. The tracer sees only the photo.

    python -m palm_training.eval_lines --data data/training/plsu_lines \
        --config filter= --config teacher=MODEL.onnx --output report.json
"""
import argparse
import json
from pathlib import Path

import numpy as np

from palm_backend.line_tracer import ORDER, SIZE, canonicalize, trace_canonical

from .train_lines import _split

TOLERANCE = 6  # canonical pixels (~2% of palm width)


def _centerline_scores(points, label):
    import cv2
    from skimage.morphology import skeletonize

    truth = skeletonize(label > 0)
    drawn = np.zeros((SIZE, SIZE), np.uint8)
    if len(points) > 1:
        cv2.polylines(drawn, [np.int32(np.round(points))], False, 1, 1)
    pred = drawn > 0
    if not truth.any() or not pred.any():
        return None
    to_truth = cv2.distanceTransform((~truth).astype(np.uint8), cv2.DIST_L2, 5)
    to_pred = cv2.distanceTransform((~pred).astype(np.uint8), cv2.DIST_L2, 5)
    precision = float((to_truth[pred] <= TOLERANCE).mean())
    recall = float((to_pred[truth] <= TOLERANCE).mean())
    return precision, recall


def evaluate(data, photos, configs, limit=None):
    """photos: the original image directory the labels were built from (PLSU/img)."""
    from PIL import Image

    from palm_backend.line_tracer import _hand_landmarks

    from .line_model import load_evidence_model

    root, photos = Path(data), Path(photos)
    index = json.loads((root / 'index.json').read_text())
    ids = [s['id'] for s in index['samples'] if _split(s['id']) == 'val'][:limit]
    cache = root / 'landmarks.json'
    landmarks = json.loads(cache.read_text()) if cache.exists() else {}
    models = {name: (load_evidence_model(spec) if spec else None) for name, spec in configs}
    rows = {name: {line: {'p': [], 'r': [], 'missed': 0, 'extra': 0, 'known': 0} for line in ORDER}
            for name in models}
    used = 0
    for sample in ids:
        with Image.open(photos / f'{sample}.jpg') as source:
            photo = source.convert('RGB')
        if sample not in landmarks:
            found = _hand_landmarks(photo)
            landmarks[sample] = found.tolist() if found is not None else None
        if landmarks[sample] is None:
            continue
        # Same photo + same landmarks reproduce the exact canonical frame of the labels.
        canon, cp, matrix, _, oriented, points = canonicalize(np.asarray(photo), np.float32(landmarks[sample]))
        packed = np.load(root / 'samples' / f'{sample}.npz')
        labels = np.unpackbits(packed['labels'], axis=-1)[..., :SIZE]
        known = packed['known']
        used += 1
        for name, model in models.items():
            evidence = model(oriented, points, matrix, canon) if model else None
            crease = evidence.pop('crease', None) if evidence else None
            lines, _ = trace_canonical(canon, cp, evidence, crease)
            for i, line_name in enumerate(ORDER):
                line = lines[line_name]
                stats = rows[name][line_name]
                if known[i]:
                    stats['known'] += 1
                    scores = _centerline_scores(line.canonical, labels[i]) if line.visible else None
                    if scores is None:
                        stats['missed'] += 1
                    else:
                        stats['p'].append(scores[0])
                        stats['r'].append(scores[1])
                elif line.visible:
                    stats['extra'] += 1
    cache.write_text(json.dumps(landmarks))
    report = {}
    for name, per_line in rows.items():
        report[name] = {}
        for line_name, s in per_line.items():
            p = float(np.mean(s['p'])) if s['p'] else 0.0
            r = float(np.sum(s['r'])) / max(s['known'], 1)  # missed lines count as 0 recall
            report[name][line_name] = {'precision': round(p, 3), 'recall': round(r, 3),
                                       'f1': round(2 * p * r / max(p + r, 1e-9), 3),
                                       'known': s['known'], 'missed': s['missed'],
                                       'visible_without_label': s['extra']}
    return {'samples': used, 'tolerance_px': TOLERANCE, 'configs': dict(configs), 'scores': report}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--data', required=True)
    parser.add_argument('--photos', required=True, help='original photo directory (PLSU/img)')
    parser.add_argument('--config', action='append', required=True, help='NAME=MODEL[+MODEL] or NAME=')
    parser.add_argument('--output', required=True)
    parser.add_argument('--limit', type=int)
    args = parser.parse_args(argv)
    configs = [tuple(item.split('=', 1)) for item in args.config]
    report = evaluate(args.data, args.photos, configs, args.limit)
    Path(args.output).write_text(json.dumps(report, indent=1))
    for name, per_line in report['scores'].items():
        print(name, {k: v['f1'] for k, v in per_line.items()})


if __name__ == '__main__':
    main()
