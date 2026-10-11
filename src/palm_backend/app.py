import asyncio
import logging
import re
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from starlette.requests import ClientDisconnect

from .config import Settings
from .errors import ApiError, ProviderError
from .images import prepare_image
from .models import (
    DISCLAIMER,
    AnalysisResult,
    BoothConfig,
    ConfigUpdate,
    CreateSession,
    PublicError,
    ResultLine,
    SessionCreated,
    SessionView,
)
from .providers import Analyzer, ClaudeAnalyzer, DemoAnalyzer, OCXAnalyzer
from .safety import validate_story
from .store import Store

logger = logging.getLogger("palm_backend")
bearer = HTTPBearer(auto_error=False)


class JsonBodyLimit:
    """Bound small JSON requests before framework parsing; images are streamed separately."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if (
            scope["type"] != "http"
            or scope["method"] not in ("POST", "PUT", "PATCH")
            or scope["path"].endswith("/analysis")
        ):
            await self.app(scope, receive, send)
            return
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > 16384:
                response = JSONResponse(
                    status_code=413,
                    content={
                        "error": {
                            "code": "body_too_large",
                            "message": "요청 내용이 너무 큽니다.",
                            "retryable": False,
                        }
                    },
                    headers={"Cache-Control": "no-store"},
                )
                await response(scope, receive, send)
                return
            if not message.get("more_body", False):
                break
        delivered = False

        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, replay, send)


def create_app(settings: Settings | None = None, analyzer: Analyzer | None = None) -> FastAPI:
    settings = settings or Settings()
    settings.validate_runtime()
    tasks: dict[str, asyncio.Task] = {}

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        store = Store(settings.database_path)
        app.state.store = store
        async with httpx.AsyncClient(
            timeout=settings.analysis_timeout_seconds, follow_redirects=False
        ) as client:
            app.state.analyzer = analyzer or (
                DemoAnalyzer()
                if settings.analysis_mode == "demo"
                else OCXAnalyzer(settings, client)
                if settings.analysis_mode == "ocx"
                else ClaudeAnalyzer(settings, client)
            )

            async def cleanup():
                while True:
                    await asyncio.sleep(15)
                    for session_id, task in list(tasks.items()):
                        try:
                            store.view(session_id)
                        except ApiError:
                            task.cancel()
                    store.purge()

            cleanup_task = asyncio.create_task(cleanup())
            try:
                yield
            finally:
                cleanup_task.cancel()
                for task in list(tasks.values()):
                    task.cancel()
                await asyncio.gather(cleanup_task, *list(tasks.values()), return_exceptions=True)
                store.close()

    app = FastAPI(title="Palm Booth Backend", version="0.1.0", lifespan=lifespan)
    app.add_middleware(JsonBodyLimit)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
    )

    @app.middleware("http")
    async def no_cache(request: Request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.exception_handler(ApiError)
    async def api_error(request: Request, exc: ApiError):
        return JSONResponse(
            status_code=exc.status,
            content={
                "error": PublicError(
                    code=exc.code, message=exc.message, retryable=exc.retryable
                ).model_dump()
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "invalid_request",
                    "message": "입력 형식을 확인해 주세요.",
                    "retryable": False,
                }
            },
        )

    def credentials_token(credentials: HTTPAuthorizationCredentials | None) -> str:
        if credentials is None:
            raise ApiError(401, "authentication_required", "인증이 필요합니다.")
        return credentials.credentials

    def operator(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
        if not secrets.compare_digest(
            credentials_token(credentials).encode(),
            settings.operator_key.get_secret_value().encode(),
        ):
            raise ApiError(401, "invalid_credentials", "운영자 인증에 실패했습니다.")

    def start_access(
        request: Request,
        credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    ):
        if settings.public_sessions:
            request.app.state.store.public_start(settings.public_starts_per_minute)
        else:
            operator(credentials)

    def config_access(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
        if not settings.public_sessions:
            operator(credentials)

    def session_auth(
        session_id: str,
        request: Request,
        credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    ):
        request.app.state.store.authorize(session_id, credentials_token(credentials))

    @app.get("/health")
    async def health():
        return {"status": "ok", "analysis_mode": settings.analysis_mode, "public_sessions": settings.public_sessions}

    @app.get('/v1/operator', dependencies=[Depends(operator)])
    async def operator_status():
        return {'authorized': True, 'can_configure': True}

    @app.get("/v1/config", response_model=BoothConfig, dependencies=[Depends(config_access)])
    async def get_config(request: Request):
        return request.app.state.store.config()

    @app.put("/v1/config", response_model=BoothConfig, dependencies=[Depends(operator)])
    async def put_config(config: ConfigUpdate, request: Request):
        return request.app.state.store.update_config(config)

    @app.post(
        "/v1/sessions",
        response_model=SessionCreated,
        status_code=201,
        dependencies=[Depends(start_access)],
    )
    async def create_session(body: CreateSession, request: Request):
        if settings.analysis_mode != "demo" and not body.external_processing_consent:
            raise ApiError(
                422, "consent_required", "사진의 외부 AI 서비스 전송에 대한 동의가 필요합니다."
            )
        return request.app.state.store.create(
            body.external_processing_consent, settings.session_ttl_seconds, settings.max_sessions
        )

    @app.get(
        "/v1/sessions/{session_id}",
        response_model=SessionView,
        dependencies=[Depends(session_auth)],
    )
    async def get_session(session_id: str, request: Request):
        return request.app.state.store.view(session_id)

    @app.delete(
        "/v1/sessions/{session_id}",
        response_model=SessionView,
        dependencies=[Depends(session_auth)],
    )
    async def cancel_session(session_id: str, request: Request):
        view = request.app.state.store.cancel(session_id)
        if task := tasks.get(session_id):
            task.cancel()
        return view

    async def perform(session_id: str, run_id: str, image, store: Store, provider: Analyzer):
        try:
            async with asyncio.timeout(settings.analysis_timeout_seconds):
                view = store.view(session_id)
                observation = await provider.observe(image)
                if observation.quality == "retake":
                    raise ProviderError("retake_required", observation.retake_reason, True)
                story = validate_story(await provider.narrate(observation, view.config))
                readings = {line.name: line.reading for line in story.readings}
                lines = [
                    ResultLine(
                        **line.model_dump(),
                        reading=(
                            "선이 명확하게 확인되지 않아 해석을 보류합니다."
                            if line.visibility != "visible" and settings.analysis_mode != "demo"
                            else readings[line.name]
                        ),
                    )
                    for line in observation.lines
                ]
                result = AnalysisResult(
                    mode=settings.analysis_mode,
                    is_demo=settings.analysis_mode == "demo",
                    hand=observation.hand,
                    lines=lines,
                    visions=story.visions,
                    disclaimer=DISCLAIMER,
                    config_version=view.config.version,
                )
                store.finish(session_id, run_id, result=result)
        except TimeoutError:
            store.finish(
                session_id,
                run_id,
                error=PublicError(
                    code="analysis_timeout",
                    message="분석 시간이 초과되었습니다. 다시 시도해 주세요.",
                    retryable=True,
                ),
            )
        except ProviderError as exc:
            store.finish(
                session_id,
                run_id,
                error=PublicError(code=exc.code, message=exc.message, retryable=exc.retryable),
            )
        except asyncio.CancelledError:
            store.finish(
                session_id,
                run_id,
                error=PublicError(
                    code="interrupted",
                    message="분석이 중단되었습니다. 다시 시도해 주세요.",
                    retryable=True,
                ),
            )
            raise
        except ApiError:
            pass  # An expired or purged session must never be recreated by a late result.
        except Exception:
            logger.error("Analysis failed unexpectedly; sensitive provider output is not logged")
            store.finish(
                session_id,
                run_id,
                error=PublicError(
                    code="analysis_failed",
                    message="분석을 완료하지 못했습니다. 다시 시도해 주세요.",
                    retryable=True,
                ),
            )

    @app.post(
        "/v1/sessions/{session_id}/analysis",
        response_model=SessionView,
        dependencies=[Depends(session_auth)],
        openapi_extra={
            "requestBody": {
                "required": True,
                "content": {
                    media: {"schema": {"type": "string", "format": "binary"}}
                    for media in ("image/jpeg", "image/png", "image/webp")
                },
            }
        },
    )
    async def analyze(session_id: str, request: Request):
        key = request.headers.get("Idempotency-Key", "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", key):
            raise ApiError(422, "invalid_request_key", "8–128자의 요청 키가 필요합니다.")
        data = bytearray()
        try:
            async for chunk in request.stream():
                if len(data) + len(chunk) > settings.max_upload_bytes:
                    raise ApiError(413, "image_too_large", "사진 파일 크기를 줄여 주세요.")
                data.extend(chunk)
        except ClientDisconnect as exc:
            raise ApiError(
                400, "upload_interrupted", "사진 업로드가 중단되었습니다.", True
            ) from exc
        image = await asyncio.to_thread(
            prepare_image,
            bytes(data),
            request.headers.get("Content-Type", "").split(";")[0].strip().lower(),
        )
        data.clear()
        store = request.app.state.store
        view = store.view(session_id)
        if settings.analysis_mode != "demo" and not view.external_processing_consent:
            raise ApiError(422, "consent_required", "외부 사진 처리 동의가 필요합니다.")
        run_id = store.begin(session_id, key, image.digest, settings.max_active_analyses)
        if run_id:
            task = asyncio.create_task(
                perform(session_id, run_id, image, store, request.app.state.analyzer)
            )
            tasks[session_id] = task

            def retire(completed):
                if tasks.get(session_id) is completed:
                    tasks.pop(session_id, None)

            task.add_done_callback(retire)
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                if not task.cancelled():
                    raise
        view = store.view(session_id)
        return JSONResponse(
            status_code=202 if view.status == "analyzing" else 200, content=view.model_dump()
        )

    app.mount("/", StaticFiles(directory=Path(__file__).parent / "web", html=True), name="web")
    return app
