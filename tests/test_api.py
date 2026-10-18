import asyncio
import io
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from palm_backend.app import create_app
from palm_backend.config import Settings
from palm_backend.errors import ProviderError
from palm_backend.providers import DemoAnalyzer

OPERATOR_KEY = "test-only-operator-key-32-characters-long"
OPERATOR = {"Authorization": f"Bearer {OPERATOR_KEY}"}


def photo(color="white", size=(320, 320), fmt="PNG"):
    stream = io.BytesIO()
    Image.new("RGB", size, color).save(stream, format=fmt)
    return stream.getvalue()


@pytest.fixture
def settings(tmp_path):
    return Settings(
        _env_file=None, operator_key=OPERATOR_KEY, database_path=tmp_path / "test.sqlite3"
    )


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as value:
        yield value


def create(client, consent=False):
    response = client.post(
        "/v1/sessions", headers=OPERATOR, json={"external_processing_consent": consent}
    )
    assert response.status_code == 201
    return response.json()


def auth(session, key=None):
    headers = {"Authorization": f"Bearer {session['access_token']}"}
    if key is not None:
        headers.update({"Idempotency-Key": key, "Content-Type": "image/png"})
    return headers


def analyze(client, session, key="request-0001", data=None):
    return client.post(
        f"/v1/sessions/{session['id']}/analysis",
        headers=auth(session, key),
        content=data if data is not None else photo(),
    )


def test_public_start_needs_no_login_but_does_not_grant_settings_or_other_sessions(settings):
    settings.public_sessions = True
    with TestClient(create_app(settings)) as client:
        assert client.get('/health').json()['public_sessions'] is True
        assert client.get('/v1/config').status_code == 200
        assert client.get('/v1/operator', headers={'Authorization': 'Bearer wrong'}).status_code == 401
        assert client.get('/v1/operator', headers=OPERATOR).json()['can_configure'] is True
        created = client.post('/v1/sessions', json={})
        assert created.status_code == 201
        session = created.json()
        assert client.get(f"/v1/sessions/{session['id']}").status_code == 401
        assert client.get(f"/v1/sessions/{session['id']}", headers=auth(session)).status_code == 200
        assert client.put('/v1/config', json=client.get('/v1/config').json()).status_code == 401


def test_public_start_limit_survives_server_restart(settings, monkeypatch):
    monkeypatch.setattr('palm_backend.store.time.time', lambda: 1800000000)
    settings.public_sessions = True
    settings.public_starts_per_minute = 1
    with TestClient(create_app(settings)) as client:
        assert client.post('/v1/sessions', json={}).status_code == 201
        assert client.post('/v1/sessions', json={}).status_code == 429
    with TestClient(create_app(settings)) as client:
        assert client.post('/v1/sessions', json={}).status_code == 429


def test_public_ocx_start_still_requires_external_photo_consent(settings):
    settings.public_sessions = True
    settings.analysis_mode = 'ocx'
    settings.ocx_base_url = 'https://ocx.test'
    settings.ocx_api_key = 'test-only-key'
    with TestClient(create_app(settings, DemoAnalyzer())) as client:
        assert client.post('/v1/sessions', json={}).status_code == 422
        assert client.post('/v1/sessions', json={'external_processing_consent': True}).status_code == 201


def test_web_assets_preserve_api_authentication(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "수문 — 손에 새겨진 우주" in response.text
    assert 'id="app"' in response.text
    assert '<script src="/app.js" type="module"></script>' in response.text
    assert 'class="cards"' not in response.text
    assert response.headers["Cache-Control"] == "no-store"
    for path, content_type in (("/app.js", "javascript"), ("/scene.js", "javascript"), ("/style.css", "text/css")):
        asset = client.get(path)
        assert asset.status_code == 200
        assert content_type in asset.headers["Content-Type"]
        assert OPERATOR_KEY not in asset.text
    audio = client.get("/portal.wav")
    assert audio.status_code == 200
    assert audio.content.startswith(b"RIFF")
    assert client.get("/.env").status_code == 404
    assert client.get("/v1/config").status_code == 401
    assert client.post("/v1/sessions", json={}).status_code == 401


def test_health_and_authentication(client):
    assert client.get("/health").json() == {"status": "ok", "analysis_mode": "demo", "public_sessions": False}
    assert client.post("/v1/sessions", json={}).status_code == 401
    assert client.get("/v1/config").status_code == 401
    assert (
        client.post("/v1/sessions", headers={"Authorization": "Bearer wrong"}, json={}).status_code
        == 401
    )


def test_demo_result_and_session_isolation(client):
    session = create(client)
    assert session["status"] == "awaiting_image"
    response = analyze(client, session)
    assert response.status_code == 200
    result = response.json()["result"]
    assert result["is_demo"] is True
    assert result["hand"] == "unknown"
    assert len(result["lines"]) == 4
    assert all(line["visibility"] == "unclear" for line in result["lines"])
    assert "오락용" in result["disclaimer"]
    assert response.headers["Cache-Control"] == "no-store"
    url = f"/v1/sessions/{session['id']}"
    other = create(client)
    assert client.get(url, headers=auth(other)).status_code == 404
    assert client.get(url, headers=auth(session)).json()["result"] == result
    assert "access_token" not in client.get(url, headers=auth(session)).json()


def test_idempotency_and_completed_result(client):
    session = create(client)
    first = analyze(client, session).json()
    second = analyze(client, session).json()
    assert second == first
    assert second["attempts"] == 1
    assert analyze(client, session, data=photo("black")).status_code == 409
    assert analyze(client, session, key="request-0002").status_code == 409


@pytest.mark.parametrize(
    "data,content_type,status,code",
    [
        (b"fake image", "image/png", 422, "invalid_image"),
        (photo(size=(64, 64)), "image/png", 422, "image_too_small"),
        (photo(), "image/jpeg", 415, "image_type_mismatch"),
        (photo(), "text/html", 415, "unsupported_image"),
    ],
)
def test_image_validation(client, data, content_type, status, code):
    session = create(client)
    headers = auth(session, "request-0001")
    headers["Content-Type"] = content_type
    response = client.post(f"/v1/sessions/{session['id']}/analysis", headers=headers, content=data)
    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert (
        client.get(f"/v1/sessions/{session['id']}", headers=auth(session)).json()["attempts"] == 0
    )


def test_upload_and_json_size_limits(settings):
    settings.max_upload_bytes = 1024
    with TestClient(create_app(settings)) as client:
        session = create(client)
        assert analyze(client, session, data=b"a" * 1025).status_code == 413
        assert (
            client.post("/v1/sessions", headers=OPERATOR, content=b"a" * 17000).status_code == 413
        )


def test_invalid_request_key_and_extra_fields(client):
    session = create(client)
    assert analyze(client, session, key="short").status_code == 422
    response = client.post("/v1/sessions", headers=OPERATOR, json={"unknown": "private-input"})
    assert response.status_code == 422
    assert "private-input" not in response.text


def test_cancel_removes_result_and_blocks_analysis(client):
    session = create(client)
    analyze(client, session)
    url = f"/v1/sessions/{session['id']}"
    cancelled = client.delete(url, headers=auth(session)).json()
    assert cancelled["status"] == "cancelled"
    assert cancelled["result"] is None
    assert client.delete(url, headers=auth(session)).json() == cancelled
    assert analyze(client, session).status_code == 409


def test_config_revision_and_session_snapshot(client):
    session = create(client)
    current = client.get("/v1/config", headers=OPERATOR).json()
    current["story_theme"] = "stars"
    updated = client.put("/v1/config", headers=OPERATOR, json=current)
    assert updated.status_code == 200
    assert updated.json()["version"] == 2
    assert client.put("/v1/config", headers=OPERATOR, json=current).status_code == 409
    old = analyze(client, session).json()
    assert old["result"]["config_version"] == 1
    assert create(client)["config"]["story_theme"] == "stars"


def test_retention_and_session_cap(settings):
    settings.max_sessions = 1
    with TestClient(create_app(settings)) as client:
        session = create(client)
        assert client.post("/v1/sessions", headers=OPERATOR, json={}).status_code == 429
        store = client.app.state.store
        with store.lock, store.db:
            store.db.execute("UPDATE sessions SET expires_at=0")
        assert client.get(f"/v1/sessions/{session['id']}", headers=auth(session)).status_code == 404
        store.purge()
        assert store.db.execute("SELECT count(*) FROM sessions").fetchone()[0] == 0
        create(client)


class RetakeAnalyzer(DemoAnalyzer):
    async def observe(self, image):
        observation = await super().observe(image)
        return observation.model_copy(
            update={"quality": "retake", "retake_reason": "손바닥을 펴고 다시 촬영해 주세요."}
        )

    async def narrate(self, observation, config):
        raise AssertionError("A rejected photo must never generate a story")


def test_retake_and_retry_limit(settings):
    with TestClient(create_app(settings, RetakeAnalyzer())) as client:
        session = create(client)
        first = analyze(client, session).json()
        assert first["status"] == "failed"
        assert first["error"]["code"] == "retake_required"
        assert first["error"]["retryable"] is True
        assert analyze(client, session).json()["attempts"] == 1
        assert analyze(client, session, "request-0002").json()["attempts"] == 2
        assert analyze(client, session, "request-0003").json()["attempts"] == 3
        assert analyze(client, session, "request-0004").status_code == 429


class FailingAnalyzer(DemoAnalyzer):
    async def observe(self, image):
        raise ProviderError("provider_configuration", "설정을 확인해 주세요.")


def test_non_retryable_failure(settings):
    with TestClient(create_app(settings, FailingAnalyzer())) as client:
        session = create(client)
        assert analyze(client, session).json()["error"]["retryable"] is False
        assert analyze(client, session, "request-0002").status_code == 409


class SlowAnalyzer(DemoAnalyzer):
    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()
        self.calls = 0

    async def observe(self, image):
        self.calls += 1
        self.started.set()
        while not self.release.is_set():
            await asyncio.sleep(0.005)
        return await super().observe(image)


def test_concurrent_idempotency_capacity_and_cancel(settings):
    settings.max_active_analyses = 1
    provider = SlowAnalyzer()
    with TestClient(create_app(settings, provider)) as client, ThreadPoolExecutor() as pool:
        session = create(client)
        other = create(client)
        pending = pool.submit(analyze, client, session)
        assert provider.started.wait(5)
        duplicate = analyze(client, session)
        assert duplicate.status_code == 202
        assert duplicate.json()["status"] == "analyzing"
        assert analyze(client, session, "request-0002").status_code == 409
        assert analyze(client, other).status_code == 429
        cancelled = client.delete(f"/v1/sessions/{session['id']}", headers=auth(session))
        assert cancelled.status_code == 200
        response = pending.result(timeout=5)
        assert response.json()["status"] == "cancelled"
        assert response.json()["result"] is None
        assert provider.calls == 1
        provider.release.set()


def test_timeout(settings):
    settings.analysis_timeout_seconds = 1
    with TestClient(create_app(settings, SlowAnalyzer())) as client:
        session = create(client)
        result = analyze(client, session).json()
        assert result["status"] == "failed"
        assert result["error"]["code"] == "analysis_timeout"


def test_restart_recovers_interrupted_jobs_and_preserves_results(settings):
    with TestClient(create_app(settings)) as client:
        done = create(client)
        result = analyze(client, done).json()["result"]
        interrupted = create(client)
        client.app.state.store.begin(interrupted["id"], "interrupted-key", "digest", 2)
    with TestClient(create_app(settings)) as client:
        assert (
            client.get(f"/v1/sessions/{done['id']}", headers=auth(done)).json()["result"] == result
        )
        failed = client.get(f"/v1/sessions/{interrupted['id']}", headers=auth(interrupted)).json()
        assert failed["status"] == "failed"
        assert failed["error"]["code"] == "interrupted"


def test_live_mode_requires_consent(settings):
    settings.analysis_mode = "claude"
    settings.anthropic_api_key = "test-key-not-used"
    with TestClient(create_app(settings, DemoAnalyzer())) as client:
        denied = client.post("/v1/sessions", headers=OPERATOR, json={})
        assert denied.status_code == 422
        assert denied.json()["error"]["code"] == "consent_required"
        assert create(client, consent=True)["external_processing_consent"] is True


def test_runtime_rejects_unsafe_configuration(settings):
    settings.operator_key = "short"
    with pytest.raises(ValueError, match="32"):
        create_app(settings)
