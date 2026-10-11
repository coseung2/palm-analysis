"""Read-only project/plan metadata; never prints credentials or response dumps."""
import json
import os

from cloud_setup import EXPECTED_REF, request_json


def main():
    token = os.environ["Supabase_access_token"]
    projects = request_json("https://api.supabase.com/v1/projects", token)
    target = next((p for p in projects if p.get("id") == EXPECTED_REF and p.get("name") == "palm-analysis"), None)
    if not target:
        raise RuntimeError("Target project not found")
    org = target["organization_id"]
    organizations = request_json("https://api.supabase.com/v1/organizations", token)
    organization = next((o for o in organizations if o.get("id") == org), None)
    if not organization:
        raise RuntimeError("Target organization not found")
    detail = request_json("https://api.supabase.com/v1/organizations/" + organization.get("slug", org), token)
    members = [p for p in projects if p.get("organization_id") == org]
    output = {
        "target_verified": True,
        "same_org_projects": [{"name": p.get("name"), "ref": p.get("id"), "status": p.get("status")} for p in members],
        "active_count": sum(p.get("status") != "INACTIVE" for p in members),
        "plan_verified": detail.get("plan") == "free",
        "plan": detail.get("plan"),
        "organization_name": detail.get("name"),
        "organization_slug": organization.get("slug", org),
        "resources_created": False,
    }
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("Resource inspection failed; remote responses suppressed.")
        raise SystemExit(1) from None
