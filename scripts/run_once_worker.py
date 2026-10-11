"""One explicit isolated integration-test cycle; no persisted readiness change."""
import asyncio
import os

from palm_backend.cloud_worker import run_once

if __name__ == '__main__':
    if os.environ.get('PALM_DEV_PROJECT_REF') != 'ihkbmxwidahgbrvxmrrk':
        raise SystemExit('Development mapping differs; no test run.')
    os.environ['PALM_RUNTIME_READY'] = 'true'
    try:
        asyncio.run(run_once())
        print('Isolated VM consumer cycle finished.')
    except Exception as error:
        print('Isolated VM cycle failed; error class:', type(error).__name__)
        if isinstance(error, RuntimeError) and str(error) in ('Runtime maintenance unavailable', 'Runtime database unavailable', 'Private photo unavailable'):
            print(str(error))
        raise SystemExit(1) from None
