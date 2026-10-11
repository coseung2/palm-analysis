"""Apply tested login-free API revision to the isolated development DB only."""
import hashlib
import os

from cloud_setup import ROOT, request_json

REF = 'ihkbmxwidahgbrvxmrrk'


def main():
    if os.environ.get('PALM_DEV_PROJECT_REF') != REF:
        raise RuntimeError('Development ref differs')
    token = os.environ['Supabase_access_token']
    endpoint = 'https://api.supabase.com/v1/projects/' + REF
    project = request_json(endpoint, token)
    if project.get('name') != 'palm-analysis-development' or project.get('status') != 'ACTIVE_HEALTHY':
        raise RuntimeError('Project identity differs')
    def query(sql):
        return request_json(endpoint + '/database/query', token, {'query': sql})
    source = (ROOT / 'supabase/schemas/visitor_api.sql').read_text(encoding='utf-8')
    digest = hashlib.sha256(source.encode()).hexdigest()
    previous = query("select sha256 from palm_runtime.schema_revisions where name='visitor_api'")
    if previous:
        if previous[0]['sha256'] != digest:
            raise RuntimeError('Revision differs; no overwrite')
    else:
        if query("select to_regprocedure('public.palm_visitor(text,jsonb)') is not null as present")[0]['present']:
            raise RuntimeError('Untracked existing API; no overwrite')
        query(source.replace('commit;', "insert into palm_runtime.schema_revisions(name,sha256) values('visitor_api','" + digest + "');\ncommit;"))
    checks = query("""select p.proname,p.prosecdef,
      has_function_privilege('anon',p.oid,'EXECUTE') as anon_execute,
      has_function_privilege('authenticated',p.oid,'EXECUTE') as user_execute
      from pg_proc p join pg_namespace n on n.oid=p.pronamespace
      where n.nspname='public' and p.proname in ('palm_visitor','palm_maintenance','palm_reschedule_photo')""")
    if len(checks) != 3 or any(row['prosecdef'] or row['anon_execute'] or row['user_execute'] for row in checks):
        raise RuntimeError('API access checks failed')
    print('Development visitor API revision tracked; browser SQL execution denied; booths/runtime remain disabled.')


if __name__ == '__main__':
    try:
        main()
    except Exception:
        print('Visitor API apply stopped; credentials and remote responses suppressed.')
        raise SystemExit(1) from None
