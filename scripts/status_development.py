"""Non-sensitive aggregate operational status for the isolated development runtime."""
import json
import os

from cloud_setup import request_json

REF = 'ihkbmxwidahgbrvxmrrk'


def main():
    if os.environ.get('PALM_DEV_PROJECT_REF') != REF:
        raise RuntimeError('Development target differs')
    endpoint = 'https://api.supabase.com/v1/projects/' + REF + '/database/query'
    def query(sql):
        return request_json(endpoint, os.environ['Supabase_access_token'], {'query': sql})
    output = {
        'runtime_ready': os.environ.get('PALM_RUNTIME_READY') == 'true',
        'booths': query('select enabled,count(*) as count from palm_runtime.booths group by enabled'),
        'jobs': query('select state,count(*) as count from palm_runtime.jobs group by state'),
        'today_calls': query("select coalesce(sum(reserved),0) as reserved,coalesce(sum(dispatched),0) as dispatched from palm_runtime.daily_usage where day=(now() at time zone 'UTC')::date"),
        'deletion_backlog': query('select count(*) as pending,max(attempts) as max_attempts from palm_runtime.photo_deletions where deleted_at is null'),
        'revisions': query('select name,sha256 from palm_runtime.schema_revisions order by name'),
    }
    print(json.dumps(output, indent=2, default=str))


if __name__ == '__main__':
    try:
        main()
    except Exception:
        print('Development status unavailable; credentials and rows suppressed.')
        raise SystemExit(1) from None
