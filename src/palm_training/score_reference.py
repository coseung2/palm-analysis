"""Score the tracer on photos against hand-drawn reference lines in the canonical palm frame.

Reference JSON (keep it with the photos, outside Git):

    {"photo.jpg": {"landmarks": [[x, y], ... 21 points],
                   "lines": {"heart": {"state": "visible", "points": [[x, y], ...]},
                             "fate": {"state": "unclear", "points": []},
                             "sun": {"state": "not_visible", "points": []}}}}

Points are canonical 512px coordinates produced by `canonicalize` with the stored landmarks,
so a reference stays valid when the landmark detector changes. `unclear` lines are skipped;
`not_visible` lines count as correct only when nothing is drawn. Visible lines are scored by
centre-line F1 within `--tolerance` canonical pixels; a missed visible line scores 0.

    python -m palm_training.score_reference --photos DIR --reference ref.json [--model lines.pt]
"""
import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image

from palm_backend.line_tracer import SIZE, canonicalize, trace_canonical


def centreline_f1(reference, predicted, tolerance):
    import cv2

    def raster(points):
        drawn = np.zeros((SIZE, SIZE), np.uint8)
        cv2.polylines(drawn, [np.int32(np.round(points))], False, 1, 1)
        return drawn > 0

    a, b = raster(reference), raster(predicted)
    to_a = cv2.distanceTransform((~a).astype(np.uint8), cv2.DIST_L2, 5)
    to_b = cv2.distanceTransform((~b).astype(np.uint8), cv2.DIST_L2, 5)
    precision, recall = float((to_a[b] <= tolerance).mean()), float((to_b[a] <= tolerance).mean())
    return 2 * precision * recall / max(precision + recall, 1e-9)


def score(photos, reference, model=None, tolerance=8):
    rows, values = {}, []
    for photo, entry in reference.items():
        with Image.open(Path(photos) / photo) as source:
            rgb = np.asarray(source.convert('RGB'))
        warped, cp, matrix, _, oriented, points = canonicalize(rgb, np.float32(entry['landmarks']))
        evidence = model(oriented, points, matrix, warped) if model else None
        crease = evidence.pop('crease', None) if evidence else None
        predicted, _ = trace_canonical(warped, cp, evidence, crease)
        rows[photo] = {}
        for name, ref in entry['lines'].items():
            got = predicted[name]
            if ref['state'] == 'unclear':
                rows[photo][name] = None
                continue
            if ref['state'] == 'not_visible':
                value = 0.0 if got.visible else 1.0
            elif not got.visible:
                value = 0.0
            else:
                value = centreline_f1(ref['points'], got.canonical, tolerance)
            rows[photo][name] = round(value, 3)
            values.append(value)
    return {'tolerance_px': tolerance, 'photos': rows,
            'mean': round(float(np.mean(values)), 3) if values else None}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--photos', required=True)
    parser.add_argument('--reference', required=True)
    parser.add_argument('--model')
    parser.add_argument('--tolerance', type=float, default=8)
    args = parser.parse_args(argv)
    model = None
    if args.model:
        from .line_model import load_evidence_model
        model = load_evidence_model(args.model)
    reference = json.loads(Path(args.reference).read_text(encoding='utf-8'))
    print(json.dumps(score(args.photos, reference, model, args.tolerance), ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
