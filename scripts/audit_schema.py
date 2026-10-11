"""Read-only metadata comparison; no session rows, keys or secret values are read."""

import hashlib
import json
import os
import re
from urllib.parse import urlparse

from cloud_setup import EXPECTED_REF, ROOT, request_json

EXPECTED_COLUMNS = {
    "palm_booth_config": {"id": "smallint", "settings": "jsonb"},
    "palm_booth_sessions": {
        "id": "uuid", "token_hash": "text", "created_at": "timestamp with time zone",
        "expires_at": "timestamp with time zone", "status": "text", "config": "jsonb",
        "consent": "boolean", "attempts": "integer", "request_key": "text", "result": "jsonb",
    },
}


def normalized_body(source):
    return re.sub(r"\s+", " ", re.sub(r"--[^\n]*", "", source)).strip()


def main():
    url = urlparse(os.environ["project_url"])
    if url.scheme != "https" or url.netloc != f"{EXPECTED_REF}.supabase.co":
        raise RuntimeError("Unexpected Supabase project")
    token = os.environ["Supabase_access_token"]
    endpoint = f"https://api.supabase.com/v1/projects/{EXPECTED_REF}"
    project = request_json(endpoint, token)
    if project.get("id") != EXPECTED_REF or project.get("name") != "palm-analysis":
        raise RuntimeError("Project identity check failed")
    if project.get("status") != "ACTIVE_HEALTHY":
        raise RuntimeError("Project is not healthy")

    def query(sql):
        return request_json(endpoint + "/database/query", token, {"query": sql})

    columns = query("""select table_name, column_name, data_type from information_schema.columns
      where table_schema='public' and table_name in ('palm_booth_config','palm_booth_sessions')
      order by table_name, ordinal_position""")
    actual = {table: {} for table in EXPECTED_COLUMNS}
    for column in columns:
        actual[column["table_name"]][column["column_name"]] = column["data_type"]
    security = query("""select c.relname, c.relrowsecurity,
      has_table_privilege('anon',c.oid,'SELECT,INSERT,UPDATE,DELETE') as anon_access,
      has_table_privilege('authenticated',c.oid,'SELECT,INSERT,UPDATE,DELETE') as user_access
      from pg_class c join pg_namespace n on n.oid=c.relnamespace
      where n.nspname='public' and c.relname in ('palm_booth_config','palm_booth_sessions')""")
    functions = query("""select p.prosrc, p.prosecdef,
      has_function_privilege('anon',p.oid,'EXECUTE') as anon_execute,
      has_function_privilege('authenticated',p.oid,'EXECUTE') as user_execute
      from pg_proc p join pg_namespace n on n.oid=p.pronamespace
      where n.nspname='public' and p.proname='palm_booth'
      and pg_get_function_identity_arguments(p.oid)='p_op text, p_args jsonb'""")
    declaration = (ROOT / "supabase/schemas/booth.sql").read_text(encoding="utf-8")
    match = re.search(r"as \$\$(.*?)\$\$;", declaration, re.DOTALL)
    body_matches = len(functions) == 1 and bool(match) and normalized_body(functions[0]["prosrc"]) == normalized_body(match[1])
    history_exists = query("select to_regclass('supabase_migrations.schema_migrations') is not null as present")[0]["present"]
    versions = query("select version from supabase_migrations.schema_migrations order by version") if history_exists else []
    report = {
        "project_verified": True, "project_ref": EXPECTED_REF,
        "column_types_match": actual == EXPECTED_COLUMNS,
        "rpc_body_matches_declaration": body_matches,
        "tables_server_only": len(security) == 2 and all(row["relrowsecurity"] and not row["anon_access"] and not row["user_access"] for row in security),
        "rpc_server_only_invoker": len(functions) == 1 and not any(functions[0][key] for key in ("prosecdef", "anon_execute", "user_execute")),
        "migration_history_present": history_exists,
        "migration_versions": [row["version"] for row in versions],
        "declaration_sha256": hashlib.sha256(declaration.encode()).hexdigest(),
        "limitations": "Column types and RPC body/grants only; indexes, defaults and constraints need a full schema diff before migration.",
    }
    print(json.dumps(report, indent=2))
    if not all(report[key] for key in ("column_types_match", "rpc_body_matches_declaration", "tables_server_only", "rpc_server_only_invoker")):
        raise RuntimeError("Metadata drift detected; no changes were applied")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("Schema audit failed; remote responses and credentials suppressed.")
        raise SystemExit(1) from None
