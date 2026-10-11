"""Inspect this user's consumer environment names only; never print values."""
import json
from pathlib import Path


def main():
    found = []
    for process in Path('/proc').iterdir():
        if not process.name.isdigit():
            continue
        try:
            command = (process / 'cmdline').read_bytes().split(b'\0')
            if b'palm_backend.cloud_worker' not in command:
                continue
            names = {item.split(b'=', 1)[0].decode('ascii', errors='ignore') for item in (process / 'environ').read_bytes().split(b'\0') if b'=' in item}
            found.append({
                'consumer_found': True,
                'management_token_present': 'Supabase_access_token' in names,
                'database_password_present': 'PALM_DEV_DB_PASSWORD' in names,
                'infisical_token_present': 'INFISICAL_TOKEN' in names,
                'required_runtime_keys_present': all(name in names for name in ('PALM_OCX_API_KEY', 'PALM_DEV_SERVICE_KEY', 'PALM_RUNTIME_READY')),
            })
        except (PermissionError, FileNotFoundError, ProcessLookupError):
            continue
    print(json.dumps(found))
    if len(found) != 1 or any(found[0][key] for key in ('management_token_present', 'database_password_present', 'infisical_token_present')) or not found[0]['required_runtime_keys_present']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
