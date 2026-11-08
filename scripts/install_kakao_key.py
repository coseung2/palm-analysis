"""Copy PALM_KAKAO_JS_KEY from Infisical dev `/` to the development Worker through stdin; prints no value."""
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from cloud_setup import ROOT  # noqa: E402
from provision_development import vault  # noqa: E402

NAME = 'PALM_KAKAO_JS_KEY'


def main():
    key = vault(NAME)
    if not key or not re.fullmatch(r'[0-9a-f]{32}', key):
        raise RuntimeError('Kakao key missing in Infisical')
    executable = shutil.which('npx.cmd') or shutil.which('npx')
    subprocess.run([executable, '--yes', 'wrangler@4.149.0', 'secret', 'put', NAME, '--env', 'development'],
                   input=key, text=True, cwd=ROOT, check=True, stdout=subprocess.DEVNULL)
    print(f'{NAME} installed on the development Worker.')


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(f'Kakao key install stopped ({type(error).__name__}); values suppressed.')
        raise SystemExit(1) from None
