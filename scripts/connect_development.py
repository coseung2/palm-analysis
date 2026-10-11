"""Approved development-only service key, private bucket and RPC bridge setup."""
import hashlib
import json
import os
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from cloud_setup import ROOT, request_json
from provision_development import vault

REF = 'ihkbmxwidahgbrvxmrrk'


def main():
    if os.environ.get('PALM_DEV_PROJECT_REF') != REF:
        raise RuntimeError('Unexpected development project')
    token = os.environ['Supabase_access_token']
    endpoint = 'https://api.supabase.com/v1/projects/' + REF
    project = request_json(endpoint, token)
    if project.get('name') != 'palm-analysis-development' or project.get('status') != 'ACTIVE_HEALTHY':
        raise RuntimeError('Project not verified')
    keys = request_json(endpoint + '/api-keys', token)
    key = next((k.get('api_key') for k in keys if k.get('name') == 'service_role'), None)
    if not key:
        raise RuntimeError('Existing server key unavailable; no new key created')
    vault('PALM_DEV_SERVICE_KEY', key)
    base = 'https://' + REF + '.supabase.co'
    headers = {'apikey': key, 'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'}
    try:
        with urlopen(Request(base + '/storage/v1/bucket/palm-uploads', headers=headers), timeout=30) as response:
            bucket = json.load(response)
    except HTTPError as error:
        failure = json.load(error)
        missing = error.code == 404 or (error.code == 400 and failure.get('message') == 'Bucket not found')
        if not missing:
            raise
        body = {'id': 'palm-uploads', 'name': 'palm-uploads', 'public': False, 'file_size_limit': 5242880, 'allowed_mime_types': ['image/jpeg', 'image/png', 'image/webp']}
        with urlopen(Request(base + '/storage/v1/bucket', data=json.dumps(body).encode(), headers=headers, method='POST'), timeout=30) as response:
            json.load(response)
        with urlopen(Request(base + '/storage/v1/bucket/palm-uploads', headers=headers), timeout=30) as response:
            bucket = json.load(response)
    if bucket.get('public') is not False or bucket.get('file_size_limit') != 5242880:
        raise RuntimeError('Private bucket restrictions do not match')

    def query(sql):
        return request_json(endpoint + '/database/query', token, {'query': sql})
    source = (ROOT / 'supabase/schemas/worker_api.sql').read_text(encoding='utf-8')
    digest = hashlib.sha256(source.encode()).hexdigest()
    previous = query("select sha256 from palm_runtime.schema_revisions where name='worker_api'")
    if previous:
        if previous[0]['sha256'] != digest:
            raise RuntimeError('Worker API revision differs; no overwrite')
    else:
        query(source.replace('commit;', "insert into palm_runtime.schema_revisions(name,sha256) values('worker_api','" + digest + "');\ncommit;"))
    checks = query("""select p.prosecdef,
      has_function_privilege('anon',p.oid,'EXECUTE') as anon_execute,
      has_function_privilege('authenticated',p.oid,'EXECUTE') as user_execute
      from pg_proc p join pg_namespace n on n.oid=p.pronamespace
      where n.nspname='public' and p.proname='palm_worker'""")
    if len(checks) != 1 or any(checks[0].values()):
        raise RuntimeError('Worker API privilege check failed')
    request = Request(base + '/rest/v1/rpc/palm_worker', data=b'{"p_op":"booths"}', headers=headers)
    with urlopen(request, timeout=30) as response:
        booths = json.load(response)
    if booths != []:
        raise RuntimeError('Unexpected enabled booth; runtime remains disabled')
    print('Development server key stored; private 5MiB bucket and service-only worker RPC verified; runtime disabled.')


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(json.dumps({'setup_stopped': True, 'error_type': type(error).__name__, 'http_status': getattr(error, 'code', None), 'details_suppressed': True}))
        raise SystemExit(1) from None
