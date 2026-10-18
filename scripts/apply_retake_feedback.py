"""Apply the additive retake-feedback revision to the isolated development DB only."""
import hashlib
import os

from cloud_setup import ROOT, request_json

REF = 'ihkbmxwidahgbrvxmrrk'
REVISION = 'retake_feedback'


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

    source = (ROOT / 'supabase/schemas/retake_feedback.sql').read_text(encoding='utf-8')
    digest = hashlib.sha256(source.encode()).hexdigest()
    previous = query("select sha256 from palm_runtime.schema_revisions where name='retake_feedback'")
    if previous:
        if previous[0]['sha256'] != digest:
            raise RuntimeError('Revision differs; no overwrite')
    else:
        for name in ('worker_api', 'visitor_api'):
            expected = hashlib.sha256((ROOT / ('supabase/schemas/' + name + '.sql')).read_text(encoding='utf-8').encode()).hexdigest()
            tracked = query("select sha256 from palm_runtime.schema_revisions where name='" + name + "'")
            if len(tracked) != 1 or tracked[0]['sha256'] != expected:
                raise RuntimeError('Baseline differs; no overwrite')
        if query("select count(*) as n from information_schema.columns where table_schema='palm_runtime' and table_name='jobs' and column_name='retake_reason'")[0]['n']:
            raise RuntimeError('Untracked feedback column; no overwrite')
        query(source.replace('commit;', "insert into palm_runtime.schema_revisions(name,sha256) values('retake_feedback','" + digest + "');\ncommit;"))
    checks = query("""select p.proname,p.prosecdef,
      has_function_privilege('anon',p.oid,'EXECUTE') as anon_execute,
      has_function_privilege('authenticated',p.oid,'EXECUTE') as user_execute
      from pg_proc p join pg_namespace n on n.oid=p.pronamespace
      where (n.nspname='public' and p.proname='palm_worker')
         or (n.nspname='palm_runtime' and p.proname='session_view')""")
    if len(checks) != 2 or any(row['prosecdef'] or row['anon_execute'] or row['user_execute'] for row in checks):
        raise RuntimeError('Feedback access checks failed')
    print('Development retake-feedback revision verified; no photo, result or credentials printed.')


if __name__ == '__main__':
    try:
        main()
    except Exception:
        print('Retake feedback apply stopped; credentials and remote responses suppressed.')
        raise SystemExit(1) from None
