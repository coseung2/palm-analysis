"""Read-only runtime connectivity probe; no photo or AI call."""
import asyncio
import os

import httpx

from palm_backend.cloud_worker import RuntimeRPC


async def main():
    async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
        repository = RuntimeRPC(os.environ['PALM_DEV_SUPABASE_URL'], os.environ['PALM_DEV_SERVICE_KEY'], client)
        booths = await repository.rpc('booths')
        print('VM development RPC connected; enabled booth count:', len(booths))


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except Exception:
        print('VM runtime probe failed; credentials suppressed.')
        raise SystemExit(1) from None
