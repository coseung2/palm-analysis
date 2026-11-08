"""Store the public Kakao JavaScript key in Infisical dev `/` as PALM_KAKAO_JS_KEY; prints no key value."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from provision_development import vault  # noqa: E402

NAME = 'PALM_KAKAO_JS_KEY'


def main(path):
    key = Path(path).read_text(encoding='utf-8').strip()
    if not re.fullmatch(r'[0-9a-f]{32}', key):
        raise RuntimeError('Key file is not a Kakao JavaScript key')
    vault(NAME, key)  # creates it, or verifies an identical existing value; never overwrites a different one
    print(f'{NAME} stored in Infisical dev / and read back.')


if __name__ == '__main__':
    try:
        main(sys.argv[1])
    except Exception as error:
        print(f'Kakao key store stopped ({type(error).__name__}); values suppressed.')
        raise SystemExit(1) from None
