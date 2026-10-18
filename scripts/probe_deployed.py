"""Deployed gateway/VM integration probe with a generated non-personal blank photo."""
import asyncio
import io
import time
import uuid

import httpx
from PIL import Image

URL = 'https://palm-analysis-development.mdownloader.workers.dev'


async def main():
    photo = io.BytesIO()
    Image.new('RGB', (320, 320), 'white').save(photo, 'PNG')
    started = time.monotonic()
    current = None
    async with httpx.AsyncClient(timeout=45, follow_redirects=False) as client:
        health = await client.get(URL + '/health')
        if health.status_code != 200 or health.json().get('analysis_mode') != 'ocx':
            raise RuntimeError('Deployment not ready')
        try:
            response = await client.post(URL + '/v1/sessions', json={'external_processing_consent': True})
            if response.status_code != 201:
                raise RuntimeError('Public start failed')
            current = response.json()
            headers = {'Authorization': 'Bearer ' + current['access_token'], 'Content-Type': 'image/png', 'Idempotency-Key': str(uuid.uuid4())}
            endpoint = URL + '/v1/sessions/' + current['id']
            upload = await client.post(endpoint + '/analysis', headers=headers, content=photo.getvalue())
            if upload.status_code != 202:
                print('Upload HTTP status:', upload.status_code)
                if upload.headers.get('content-type', '').startswith('application/json'):
                    print('Upload error code:', upload.json().get('error', {}).get('code'))
                raise RuntimeError('Deployed upload failed')
            deadline = time.monotonic() + 150
            while time.monotonic() < deadline:
                view = await client.get(endpoint, headers={'Authorization': headers['Authorization']})
                if view.status_code != 200:
                    raise RuntimeError('Deployed status query failed')
                result = view.json()
                if result['status'] != 'analyzing':
                    if result['status'] != 'failed' or result.get('error', {}).get('code') != 'retake_required':
                        print('Synthetic outcome status:', result['status'], 'error code:', (result.get('error') or {}).get('code'))
                        raise RuntimeError('Expected blank-photo retake')
                    message = result.get('error', {}).get('message', '')
                    if not message.startswith('AI의 재촬영 판정 사유: ') or len(message) > 300:
                        raise RuntimeError('Specific bounded retake feedback was not delivered')
                    denied = await client.get(endpoint, headers={'Authorization': 'Bearer ' + '0' * 64})
                    if denied.status_code != 404:
                        raise RuntimeError('Invalid session token was not denied')
                    print('Deployed HTTPS gateway, VM consumer, OCX retake reason and session isolation verified; elapsed seconds:', round(time.monotonic() - started, 1))
                    break
                await asyncio.sleep(2)
            else:
                raise RuntimeError('Deployed analysis wait timed out')
        finally:
            if current:
                cancelled = await client.delete(URL + '/v1/sessions/' + current['id'], headers={'Authorization': 'Bearer ' + current['access_token']})
                if cancelled.status_code != 200 or cancelled.json()['status'] != 'cancelled':
                    raise RuntimeError('Synthetic session cancellation not confirmed')
                print('Synthetic deployed test cancelled; no real photo used.')


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except Exception as error:
        print('Deployed test stopped; error class:', type(error).__name__)
        if isinstance(error, RuntimeError):
            print(str(error))
        raise SystemExit(1) from None
