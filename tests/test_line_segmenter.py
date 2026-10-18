import asyncio
import io
import os
from types import SimpleNamespace

import pytest
from PIL import Image

from palm_backend import line_segmenter
from palm_backend.config import Settings
from palm_backend.images import PreparedImage
from palm_backend.line_segmenter import (
    LineCandidate,
    Segmentation,
    hand_view,
    segment_lines,
    zoomed_out,
)
from palm_backend.providers import ClaudeAnalyzer

np = pytest.importorskip('numpy')


def photo(size=(800, 600)):
    out = io.BytesIO()
    Image.new('RGB', size, (200, 170, 150)).save(out, format='JPEG')
    return out.getvalue()


class FakeSession:
    """Draws a strong heart band and a faint head band, regardless of input."""

    def __init__(self, heart=12.0):
        self.heart = heart
        self.calls = 0

    def get_inputs(self):
        return [SimpleNamespace(name='input')]

    def run(self, outputs, feeds):
        self.calls += 1
        assert feeds['input'].shape == (1, 3, 512, 512)
        logits = np.zeros((1, 4, 512, 512), dtype=np.float32)
        logits[0, 0] = 5
        logits[0, 1, 200:210, 100:400] = self.heart
        logits[0, 2, 300:303, 100:400] = 5.1  # wins argmax but with weak softmax mass
        return [logits]


def test_disabled_missing_or_unverified_model_is_absent(tmp_path):
    assert segment_lines(photo(), None, None) is None
    assert segment_lines(photo(), None, str(tmp_path / 'missing.onnx')) is None
    fake = tmp_path / 'fake.onnx'
    fake.write_bytes(b'not the published model')
    line_segmenter._session.cache_clear()
    assert segment_lines(photo(), None, str(fake)) is None


def test_hand_view_extends_toward_fingers_and_stays_square():
    left, top, right, bottom = hand_view((.25, .5, .75, .9), 1000, 1000)
    assert right - left == bottom - top
    assert top < 500 - 100 and bottom > 900  # room for fingers above the palm box
    assert left <= 250 and right >= 750


def test_zoomed_out_pads_beyond_photo():
    left, top, right, bottom = zoomed_out(800, 600)
    assert right - left == bottom - top == 1200
    assert left < 0 and top < 0 and right > 800 and bottom > 600


def test_segmentation_keeps_overview_frame_and_drops_weak_lines(monkeypatch):
    session = FakeSession()
    monkeypatch.setattr(line_segmenter, '_session', lambda path: session)
    result = segment_lines(photo((1600, 1200)), (.2, .3, .8, .95), 'test-only.onnx')
    assert result.lines == (LineCandidate('heart', 'strong'),)
    with Image.open(io.BytesIO(result.overlay)) as overlay:
        assert overlay.size == (1024, 768)  # same aspect as the first image the model sees
        assert overlay.format == 'PNG' and not overlay.getexif()
    assert session.calls == 3  # two views, then the best one mirrored


def test_nothing_found_tries_every_mirror_then_gives_up(monkeypatch):
    session = FakeSession(heart=0.0)
    monkeypatch.setattr(line_segmenter, '_session', lambda path: session)
    assert segment_lines(photo(), None, 'test-only.onnx') is None
    assert session.calls == 4


def test_runtime_failure_never_raises(monkeypatch):
    class Broken(FakeSession):
        def run(self, outputs, feeds):
            raise RuntimeError('test-only failure')
    monkeypatch.setattr(line_segmenter, '_session', lambda path: Broken())
    assert segment_lines(photo(), None, 'test-only.onnx') is None
    assert segment_lines(b'not-a-photo', None, 'test-only.onnx') is None


def test_observation_labels_segmentation_untrusted_and_fate_agnostic(monkeypatch):
    async def run():
        config = Settings(_env_file=None, operator_key='test-only-operator-key-at-least-32-characters',
                          line_segmenter_path='test-only.onnx')
        prepared = PreparedImage(data=b'overview', digest='a' * 64, palm_box=(.1, .2, .9, .95))
        calls, seen = [], []

        class Probe(ClaudeAnalyzer):
            async def _generate(self, system, content, model):
                calls.append(content)
                return 'observed'

        def fake(data, box, path):
            seen.append((data, box, path))
            return Segmentation(b'overlay', (LineCandidate('heart', 'strong'), LineCandidate('life', 'weak')))

        monkeypatch.setattr('palm_backend.line_segmenter.segment_lines', fake)
        assert await Probe(config, None).observe(prepared) == 'observed'
        assert seen == [(b'overview', (.1, .2, .9, .95), 'test-only.onnx')]
        assert len([b for b in calls[0] if b['type'] == 'image']) == 2
        text = next(b['text'] for b in calls[0] if '3종 주름' in b.get('text', ''))
        assert '감정선(뚜렷)' in text and '생명선(약함)' in text and '운명선' in text
        monkeypatch.setattr('palm_backend.line_segmenter.segment_lines', lambda *a: None)
        await Probe(config, None).observe(prepared)
        assert len([b for b in calls[1] if b['type'] == 'image']) == 1
    asyncio.run(run())


@pytest.mark.skipif(not os.environ.get('PALM_TEST_LINE_SEGMENTER'),
                    reason='set PALM_TEST_LINE_SEGMENTER to a provisioned model to run')
def test_published_model_runs_end_to_end():
    line_segmenter._session.cache_clear()
    result = segment_lines(photo(), None, os.environ['PALM_TEST_LINE_SEGMENTER'])
    # A flat synthetic photo has no creases; the point is that loading and inference succeed.
    assert result is None or result.overlay.startswith(b'\x89PNG')
