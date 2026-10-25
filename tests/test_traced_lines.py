import asyncio
import io

from PIL import Image

from palm_backend.config import Settings
from palm_backend.images import PreparedImage
from palm_backend.models import LineObservation, Observation
from palm_backend.providers import ClaudeAnalyzer
from palm_backend.traced_lines import (
    apply_traces,
    render_traces,
    resample,
    trace_lines,
    warm_up,
)


def observation():
    model_trace = [{'x': .1, 'y': .1}, {'x': .2, 'y': .2}]
    return Observation(hand='unknown', quality='usable', retake_reason='', lines=[
        LineObservation(name='life', visibility='visible', trait='t', description='d', trace=model_trace),
        LineObservation(name='head', visibility='visible', trait='t', description='d', trace=model_trace),
        LineObservation(name='heart', visibility='unclear', trait='t', description='d'),
        LineObservation(name='fate', visibility='not_visible', trait='t', description='d'),
    ])


def photo():
    stream = io.BytesIO()
    Image.new('RGB', (400, 300), 'white').save(stream, 'JPEG')
    return stream.getvalue()


def test_resample_keeps_both_ends_within_trace_limit():
    points = [(i / 99, i / 99) for i in range(100)]
    kept = resample(points)
    assert len(kept) == 24 and kept[0] == points[0] and kept[-1] == points[-1]
    assert resample(points[:5]) == points[:5]


def test_traced_coordinates_replace_model_drawing_and_decide_trusted_visibility():
    traced = {'life': [(.3, .4), (.5, .6)], 'heart': [(.2, .2), (.8, .2)], 'fate': [(.5, .9), (.5, .5)]}
    lines = {line.name: line for line in apply_traces(observation(), traced).lines}
    assert [(p.x, p.y) for p in lines['life'].trace] == [(.3, .4), (.5, .6)]
    assert lines['head'].visibility == 'visible' and lines['head'].trace == []  # untraced: draw nothing
    # Traced heart is drawn although the model judged it unclear.
    assert lines['heart'].visibility == 'visible'
    assert [(p.x, p.y) for p in lines['heart'].trace] == [(.2, .2), (.8, .2)]
    # Traced fate still needs the model's confirmation.
    assert lines['fate'].visibility == 'not_visible' and lines['fate'].trace == []
    assert apply_traces(observation(), None) == observation()


def test_unverified_checkpoint_or_bad_photo_falls_back(tmp_path):
    checkpoint = tmp_path / 'lines.pt'
    checkpoint.write_bytes(b'not the pinned checkpoint')
    assert trace_lines(photo(), str(checkpoint)) is None
    assert trace_lines(b'not-a-photo', str(checkpoint)) is None
    warm_up(str(tmp_path / 'missing.pt'))  # start-up warm-up never raises


def test_render_traces_draws_on_the_overview():
    with Image.open(io.BytesIO(render_traces(photo(), {'life': [(.1, .1), (.9, .9)]}))) as image:
        assert image.size == (400, 300)
        assert image.getpixel((200, 150)) != (255, 255, 255)


def test_observation_uses_tracer_and_falls_back_to_model_traces(monkeypatch):
    async def run():
        config = Settings(_env_file=None, operator_key='test-only-operator-key-at-least-32-characters',
                          line_model_path='test-only.pth', line_tracer_model_path='test-only.pt')
        image = PreparedImage(data=photo(), digest='a' * 64, palm_detail=b'crop')
        calls = []

        class Probe(ClaudeAnalyzer):
            async def _generate(self, system, content, model):
                calls.append(content)
                return observation()

        monkeypatch.setattr('palm_backend.line_mask.line_overlay', lambda photo, path: b'overlay')
        monkeypatch.setattr('palm_backend.traced_lines.trace_lines',
                            lambda photo, path: {'life': [(.3, .4), (.5, .6)]})
        result = await Probe(config, None).observe(image)
        assert [(p.x, p.y) for p in result.lines[0].trace] == [(.3, .4), (.5, .6)]
        assert result.lines[1].trace == []
        texts = [b.get('text', '') for b in calls[0]]
        assert any('추적된 선: life' in text and 'trace는 빈 배열' in text for text in texts)
        # Overview, crop and tracer drawing; the older crease overlay is not sent alongside.
        assert len([b for b in calls[0] if b['type'] == 'image']) == 3
        assert not any('실험적 주름 후보' in text for text in texts)

        monkeypatch.setattr('palm_backend.traced_lines.trace_lines', lambda photo, path: None)
        result = await Probe(config, None).observe(image)
        assert result == observation()
        assert any('실험적 주름 후보' in b.get('text', '') for b in calls[1])
    asyncio.run(run())
