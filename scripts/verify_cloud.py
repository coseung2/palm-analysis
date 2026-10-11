"""Exercise only demo data against the deployed operator-only booth."""

import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from palm_backend.config import Settings

URL = "https://palm-analysis.mdownloader.workers.dev"
ROOT = Path(__file__).resolve().parents[1]


def call(path, method="GET", token=None, body=None, key=None):
    headers = {"Content-Type": "application/json", "User-Agent": "PalmBoothVerification/1.0"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if key:
        headers["Idempotency-Key"] = key
    data = json.dumps(body).encode() if body is not None else None
    request = Request(URL + path, method=method, data=data, headers=headers)
    try:
        with urlopen(request, timeout=30) as response:
            return response.status, json.load(response)
    except HTTPError as exc:
        return exc.code, json.load(exc)


def main():
    operator = Settings(_env_file=ROOT / ".env").operator_key.get_secret_value()
    assert call("/v1/config")[0] == 401
    status, session = call("/v1/sessions", "POST", operator, {})
    assert status == 201
    path = f"/v1/sessions/{session['id']}"
    token = session["access_token"]
    try:
        assert call(path, token="wrong-token")[0] == 404
        status, result = call(path + "/analysis", "POST", token, {"demo": True}, "cloud-verification-001")
        assert status == 200 and result["status"] == "completed"
        assert len(result["result"]["lines"]) == 4 and result["result"]["is_demo"]
        assert "access_token" not in result
        assert call(path, token=token)[1]["result"] == result["result"]
        status, duplicate = call(path + "/analysis", "POST", token, {"demo": True}, "cloud-verification-001")
        assert status == 200 and duplicate["attempts"] == 1
        assert call(path + "/analysis", "POST", token, {"demo": True}, "cloud-verification-002")[0] == 409
        status, cancelled = call(path, "DELETE", token)
        assert status == 200 and cancelled["status"] == "cancelled" and cancelled["result"] is None
        assert call(path + "/analysis", "POST", token, {"demo": True}, "cloud-verification-003")[0] == 409
        print("Live API: authentication, persisted result, idempotency, conflict and cancellation passed.")
    finally:
        call(path, "DELETE", token)


if __name__ == "__main__":
    main()
