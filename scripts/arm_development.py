"""Enable only the reviewed development booth with a conservative call ceiling."""
import json
import os
from urllib.request import Request, urlopen

from cloud_setup import request_json
from provision_development import vault

REF = 'ihkbmxwidahgbrvxmrrk'
BOOTH = '11111111-1111-4111-8111-111111111111'
PROJECT = 'bde1d1c7-150c-4490-a43f-61ff9b6c6aae'


def main():
    if os.environ.get('PALM_DEV_PROJECT_REF') != REF:
        raise RuntimeError('Unexpected development target')
    project = request_json('https://api.supabase.com/v1/projects/' + REF, os.environ['Supabase_access_token'])
    if project.get('name') != 'palm-analysis-development':
        raise RuntimeError('Development identity differs')
    existing = request_json('https://api.supabase.com/v1/projects/' + REF + '/database/query', os.environ['Supabase_access_token'], {'query': "select id,enabled,daily_call_limit from palm_runtime.booths where id='" + BOOTH + "'"})
    if existing and (existing[0]['daily_call_limit'] != 20 or existing[0]['enabled'] is not True):
        raise RuntimeError('Existing booth differs; no overwrite')
    if not existing:
        request_json('https://api.supabase.com/v1/projects/' + REF + '/database/query', os.environ['Supabase_access_token'], {'query': "insert into palm_runtime.booths(id,enabled,daily_call_limit,max_pending,max_running) values('" + BOOTH + "',true,20,2,1)"})
    old = vault('PALM_RUNTIME_READY')
    if old not in ('false', 'true'):
        raise RuntimeError('Unexpected readiness flag')
    if old == 'false':
        body = {'projectId': PROJECT, 'environment': 'dev', 'secretPath': '/', 'type': 'shared', 'secretValue': 'true'}
        headers = {'Authorization': 'Bearer ' + os.environ['INFISICAL_TOKEN'], 'Content-Type': 'application/json'}
        with urlopen(Request('https://app.infisical.com/api/v4/secrets/PALM_RUNTIME_READY', data=json.dumps(body).encode(), headers=headers, method='PATCH'), timeout=30) as response:
            json.load(response)
    if vault('PALM_RUNTIME_READY') != 'true':
        raise RuntimeError('Readiness update readback failed')
    print('Development booth enabled: 20 upstream calls/UTC day, 2 pending jobs, 1 running job; production untouched.')


if __name__ == '__main__':
    try:
        main()
    except Exception:
        print('Development activation stopped; secrets suppressed.')
        raise SystemExit(1) from None
