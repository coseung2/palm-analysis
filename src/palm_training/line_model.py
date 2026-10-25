"""Per-line evidence models for the corridor tracer (offline experiments only).

- `OnnxThreeLineEvidence`: the MIT-licensed palm-line-reader student (heart/head/life, whole-hand
  fingers-up crop). Its probabilities are warped into the tracer's canonical palm frame.
- `CanonicalLineEvidence`: our own model trained on canonical palms (`palm_training.cli train-lines`).
Neither is activated by the server; `scripts/trace_lines.py --model` uses them for inspection.
"""
import hashlib
import math
from pathlib import Path

import numpy as np

IMAGENET_MEAN = np.float32([0.485, 0.456, 0.406])
IMAGENET_STD = np.float32([0.229, 0.224, 0.225])
LINE_NAMES = ('head', 'heart', 'life', 'fate', 'sun')


def _homogeneous(matrix):
    return np.vstack([matrix, [0, 0, 1]])


def fingers_up_crop(points, margin=.12):
    """Rotation+crop that puts the middle MCP above the wrist (palm-line-reader framing)."""
    import cv2

    v = points[9] - points[0]
    theta = math.degrees(math.atan2(v[0], -v[1]))
    centre = tuple(map(float, points.mean(0)))
    best = None
    for angle in (theta, -theta):
        m = cv2.getRotationMatrix2D(centre, angle, 1.0)
        rp = points @ m[:, :2].T + m[:, 2]
        if rp[9][1] < rp[0][1] and (best is None or abs(rp[9][0] - rp[0][0]) < best[0]):
            best = (abs(rp[9][0] - rp[0][0]), m)
    m = (best or (0, cv2.getRotationMatrix2D(centre, theta, 1.0)))[1].copy()
    rp = points @ m[:, :2].T + m[:, 2]
    pad = margin * float((rp.max(0) - rp.min(0)).max())
    x0, y0 = rp.min(0) - pad
    x1, y1 = rp.max(0) + pad
    m[0, 2] -= x0
    m[1, 2] -= y0
    return m, (int(math.ceil(x1 - x0)), int(math.ceil(y1 - y0)))


class OnnxThreeLineEvidence:
    CLASSES = {1: 'heart', 2: 'head', 3: 'life'}

    def __init__(self, path):
        import onnxruntime as ort

        self.session = ort.InferenceSession(str(path), providers=['CPUExecutionProvider'])
        self.digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()

    def __call__(self, oriented, points, matrix, warped):
        import cv2

        crop_m, size = fingers_up_crop(np.float64(points))
        crop = cv2.warpAffine(oriented, crop_m, size, flags=cv2.INTER_LINEAR,
                              borderMode=cv2.BORDER_REPLICATE)
        x = cv2.resize(crop, (512, 512), interpolation=cv2.INTER_LINEAR).astype(np.float32) / 255
        x = ((x - IMAGENET_MEAN) / IMAGENET_STD).transpose(2, 0, 1)[None]
        logits = self.session.run(None, {'input': x})[0][0].astype(np.float32)
        prob = np.exp(logits - logits.max(0))
        prob /= prob.sum(0)
        to_crop512 = np.diag([512 / size[0], 512 / size[1], 1]) @ _homogeneous(crop_m)
        to_canonical = _homogeneous(matrix) @ np.linalg.inv(to_crop512)
        size_out = warped.shape[1], warped.shape[0]
        return {name: cv2.warpAffine(prob[i], to_canonical[:2], size_out, flags=cv2.INTER_LINEAR)
                for i, name in self.CLASSES.items()}


class CanonicalLineEvidence:
    def __init__(self, path, device='cpu'):
        import torch

        from .line_net import build_line_net

        state = torch.load(path, map_location='cpu', weights_only=True)
        self.names = tuple(state['names'])
        self.size = int(state['size'])
        self.model = build_line_net(len(self.names), pretrained=False)
        self.model.load_state_dict(state['model'], strict=True)
        self.model.eval().to(device)
        self.device = device

    def __call__(self, oriented, points, matrix, warped):
        import cv2
        import torch

        x = cv2.resize(warped, (self.size, self.size), interpolation=cv2.INTER_AREA)
        x = ((x.astype(np.float32) / 255 - IMAGENET_MEAN) / IMAGENET_STD).transpose(2, 0, 1)
        with torch.inference_mode():
            prob = torch.sigmoid(self.model(torch.from_numpy(x)[None].to(self.device)))[0].cpu().numpy()
        size_out = warped.shape[1], warped.shape[0]
        return {name: cv2.resize(prob[i], size_out, interpolation=cv2.INTER_LINEAR)
                for i, name in enumerate(self.names)}


class Ensemble:
    def __init__(self, models):
        self.models = models

    def __call__(self, *args):
        maps = {}
        for model in self.models:
            for name, value in model(*args).items():
                maps.setdefault(name, []).append(value)
        return {name: np.mean(values, axis=0) for name, values in maps.items()}


def load_evidence_model(spec, device='cpu'):
    """`spec` is one path or several joined with '+'; .onnx -> teacher, .pt -> canonical model."""
    models = []
    for path in str(spec).split('+'):
        models.append(OnnxThreeLineEvidence(path) if path.endswith('.onnx')
                      else CanonicalLineEvidence(path, device))
    return models[0] if len(models) == 1 else Ensemble(models)
