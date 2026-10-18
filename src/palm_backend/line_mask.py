"""Optional experimental overlay. It never decides acceptance or labels a palm line."""
import hashlib
import io
from functools import lru_cache
from pathlib import Path
from threading import Lock

from PIL import Image

CHECKPOINT_SHA256 = '8493d6dc2fa772cd919ddbb9a907d4dd194b8f480f2adeca14ca844140092daf'
_LOCK = Lock()


@lru_cache(maxsize=1)
def _load(path):
    import torch

    from .line_network import LineUNet

    checkpoint = Path(path)
    if checkpoint.stat().st_size != 55490203 or hashlib.sha256(checkpoint.read_bytes()).hexdigest() != CHECKPOINT_SHA256:
        raise ValueError('Unverified palm-line checkpoint')
    model = LineUNet()
    model.load_state_dict(torch.load(checkpoint, map_location='cpu', weights_only=True), strict=True)
    model.eval()
    return model


def render_overlay(image, mask):
    # Empty, almost empty or widespread predictions are not reliable visual evidence.
    histogram = mask.histogram()
    coverage = 1 - histogram[0] / (mask.width * mask.height)
    if not .001 <= coverage <= .2:
        return None
    image = image.convert('RGB').resize((256, 256), Image.Resampling.NEAREST)
    tint = Image.new('RGB', image.size, (255, 80, 30))
    marked = Image.blend(image, tint, .6)
    overlay = Image.composite(marked, image, mask)
    output = io.BytesIO()
    overlay.save(output, format='PNG')
    return output.getvalue()


def line_overlay(photo: bytes, model_path: str | None):
    if not model_path:
        return None
    try:
        import numpy as np
        import torch

        with _LOCK, torch.inference_mode():
            model = _load(model_path)
            with Image.open(io.BytesIO(photo)) as source:
                image = source.convert('RGB').resize((256, 256), Image.Resampling.NEAREST)
            array = np.asarray(image).copy().astype('float32') / 255
            tensor = torch.from_numpy(array).permute(2, 0, 1).unsqueeze(0)
            logits = model(tensor)
            if logits.shape != (1, 1, 256, 256) or not torch.isfinite(logits).all():
                return None
            # Upstream cutoff is a RAW LOGIT, not a calibrated probability.
            mask = Image.fromarray((logits[0, 0].numpy() > .03).astype('uint8') * 255)
            return render_overlay(image, mask)
    except (ImportError, OSError, ValueError, RuntimeError, KeyError):
        return None
