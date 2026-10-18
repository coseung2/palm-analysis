import asyncio
import base64
import io
import json

import httpx
import pytest
from PIL import Image, ImageDraw

from palm_backend.config import Settings
from palm_backend.images import prepare_image
from palm_backend.providers import DemoAnalyzer, OCXAnalyzer


@pytest.mark.parametrize('format,media_type', [('JPEG', 'image/jpeg'), ('PNG', 'image/png'), ('WEBP', 'image/webp')])
def test_normalized_photo_preserves_asymmetric_visual_content_through_ocx(format, media_type):
    image = Image.new('RGB', (800, 400), 'white')
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 399, 399), fill='red')
    draw.rectangle((400, 0, 799, 399), fill='blue')
    source = io.BytesIO()
    image.save(source, format=format)
    photo = prepare_image(source.getvalue(), media_type)

    async def run():
        observation = await DemoAnalyzer().observe(photo)
        def handler(request):
            payload = json.loads(request.content)
            data_url = payload['input'][0]['content'][0]['image_url']
            prefix, data = data_url.split(',', 1)
            assert prefix == 'data:image/jpeg;base64'
            assert base64.b64decode(data) == photo.data
            with Image.open(io.BytesIO(base64.b64decode(data))) as decoded:
                assert decoded.size == (800, 400)
                left, right = decoded.getpixel((200, 200)), decoded.getpixel((600, 200))
                assert left[0] > 200 and left[2] < 30
                assert right[2] > 200 and right[0] < 30
            return httpx.Response(200, json={'status': 'completed', 'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': observation.model_dump_json()}]}]})
        config = Settings(_env_file=None, operator_key='test-only-operator-key-at-least-32-characters', analysis_mode='ocx', ocx_base_url='https://ocx.test', ocx_api_key='test-only-key')
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            assert await OCXAnalyzer(config, client).observe(photo) == observation
    asyncio.run(run())


def test_exif_orientation_is_applied_before_metadata_is_removed():
    image = Image.new('RGB', (800, 400), 'white')
    ImageDraw.Draw(image).rectangle((0, 0, 399, 399), fill='red')
    exif = Image.Exif()
    exif[274] = 6
    source = io.BytesIO()
    image.save(source, 'JPEG', exif=exif)
    photo = prepare_image(source.getvalue(), 'image/jpeg')
    with Image.open(io.BytesIO(photo.data)) as decoded:
        assert decoded.size == (400, 800)
        assert not decoded.getexif()
        assert decoded.getpixel((200, 200))[0] > 200
        assert decoded.getpixel((200, 600))[1] > 200
