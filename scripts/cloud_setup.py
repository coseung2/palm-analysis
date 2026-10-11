"""Supabase setup and Cloudflare secret provisioning; secret values stay in memory."""

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from palm_backend.config import Settings

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_REF = "pyugqoogcoynvywihgym"


def request_json(url, token, body=None):
    data = json.dumps(body).encode() if body is not None else None
    request = Request(url, data=data, headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=60) as response:
            return json.load(response)
    except HTTPError as exc:
        raise RuntimeError(f"Remote API failed with HTTP {exc.code}; response suppressed") from None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["inspect", "apply", "secrets", "verify"])
    args = parser.parse_args()
    url = os.environ["project_url"].rstrip("/")
    if urlparse(url).hostname != f"{EXPECTED_REF}.supabase.co" or urlparse(url).scheme != "https":
        raise RuntimeError("Unexpected Supabase project URL")
    token = os.environ["Supabase_access_token"]
    endpoint = f"https://api.supabase.com/v1/projects/{EXPECTED_REF}"

    def query(sql):
        return request_json(endpoint + "/database/query", token, {"query": sql})

    if args.action == "inspect":
        rows = query("select tablename, rowsecurity from pg_tables where schemaname='public' order by tablename")
        print(json.dumps(rows))
    elif args.action == "apply":
        existing = query("select tablename from pg_tables where schemaname='public' and tablename in ('palm_booth_config','palm_booth_sessions')")
        if existing:
            raise RuntimeError("Booth tables already exist; inspect before applying schema again")
        query((ROOT / "supabase/schemas/booth.sql").read_text(encoding="utf-8"))
        print("Supabase booth schema applied.")
    elif args.action == "verify":
        checks = query("""select c.relname, c.relrowsecurity,
          has_table_privilege('anon',c.oid,'SELECT') as anon_read,
          has_table_privilege('authenticated',c.oid,'SELECT') as user_read
          from pg_class c join pg_namespace n on n.oid=c.relnamespace
          where n.nspname='public' and c.relname in ('palm_booth_sessions','palm_booth_config')""")
        if len(checks) != 2 or any(not row["relrowsecurity"] or row["anon_read"] or row["user_read"] for row in checks):
            raise RuntimeError("Server-only table security check failed")
        grants = query("select has_function_privilege('anon','public.palm_booth(text,jsonb)','EXECUTE') as anon_rpc, has_function_privilege('authenticated','public.palm_booth(text,jsonb)','EXECUTE') as user_rpc")
        if grants[0]["anon_rpc"] or grants[0]["user_rpc"]:
            raise RuntimeError("RPC is exposed to browser roles")
        for path, body in (("/rest/v1/palm_booth_sessions?select=id", None), ("/rest/v1/rpc/palm_booth", {"p_op": "config_get"})):
            data = json.dumps(body).encode() if body is not None else None
            request = Request(url + path, data=data, headers={"apikey": os.environ["SUPABASE_PUBLISHABLE_KEY"], "Content-Type": "application/json"})
            try:
                with urlopen(request, timeout=30):
                    raise RuntimeError("Browser key unexpectedly accessed server-only storage")
            except HTTPError as exc:
                if exc.code not in (401, 403, 404):
                    raise RuntimeError(f"Unexpected browser access probe status: {exc.code}") from None
        print("RLS, table/RPC grants and actual publishable-key denial verified.")
    else:
        keys = request_json(endpoint + "/api-keys", token)
        service = next((item.get("api_key") for item in keys if item.get("name") == "service_role"), None)
        if not service:
            raise RuntimeError("Server service key unavailable; no new key was created")
        operator = Settings(_env_file=ROOT / ".env").operator_key.get_secret_value()
        if len(operator) < 32:
            raise RuntimeError("Operator key is too short")
        payload = json.dumps({"SUPABASE_URL":url,"SUPABASE_SERVICE_KEY":service,"OPERATOR_KEY":operator})
        executable = shutil.which("npx.cmd") or shutil.which("npx")
        subprocess.run([executable,"--yes","wrangler@4.149.0","secret","bulk"], input=payload, text=True, cwd=ROOT, check=True)
        print("Cloudflare secrets provisioned via stdin; no plaintext file or console output was used.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Do not dump environment, response bodies, or process inputs on errors.
        print(f"Setup failed: {type(exc).__name__}: {exc}")
        raise SystemExit(1) from None
