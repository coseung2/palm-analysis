"""Inject development server secrets through stdin; never write plaintext values."""
import json
import os
import secrets
import shutil
import subprocess

from cloud_setup import ROOT
from provision_development import vault


def main():
    if os.environ.get('PALM_DEV_PROJECT_REF') != 'ihkbmxwidahgbrvxmrrk':
        raise RuntimeError('Unexpected development ref')
    settings = vault('PALM_DEV_SETTINGS_KEY')
    if not settings:
        settings = vault('PALM_DEV_SETTINGS_KEY', secrets.token_urlsafe(40))
    payload = {
        'SUPABASE_URL': os.environ['PALM_DEV_SUPABASE_URL'],
        'SUPABASE_SERVICE_KEY': os.environ['PALM_DEV_SERVICE_KEY'],
        'OPERATOR_KEY': settings,
    }
    executable = shutil.which('npx.cmd') or shutil.which('npx')
    subprocess.run([executable, '--yes', 'wrangler@4.149.0', 'secret', 'bulk', '--env', 'development'],
                   input=json.dumps(payload), text=True, cwd=ROOT, check=True)
    print('Only development DB/server settings secrets installed; OCX and management keys were not sent to Cloudflare.')


if __name__ == '__main__':
    try:
        main()
    except Exception:
        print('Development secret install stopped; credentials suppressed.')
        raise SystemExit(1) from None
