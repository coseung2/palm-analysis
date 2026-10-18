import asyncio
import base64
import io
import json
from types import SimpleNamespace

import httpx
from PIL import Image

from palm_backend.config import Settings
from palm_backend.images import prepare_image
from palm_backend.palm_roi import palm_box
from palm_backend.providers import DemoAnalyzer, OCXAnalyzer


def landmarks(x=.5, y=.5, size=.2):
    points = [SimpleNamespace(x=x, y=y) for _ in range(21)]
    for i, dx, dy in [(0, 0, size), (1, -size/2, size/2), (2, -size, 0), (5, -size/2, -size), (9, 0, -size), (13, size/2, -size), (17, size, -size/2)]:
        points[i] = SimpleNamespace(x=x+dx, y=y+dy)
    return points


def test_palm_box_has_padding_and_clamps_to_image():
    box = palm_box([landmarks()], 1000, 800)
    assert box is not None
    assert box[0] < 300 and box[2] > 700
    assert 0 <= box[1] < box[3] <= 800
    edge = palm_box([landmarks(.15, .2, .15)], 1000, 800)
    assert edge[0] == 0


def test_ambiguous_hands_and_invalid_landmarks_do_not_choose_random_crop():
    assert palm_box([], 1000, 800) is None
    assert palm_box([landmarks(.25), landmarks(.75)], 1000, 800) is None
    assert palm_box([landmarks(size=.001)], 1000, 800) is None
    assert palm_box([landmarks(x=float('nan'))], 1000, 800) is None


def test_original_resolution_roi_and_no_upscale(monkeypatch):
    monkeypatch.setattr('palm_backend.images.locate_palm', lambda image: (400, 300, 1600, 1500))
    source = io.BytesIO()
    Image.new('RGB', (3200, 2400), 'white').save(source, 'JPEG')
    photo = prepare_image(source.getvalue(), 'image/jpeg')
    with Image.open(io.BytesIO(photo.data)) as full:
        assert full.size == (2048, 1536)
        assert not full.getexif()
    with Image.open(io.BytesIO(photo.palm_detail)) as crop:
        assert crop.size == (1200, 1200)
        assert not crop.getexif()


def test_detector_error_is_not_a_photo_rejection(monkeypatch):
    def fail(image):
        raise RuntimeError('test detector unavailable')
    monkeypatch.setattr('palm_backend.images.locate_palm', fail)
    source = io.BytesIO()
    Image.new('RGB', (800, 600), 'white').save(source, 'PNG')
    assert prepare_image(source.getvalue(), 'image/png').palm_detail is None


def test_ocx_sends_overview_and_crop_in_one_observation_with_explicit_options(monkeypatch):
    monkeypatch.setattr('palm_backend.images.locate_palm', lambda image: (100, 100, 700, 500))
    source = io.BytesIO()
    Image.new('RGB', (800, 600), 'white').save(source, 'PNG')
    photo = prepare_image(source.getvalue(), 'image/png')
    async def run():
        observation = await DemoAnalyzer().observe(photo)
        calls = []
        def handler(request):
            body = json.loads(request.content)
            calls.append(body)
            images = [b for b in body['input'][0]['content'] if b['type'] == 'input_image']
            assert len(images) == (3 if photo.enhanced_detail else 2)
            if photo.enhanced_detail:
                assert images[2]['image_url'].startswith('data:image/png;base64,')
                assert base64.b64decode(images[2]['image_url'].split(',')[1]) == photo.enhanced_detail
                text = ' '.join(b['text'] for b in body['input'][0]['content'] if b['type'] == 'input_text')
                assert '보정 전 사진과 대조' in text
                assert '첫 전체 사진 기준' in text
            assert all(b['detail'] == 'high' for b in images)
            assert base64.b64decode(images[0]['image_url'].split(',')[1]) == photo.data
            assert base64.b64decode(images[1]['image_url'].split(',')[1]) == photo.palm_detail
            assert body['reasoning'] == {'effort': 'high'}
            assert body['max_output_tokens'] == 6000
            assert body['store'] is False
            return httpx.Response(200, json={'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':observation.model_dump_json()}]}]})
        config = Settings(_env_file=None, operator_key='test-only-operator-key-at-least-32-characters', analysis_mode='ocx', ocx_base_url='https://ocx.test', ocx_api_key='test-only-key')
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await OCXAnalyzer(config, client).observe(photo)
        assert len(calls) == 1
    asyncio.run(run())
