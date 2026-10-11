import asyncio
import io
import json

import httpx
import pytest
from PIL import Image

from palm_backend.cloud_worker import RuntimeRPC

BASE = 'https://ihkbmxwidahgbrvxmrrk.supabase.co'
KEY = 'test-only-server-key'
PHOTO = '33333333-3333-4333-8333-333333333333.jpg'


def test_cloud_worker_rpc_uses_only_explicit_development_target():
    async def run():
        def handler(request):
            assert str(request.url) == BASE + '/rest/v1/rpc/palm_worker'
            assert request.headers['apikey'] == KEY
            assert json.loads(request.content)['p_op'] == 'booths'
            return httpx.Response(200, json=[])
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            repo = RuntimeRPC(BASE, KEY, client)
            assert await repo.rpc('booths') == []
            for target in ['https://pyugqoogcoynvywihgym.supabase.co', 'http://ihkbmxwidahgbrvxmrrk.supabase.co', BASE + '/unexpected']:
                with pytest.raises(ValueError):
                    RuntimeRPC(target, KEY, client)
    asyncio.run(run())


def test_private_photo_read_revalidates_decode_and_strips_metadata():
    stream = io.BytesIO()
    image = Image.new('RGB', (320, 320), 'white')
    exif = Image.Exif()
    exif[270] = 'private-test-metadata'
    image.save(stream, 'JPEG', exif=exif)
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(
            200, content=stream.getvalue(), headers={'content-type': 'image/jpeg'},
        ))) as client:
            repo = RuntimeRPC(BASE, KEY, client)
            result = await repo.read(PHOTO)
            assert b'private-test-metadata' not in result.data
            with pytest.raises(ValueError):
                await repo.read('../other-bucket')
    asyncio.run(run())


def test_private_photo_deletion_uses_bucket_prefix_request_and_records_failure():
    async def run():
        requests = []
        def handler(request):
            if request.method == 'DELETE':
                assert str(request.url) == BASE + '/storage/v1/object/palm-uploads'
                assert json.loads(request.content) == {'prefixes': [PHOTO]}
                return httpx.Response(503)
            body = json.loads(request.content)
            requests.append(body)
            if body['p_op'] == 'claim_deletion':
                return httpx.Response(200, json={'photo_key': PHOTO})
            return httpx.Response(200, json=True)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            await RuntimeRPC(BASE, KEY, client).clean_one()
        assert requests[-1]['p_op'] == 'finish_deletion'
        assert requests[-1]['p_args']['success'] is False
    asyncio.run(run())
