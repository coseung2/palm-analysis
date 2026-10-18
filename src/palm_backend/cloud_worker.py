"""VM consumer for the service-only development DB and private temporary photos."""
import asyncio
import os
import time
import uuid
from urllib.parse import urlparse

import httpx

from .config import Settings
from .images import prepare_image
from .models import BoothConfig
from .providers import OCXAnalyzer
from .runtime_logging import configure, event
from .timing import analysis_timing, configure_timing, stage
from .worker import Job, consume


class RuntimeRPC:
    def __init__(self, url: str, key: str, client: httpx.AsyncClient):
        parsed = urlparse(url)
        if parsed.scheme != 'https' or parsed.netloc != 'ihkbmxwidahgbrvxmrrk.supabase.co' or parsed.path not in ('', '/'):
            raise ValueError('Development Supabase origin not verified')
        self.url = url.rstrip('/')
        self.headers = {'apikey': key, 'Authorization': 'Bearer ' + key}
        self.client = client

    async def rpc(self, op, args=None):
        response = await self.client.post(
            self.url + '/rest/v1/rpc/palm_worker', headers=self.headers,
            json={'p_op': op, 'p_args': args or {}},
        )
        if response.status_code != 200:
            raise RuntimeError('Runtime database unavailable')
        return response.json()

    async def dispatch(self, job, stage):
        return await self.rpc('dispatch', {'job': job.id, 'lease': job.lease, 'stage': stage}) is True

    async def finish(self, job, result, error, *, reason=None):
        args = {'job': job.id, 'lease': job.lease}
        if result is not None:
            args['result'] = result.model_dump()
        if error is not None:
            args['error'] = error
        if error == 'retake_required' and reason:
            cleaned = ''.join(char for char in reason if char.isprintable()).strip()
            if cleaned:
                args['retake_reason'] = ('AI의 재촬영 판정 사유: ' + cleaned)[:300]
        accepted = await self.rpc('finish', args) is True
        if accepted:
            event('job_finished', outcome='completed' if result is not None else 'failed')
        else:
            event('late_result_dropped')
        return accepted

    async def read(self, key):
        with stage('photo_fetch'):
            content, media_type = await self._download_photo(key)
        return prepare_image(content, media_type)

    async def _download_photo(self, key):
        if key != str(uuid.UUID(key[:-4])) + '.jpg':
            raise ValueError('Invalid private photo key')
        async with self.client.stream('GET', self.url + '/storage/v1/object/palm-uploads/' + key, headers=self.headers) as response:
            if response.status_code != 200:
                raise RuntimeError('Private photo unavailable')
            content = bytearray()
            async for block in response.aiter_bytes():
                content.extend(block)
                if len(content) > 5 * 1024 * 1024:
                    raise ValueError('Photo too large')
            media_type = response.headers.get('content-type', '').split(';')[0]
        return bytes(content), media_type

    async def clean_one(self):
        lease = str(uuid.uuid4())
        deletion = await self.rpc('claim_deletion', {'lease': lease})
        if not deletion:
            return
        key = deletion['photo_key']
        if key != str(uuid.UUID(key[:-4])) + '.jpg':
            raise ValueError('Invalid deletion key')
        response = await self.client.request('DELETE', self.url + '/storage/v1/object/palm-uploads', headers=self.headers, json={'prefixes': [key]})
        # Supabase object delete returns 200 on success; 404 is also safely absent.
        await self.rpc('finish_deletion', {'photo_key': key, 'lease': lease, 'success': response.status_code in (200, 404)})


async def run_once():
    if os.environ.get('PALM_RUNTIME_READY') != 'true':
        return
    settings = Settings(
        _env_file=None, operator_key='unused-worker-key-at-least-32-characters',
        analysis_mode='ocx', ocx_base_url=os.environ['PALM_OCX_BASE_URL'],
        ocx_api_key=os.environ['PALM_OCX_API_KEY'], ocx_model=os.environ['PALM_OCX_MODEL'],
    )
    settings.validate_runtime()
    async with httpx.AsyncClient(timeout=120, follow_redirects=False) as client:
        repository = RuntimeRPC(os.environ['PALM_DEV_SUPABASE_URL'], os.environ['PALM_DEV_SERVICE_KEY'], client)
        response = await client.post(repository.url + '/rest/v1/rpc/palm_maintenance', headers=repository.headers, json={})
        if response.status_code not in (200, 204):
            raise RuntimeError('Runtime maintenance unavailable')
        for booth in await repository.rpc('booths'):
            await repository.rpc('recover', {'booth': booth})
            lease = str(uuid.uuid4())
            row = await repository.rpc('claim', {'booth': booth, 'lease': lease})
            if row:
                started = time.monotonic()
                try:
                    with analysis_timing(enqueued_at=row.get('created_at')):
                        async with asyncio.timeout(150):
                            await consume(Job(row['id'], lease, row['photo_key'], BoothConfig.model_validate(row['config'])), repository, repository, OCXAnalyzer(settings, client))
                finally:
                    event('job_cycle_duration', duration_ms=int((time.monotonic() - started) * 1000))
        await repository.clean_one()


async def main():
    configure()
    configure_timing()
    while True:
        try:
            await run_once()
        except Exception:
            event('consumer_cycle_failed')
        await asyncio.sleep(2)


if __name__ == '__main__':
    asyncio.run(main())
