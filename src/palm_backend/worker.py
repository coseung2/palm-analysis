"""Fenced consumer core; repository and private photo storage are deployment adapters."""

from dataclasses import dataclass
from typing import Protocol

from .errors import ApiError, ProviderError
from .images import PreparedImage
from .models import AnalysisResult, BoothConfig, ResultLine
from .providers import Analyzer
from .safety import validate_story
from .timing import mark_outcome, stage


@dataclass(frozen=True)
class Job:
    id: str
    lease: str
    photo_key: str
    config: BoothConfig


class JobRepository(Protocol):
    async def dispatch(self, job: Job, stage: int) -> bool: ...
    async def finish(self, job: Job, result: AnalysisResult | None, error: str | None, *, reason: str | None = None) -> bool: ...


class PrivatePhotos(Protocol):
    async def read(self, key: str) -> PreparedImage: ...


async def consume(job: Job, repository: JobRepository, photos: PrivatePhotos, analyzer: Analyzer):
    """No automatic upstream retry after an ambiguous dispatch or transport failure."""
    async def save(result, error, *, reason=None):
        with stage('result_save'):
            kwargs = {'reason': reason} if reason is not None else {}
            accepted = await repository.finish(job, result, error, **kwargs)
        mark_outcome(('completed' if result is not None else 'failed') if accepted else 'late_result')

    try:
        with stage('photo_total'):
            image = await photos.read(job.photo_key)
        with stage('reservation_rpc'):
            allowed = await repository.dispatch(job, 1)
        if not allowed:
            return
        with stage('observation_total'):
            observation = await analyzer.observe(image)
        del image
        if observation.quality == "retake":
            await save(None, "retake_required", reason=observation.retake_reason)
            return
        with stage('reservation_rpc'):
            allowed = await repository.dispatch(job, 2)
        if not allowed:
            return
        with stage('narration_total'):
            story = validate_story(await analyzer.narrate(observation, job.config))
        readings = {line.name: line.reading for line in story.readings}
        lines = [ResultLine(
            **line.model_dump(),
            reading=readings[line.name] if line.visibility == "visible"
            else "선이 불명확하거나 보이지 않아 해석을 보류합니다.",
        ) for line in observation.lines]
        result = AnalysisResult(
            mode="ocx", is_demo=False, hand=observation.hand,
            lines=lines, visions=story.visions, config_version=job.config.version,
        )
        await save(result, None)
    except (ProviderError, ApiError) as error:
        await save(None, error.code)
    except Exception:
        # Photo-store failures and malformed output never become demo successes.
        await save(None, "worker_failed")
