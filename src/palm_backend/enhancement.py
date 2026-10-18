"""Auxiliary ridge evidence, never a replacement for the original photograph."""
import io

from PIL import Image


RIDGE_SIGMAS = (3, 5, 7)
RIDGE_MAX_EDGE = 1024


def enhance_palm(image: Image.Image) -> bytes | None:
    try:
        import cv2
        import numpy as np
        from skimage.filters import meijering
    except ImportError:
        return None
    view = image.convert('RGB').copy()
    view.thumbnail((RIDGE_MAX_EDGE, RIDGE_MAX_EDGE), Image.Resampling.LANCZOS)
    gray = cv2.cvtColor(np.asarray(view), cv2.COLOR_RGB2GRAY).astype(np.float32) / 255
    response = meijering(gray, sigmas=RIDGE_SIGMAS, black_ridges=True)
    if not np.isfinite(response).all():
        return None
    # Match experiment 9: scale display using the central palm comparison area.
    # This region is not an automatic palm mask; no pixels are removed or traced.
    height, width = response.shape
    interior = response[round(height * 120 / 1024):round(height * 850 / 1024),
                        round(width * 170 / 1024):round(width * 830 / 1024)]
    ceiling = float(np.percentile(interior if interior.size else response, 99.5))
    display = np.clip(response / max(ceiling, 1e-8), 0, 1)
    result = Image.fromarray(np.uint8(255 * (1 - display)))
    out = io.BytesIO()
    result.save(out, format='PNG')
    return out.getvalue()
