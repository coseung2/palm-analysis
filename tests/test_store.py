import asyncio
import sqlite3

import pytest

from palm_backend.errors import ApiError
from palm_backend.images import PreparedImage
from palm_backend.models import AnalysisResult, PublicError, ResultLine
from palm_backend.providers import DemoAnalyzer
from palm_backend.store import Store


def demo_result(config):
    async def run():
        provider = DemoAnalyzer()
        observation = await provider.observe(PreparedImage(b"test", "digest"))
        story = await provider.narrate(observation, config)
        return AnalysisResult(
            mode="demo",
            is_demo=True,
            hand="unknown",
            config_version=config.version,
            lines=[
                ResultLine(**line.model_dump(), reading=story.readings[i].reading)
                for i, line in enumerate(observation.lines)
            ],
            visions=story.visions,
        )

    return asyncio.run(run())


def test_cancelled_session_rejects_late_success_and_failure(tmp_path):
    store = Store(tmp_path / "test.sqlite3")
    try:
        session = store.create(False, 3600, 10)
        run_id = store.begin(session.id, "request-0001", "digest", 2)
        store.cancel(session.id)
        store.finish(session.id, run_id, result=demo_result(session.config))
        store.finish(session.id, run_id, error=PublicError(code="late_failure", message="late"))
        assert store.view(session.id).status == "cancelled"
        assert store.view(session.id).result is None
        assert store.view(session.id).error is None
    finally:
        store.close()


def test_expired_and_purged_session_cannot_be_resurrected(tmp_path):
    store = Store(tmp_path / "test.sqlite3")
    try:
        session = store.create(False, 3600, 10)
        run_id = store.begin(session.id, "request-0001", "digest", 2)
        with store.lock, store.db:
            store.db.execute("UPDATE sessions SET expires_at=0 WHERE id=?", (session.id,))
        store.finish(session.id, run_id, result=demo_result(session.config))
        with pytest.raises(ApiError):
            store.view(session.id)
        store.purge()
        store.finish(session.id, run_id, result=demo_result(session.config))
        assert store.db.execute("SELECT count(*) FROM sessions").fetchone()[0] == 0
    finally:
        store.close()


def test_token_is_hashed_and_database_has_no_photo_column(tmp_path):
    path = tmp_path / "test.sqlite3"
    store = Store(path)
    try:
        session = store.create(False, 3600, 10)
        row = dict(store.db.execute("SELECT * FROM sessions").fetchone())
        assert row["token_hash"] != session.access_token
        assert session.access_token not in str(row)
        assert not ({"photo", "image", "image_bytes", "image_path", "image_url"} & row.keys())
        store.authorize(session.id, session.access_token)
    finally:
        store.close()
    with sqlite3.connect(path) as database:
        assert database.execute("SELECT status FROM sessions").fetchone()[0] == "awaiting_image"
