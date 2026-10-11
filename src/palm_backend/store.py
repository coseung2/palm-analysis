import hashlib
import secrets
import sqlite3
import threading
import time
import uuid
from pathlib import Path

from .errors import ApiError
from .models import AnalysisResult, BoothConfig, PublicError, SessionCreated, SessionView


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY, token_hash TEXT NOT NULL,
                status TEXT NOT NULL, created_at REAL NOT NULL, expires_at REAL NOT NULL,
                consent INTEGER NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
                config TEXT NOT NULL, run_id TEXT, request_key TEXT, image_hash TEXT,
                result TEXT, error TEXT
            );
            CREATE INDEX IF NOT EXISTS sessions_expiry ON sessions(expires_at);
            CREATE TABLE IF NOT EXISTS public_starts (
                minute INTEGER PRIMARY KEY, starts INTEGER NOT NULL CHECK(starts>=0)
            );
            CREATE TABLE IF NOT EXISTS settings (
                id INTEGER PRIMARY KEY CHECK(id=1), config TEXT NOT NULL
            );
        """)
        with self.db:
            self.db.execute(
                "INSERT OR IGNORE INTO settings VALUES (1, ?)",
                (BoothConfig().model_dump_json(),),
            )
            self.db.execute(
                "UPDATE sessions SET status='failed', run_id=NULL, error=? WHERE status='analyzing'",
                (
                    PublicError(
                        code="interrupted",
                        message="서버가 재시작되었습니다. 다시 시도해 주세요.",
                        retryable=True,
                    ).model_dump_json(),
                ),
            )
        self.purge()

    def close(self):
        with self.lock:
            self.db.close()

    def purge(self):
        with self.lock, self.db:
            self.db.execute("DELETE FROM sessions WHERE expires_at <= ?", (time.time(),))

    def public_start(self, limit: int):
        minute = int(time.time() // 60)
        with self.lock, self.db:
            self.db.execute("DELETE FROM public_starts WHERE minute < ?", (minute - 2,))
            row = self.db.execute("SELECT starts FROM public_starts WHERE minute=?", (minute,)).fetchone()
            if row and row["starts"] >= limit:
                raise ApiError(429, "request_limit", "체험 요청이 많습니다. 잠시 후 다시 시도해 주세요.", True)
            self.db.execute(
                "INSERT INTO public_starts(minute,starts) VALUES (?,1) ON CONFLICT(minute) DO UPDATE SET starts=starts+1",
                (minute,),
            )

    def config(self) -> BoothConfig:
        with self.lock:
            row = self.db.execute("SELECT config FROM settings WHERE id=1").fetchone()
            return BoothConfig.model_validate_json(row["config"])

    def update_config(self, config: BoothConfig) -> BoothConfig:
        with self.lock, self.db:
            current = self.config()
            if current.version != config.version:
                raise ApiError(409, "config_conflict", "설정이 변경되었습니다. 다시 조회해 주세요.")
            updated = config.model_copy(update={"version": current.version + 1})
            self.db.execute("UPDATE settings SET config=? WHERE id=1", (updated.model_dump_json(),))
            return updated

    def create(self, consent: bool, ttl: int, limit: int) -> SessionCreated:
        token = secrets.token_urlsafe(32)
        session_id = str(uuid.uuid4())
        now = time.time()
        with self.lock, self.db:
            self.purge()
            count = self.db.execute("SELECT count(*) FROM sessions").fetchone()[0]
            if count >= limit:
                raise ApiError(
                    429, "session_limit", "세션 한도에 도달했습니다. 잠시 후 시도해 주세요.", True
                )
            self.db.execute(
                "INSERT INTO sessions (id,token_hash,status,created_at,expires_at,consent,config) VALUES (?,?,?,?,?,?,?)",
                (
                    session_id,
                    self._hash(token),
                    "awaiting_image",
                    now,
                    now + ttl,
                    consent,
                    self.config().model_dump_json(),
                ),
            )
            view = self.view(session_id)
        return SessionCreated(**view.model_dump(), access_token=token)

    @staticmethod
    def _hash(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def authorize(self, session_id: str, token: str):
        with self.lock:
            row = self.db.execute(
                "SELECT token_hash, expires_at FROM sessions WHERE id=?", (session_id,)
            ).fetchone()
            if (
                not row
                or row["expires_at"] <= time.time()
                or not secrets.compare_digest(row["token_hash"], self._hash(token))
            ):
                raise ApiError(404, "session_not_found", "세션이 없거나 만료되었습니다.")

    def view(self, session_id: str) -> SessionView:
        with self.lock:
            row = self.db.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
            if not row or row["expires_at"] <= time.time():
                raise ApiError(404, "session_not_found", "세션이 없거나 만료되었습니다.")
            return SessionView(
                id=row["id"],
                status=row["status"],
                created_at=row["created_at"],
                expires_at=row["expires_at"],
                external_processing_consent=bool(row["consent"]),
                attempts=row["attempts"],
                config=BoothConfig.model_validate_json(row["config"]),
                result=AnalysisResult.model_validate_json(row["result"]) if row["result"] else None,
                error=PublicError.model_validate_json(row["error"]) if row["error"] else None,
            )

    def begin(self, session_id: str, key: str, image_hash: str, max_active: int) -> str | None:
        with self.lock, self.db:
            view = self.view(session_id)
            row = self.db.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone()
            if view.status == "cancelled":
                raise ApiError(
                    409, "session_cancelled", "취소된 세션입니다. 새 체험을 시작해 주세요."
                )
            if row["request_key"] == key:
                if row["image_hash"] != image_hash:
                    raise ApiError(
                        409,
                        "idempotency_conflict",
                        "같은 요청 키에 다른 사진을 사용할 수 없습니다.",
                    )
                return None
            if view.status == "analyzing":
                raise ApiError(409, "analysis_in_progress", "이미 분석 중입니다.")
            if view.status == "completed":
                raise ApiError(
                    409, "session_completed", "완료된 결과를 조회하거나 새 세션을 만들어 주세요."
                )
            if view.status == "failed" and view.error and not view.error.retryable:
                raise ApiError(409, "not_retryable", "새 세션으로 체험을 시작해 주세요.")
            if view.attempts >= 3:
                raise ApiError(
                    429, "attempt_limit", "재시도 한도에 도달했습니다. 새 세션을 만들어 주세요."
                )
            count = self.db.execute(
                "SELECT count(*) FROM sessions WHERE status='analyzing' AND expires_at > ?",
                (time.time(),),
            ).fetchone()[0]
            if count >= max_active:
                raise ApiError(
                    429, "analysis_busy", "다른 손님을 분석 중입니다. 잠시 후 시도해 주세요.", True
                )
            run_id = str(uuid.uuid4())
            self.db.execute(
                "UPDATE sessions SET status='analyzing', attempts=attempts+1, run_id=?, request_key=?, image_hash=?, error=NULL WHERE id=?",
                (run_id, key, image_hash, session_id),
            )
            return run_id

    def finish(
        self,
        session_id: str,
        run_id: str,
        result: AnalysisResult | None = None,
        error: PublicError | None = None,
    ):
        with self.lock, self.db:
            self.db.execute(
                "UPDATE sessions SET status=?,result=?,error=?,run_id=NULL WHERE id=? AND status='analyzing' AND run_id=? AND expires_at > ?",
                (
                    "completed" if result else "failed",
                    result.model_dump_json() if result else None,
                    error.model_dump_json() if error else None,
                    session_id,
                    run_id,
                    time.time(),
                ),
            )

    def cancel(self, session_id: str) -> SessionView:
        with self.lock, self.db:
            self.view(session_id)
            self.db.execute(
                "UPDATE sessions SET status='cancelled',run_id=NULL,result=NULL,error=NULL,image_hash=NULL,request_key=NULL WHERE id=?",
                (session_id,),
            )
            return self.view(session_id)
