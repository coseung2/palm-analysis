import io
import sys

import pytest
from PIL import Image, ImageDraw

from palm_backend.enhancement import enhance_palm
from palm_backend.images import prepare_image


def photo_bytes(image):
    out = io.BytesIO()
    image.save(out, 'PNG')
    return out.getvalue()


def test_ridge_view_preserves_geometry_and_detects_dark_crease():
    pytest.importorskip('skimage')
    image = Image.new('RGB', (400, 300), (180, 160, 140))
    ImageDraw.Draw(image).line((80, 30, 80, 270), fill=(80, 60, 40), width=8)
    with Image.open(io.BytesIO(enhance_palm(image))) as enhanced:
        assert enhanced.format == 'PNG'
        assert enhanced.size == image.size
        assert not enhanced.getexif()
        assert enhanced.getpixel((80, 100)) < enhanced.getpixel((300, 100))


def test_ridge_limits_resolution_without_changing_aspect():
    pytest.importorskip('skimage')
    with Image.open(io.BytesIO(enhance_palm(Image.new('RGB', (2400, 1200))))) as result:
        assert result.size == (1024, 512)


def test_ridge_uses_medium_scales_without_threshold_or_skeleton(monkeypatch):
    filters = pytest.importorskip('skimage.filters')
    import numpy as np
    def response(image, *, sigmas, black_ridges):
        assert sigmas == (3, 5, 7)
        assert black_ridges is True
        return np.tile(np.linspace(0, 1, image.shape[1]), (image.shape[0], 1))
    monkeypatch.setattr(filters, 'meijering', response)
    with Image.open(io.BytesIO(enhance_palm(Image.new('RGB', (300, 300))))) as result:
        assert len(set(result.getdata())) > 100
        assert result.getpixel((20, 100)) > result.getpixel((280, 100))


def test_ridge_preserves_original_and_always_uses_overview(monkeypatch):
    pytest.importorskip('skimage')
    monkeypatch.setattr('palm_backend.images.locate_palm', lambda image: (30, 40, 330, 240))
    data = photo_bytes(Image.new('RGB', (600, 400), (65, 55, 45)))
    photo = prepare_image(data, 'image/png')
    with Image.open(io.BytesIO(photo.enhanced_detail)) as enhanced:
        assert enhanced.size == (600, 400)
    monkeypatch.setattr('palm_backend.images.enhance_palm', lambda image: None)
    original_only = prepare_image(data, 'image/png')
    assert photo.data == original_only.data
    assert photo.digest == original_only.digest
    assert photo.palm_detail == original_only.palm_detail


def test_no_roi_still_produces_ridge_view(monkeypatch):
    pytest.importorskip('skimage')
    monkeypatch.setattr('palm_backend.images.locate_palm', lambda image: None)
    photo = prepare_image(photo_bytes(Image.new('RGB', (600, 400))), 'image/png')
    assert photo.palm_detail is None
    assert photo.enhanced_detail


def test_missing_optional_dependency_skips_enhancement(monkeypatch):
    monkeypatch.setitem(sys.modules, 'skimage.filters', None)
    assert enhance_palm(Image.new('RGB', (300, 300))) is None


def test_enhancement_failure_does_not_reject_original(monkeypatch):
    monkeypatch.setattr('palm_backend.images.locate_palm', lambda image: None)
    def fail(image):
        raise RuntimeError('enhancement unavailable')
    monkeypatch.setattr('palm_backend.images.enhance_palm', fail)
    photo = prepare_image(photo_bytes(Image.new('RGB', (300, 300))), 'image/png')
    assert photo.data
    assert photo.enhanced_detail is None
