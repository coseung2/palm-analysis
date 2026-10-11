"""Validate approved machine write access using a disabled runtime flag only."""
import json
import os
from urllib.error import HTTPError
from urllib.request import Request, urlopen

PROJECT = 'bde1d1c7-150c-4490-a43f-61ff9b6c6aae'
NAME = 'PALM_RUNTIME_READY'
BASE = 'https://app.infisical.com/api/v4/secrets/' + NAME


def main():
    token = os.environ['INFISICAL_TOKEN']
    body = {'projectId': PROJECT, 'environment': 'dev', 'secretPath': '/', 'type': 'shared', 'secretValue': 'false'}
    headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}
    url = BASE + '?projectId=' + PROJECT + '&environment=dev&secretPath=%2F&type=shared'
    try:
        with urlopen(Request(url, headers=headers), timeout=30) as response:
            existing = json.load(response)
        if existing.get('secret', {}).get('secretValue') != 'false':
            raise RuntimeError('Existing flag differs; no overwrite allowed')
        print('Existing disabled runtime flag verified; no overwrite.')
        return
    except HTTPError as error:
        if error.code != 404:
            raise
    with urlopen(Request(BASE, data=json.dumps(body).encode(), headers=headers, method='POST'), timeout=30) as response:
        json.load(response)
    with urlopen(Request(url, headers=headers), timeout=30) as response:
        result = json.load(response)
    if result.get('secret', {}).get('secretValue') != 'false':
        raise RuntimeError('Write readback mismatch')
    print('Machine secret write and readback verified; runtime remains disabled.')


if __name__ == '__main__':
    try:
        main()
    except Exception:
        print('Write verification failed; credentials and remote responses suppressed.')
        raise SystemExit(1) from None
