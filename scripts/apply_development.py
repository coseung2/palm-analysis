"""Apply the reviewed candidate to the new development project only, never demo."""
import hashlib
import json
import os

from cloud_setup import ROOT, request_json

EXPECTED = 'ihkbmxwidahgbrvxmrrk'


def main():
    if os.environ.get('PALM_DEV_PROJECT_REF') != EXPECTED:
        raise RuntimeError('Development ref differs')
    token = os.environ['Supabase_access_token']
    endpoint = 'https://api.supabase.com/v1/projects/' + EXPECTED
    project = request_json(endpoint, token)
    if project.get('name') != 'palm-analysis-development' or project.get('status') != 'ACTIVE_HEALTHY':
        raise RuntimeError('Development project not verified')
    def query(sql):
        return request_json(endpoint + '/database/query', token, {'query': sql})
    source = (ROOT / 'supabase/schemas/jobs.sql').read_text(encoding='utf-8')
    digest = hashlib.sha256(source.encode()).hexdigest()
    present = query("select exists(select 1 from pg_namespace where nspname='palm_runtime') as present")[0]['present']
    if present:
        rows = query("select sha256 from palm_runtime.schema_revisions where name='runtime_baseline'")
        if len(rows) != 1 or rows[0]['sha256'] != digest:
            raise RuntimeError('Schema already exists with different revision; no overwrite')
        print('Development schema already matches tracked baseline; no change.')
        return
    ledger = """
create table palm_runtime.schema_revisions(name text primary key,sha256 text not null,applied_at timestamptz not null default now());
alter table palm_runtime.schema_revisions enable row level security;
revoke all on palm_runtime.schema_revisions from public,anon,authenticated;
grant select on palm_runtime.schema_revisions to service_role;
insert into palm_runtime.schema_revisions(name,sha256) values('runtime_baseline','""" + digest + "');\ncommit;"
    if source.count('commit;') != 1:
        raise RuntimeError('Unexpected transaction structure')
    query(source.replace('commit;', ledger))
    checks = query("""select c.relname,c.relrowsecurity,
      has_table_privilege('anon',c.oid,'SELECT,INSERT,UPDATE,DELETE') as anon_access,
      has_table_privilege('authenticated',c.oid,'SELECT,INSERT,UPDATE,DELETE') as user_access
      from pg_class c join pg_namespace n on n.oid=c.relnamespace
      where n.nspname='palm_runtime' and c.relkind='r'""")
    if len(checks) != 6 or any(not row['relrowsecurity'] or row['anon_access'] or row['user_access'] for row in checks):
        raise RuntimeError('Post-apply access checks failed')
    print(json.dumps({'development_ref': EXPECTED, 'schema_applied': True, 'tables_rls_server_only': True, 'revision_sha256': digest, 'supabase_cli_history_repaired': False, 'runtime_enabled': False}))


if __name__ == '__main__':
    try:
        main()
    except Exception:
        print('Development schema apply stopped; details and credentials suppressed.')
        raise SystemExit(1) from None
