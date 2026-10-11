"""Fenced consumer core; repository and private photo storage are deployment adapters."""

from dataclasses import dataclass
from typing import Protocol

from .errors import ApiError, ProviderError
from .images import PreparedImage
from .models import AnalysisResult, BoothConfig, ResultLine
from .providers import Analyzer
from .safety import validate_story


@dataclass(frozen=True)
class Job:
    id: str
    lease: str
    photo_key: str
    config: BoothConfig


class JobRepository(Protocol):
    async def dispatch(self, job: Job, stage: int) -> bool: ...
    async def finish(self, job: Job, result: AnalysisResult | None, error: str | None) -> bool: ...


class PrivatePhotos(Protocol):
    async def read(self, key: str) -> PreparedImage: ...


async def consume(job: Job, repository: JobRepository, photos: PrivatePhotos, analyzer: Analyzer):
    """No automatic upstream retry after an ambiguous dispatch or transport failure."""
    try:
        image = await photos.read(job.photo_key)
        if not await repository.dispatch(job, 1):
            return
        observation = await analyzer.observe(image)
        del image
        if observation.quality == "retake":
            await repository.finish(job, None, "retake_required")
            return
        if not await repository.dispatch(job, 2):
            return
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
        await repository.finish(job, result, None)
    except (ProviderError, ApiError) as error:
        await repository.finish(job, None, error.code)
    except Exception:
        # Photo-store failures and malformed output never become demo successes.
        await repository.finish(job, None, "worker_failed")
