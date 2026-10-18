import asyncio
import io

from PIL import Image, ImageDraw

from palm_backend.config import Settings
from palm_backend.images import PreparedImage
from palm_backend.line_mask import line_overlay, render_overlay
from palm_backend.providers import ClaudeAnalyzer


def test_overlay_suppresses_empty_dense_and_renders_candidates():
    image = Image.new('RGB', (256, 256), 'white')
    assert render_overlay(image, Image.new('L', image.size, 0)) is None
    assert render_overlay(image, Image.new('L', image.size, 255)) is None
    mask = Image.new('L', image.size, 0)
    ImageDraw.Draw(mask).line((20, 100, 230, 150), fill=255, width=2)
    overlay = render_overlay(image, mask)
    assert overlay.startswith(b'\x89PNG')
    with Image.open(io.BytesIO(overlay)) as decoded:
        assert decoded.size == (256, 256)
        assert not decoded.getexif()


def test_disabled_or_missing_checkpoint_does_not_reject_photo():
    assert line_overlay(b'not-a-photo', None) is None
    assert line_overlay(b'not-a-photo', 'missing-test-only.pth') is None


def test_observation_keeps_originals_and_labels_overlay_untrusted(monkeypatch):
    async def run():
        config = Settings(_env_file=None, operator_key='test-only-operator-key-at-least-32-characters', line_model_path='test-only.pth')
        photo = PreparedImage(data=b'overview', digest='a'*64, palm_detail=b'crop')
        calls = []
        class Probe(ClaudeAnalyzer):
            async def _generate(self, system, content, model):
                calls.append(content)
                return 'observed'
        monkeypatch.setattr('palm_backend.line_mask.line_overlay', lambda photo, path: b'overlay')
        assert await Probe(config, None).observe(photo) == 'observed'
        assert len([b for b in calls[0] if b['type'] == 'image']) == 3
        assert any('정답이 아닙니다' in b.get('text', '') for b in calls[0])
        monkeypatch.setattr('palm_backend.line_mask.line_overlay', lambda photo, path: None)
        await Probe(config, None).observe(photo)
        assert len([b for b in calls[1] if b['type'] == 'image']) == 2
        await Probe(config, None).observe(PreparedImage(data=b'overview', digest='a'*64))
        assert len([b for b in calls[2] if b['type'] == 'image']) == 1
    asyncio.run(run())
