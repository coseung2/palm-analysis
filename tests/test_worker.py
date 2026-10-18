import asyncio

from palm_backend.errors import ProviderError
from palm_backend.images import PreparedImage
from palm_backend.models import BoothConfig
from palm_backend.providers import DemoAnalyzer
from palm_backend.worker import Job, consume


class Repository:
    def __init__(self, denied=None):
        self.denied = denied
        self.stages = []
        self.results = []
        self.reasons = []

    async def dispatch(self, job, stage):
        self.stages.append(stage)
        return stage != self.denied

    async def finish(self, job, result, error, *, reason=None):
        self.results.append((result, error))
        self.reasons.append(reason)
        return True


class Photos:
    async def read(self, key):
        return PreparedImage(data=b"synthetic-test-only", digest="a" * 64)


class Analyzer(DemoAnalyzer):
    def __init__(self, retake=False, failure=False):
        self.retake = retake
        self.failure = failure
        self.calls = []

    async def observe(self, image):
        self.calls.append("observe")
        if self.failure:
            raise ProviderError("provider_busy", "test-only", True)
        value = await super().observe(image)
        return value.model_copy(update={"quality": "retake", "retake_reason": "다시 촬영"}) if self.retake else value

    async def narrate(self, observation, config):
        self.calls.append("narrate")
        return await super().narrate(observation, config)


def run(repository, analyzer):
    asyncio.run(consume(Job("job", "lease", "job.jpg", BoothConfig()), repository, Photos(), analyzer))


def test_consumer_fences_before_each_external_call():
    for stage, expected in [(1, []), (2, ["observe"])]:
        repo, analyzer = Repository(denied=stage), Analyzer()
        run(repo, analyzer)
        assert analyzer.calls == expected
        assert repo.results == []


def test_retake_skips_story_and_reports_failure():
    repo, analyzer = Repository(), Analyzer(retake=True)
    run(repo, analyzer)
    assert analyzer.calls == ["observe"]
    assert repo.results == [(None, "retake_required")]
    assert repo.reasons == ["다시 촬영"]


def test_failed_provider_is_not_retried_or_replaced_with_demo():
    repo, analyzer = Repository(), Analyzer(failure=True)
    run(repo, analyzer)
    assert analyzer.calls == ["observe"]
    assert repo.results == [(None, "provider_busy")]


def test_result_withholds_unclear_lines_even_if_story_contains_a_reading():
    repo, analyzer = Repository(), Analyzer()
    run(repo, analyzer)
    assert repo.stages == [1, 2]
    result, error = repo.results[0]
    assert error is None
    assert result.mode == "ocx" and not result.is_demo
    assert len(result.lines) == 4
    assert all("보류" in line.reading for line in result.lines)
    assert analyzer.calls == ['observe', 'narrate']


def test_partially_readable_palm_is_completed_without_inventing_hidden_lines():
    class PartialPalm(Analyzer):
        async def observe(self, image):
            value = await super().observe(image)
            lines = [line.model_copy(update={
                'visibility': 'visible' if line.name == 'life' else 'not_visible',
                'trait': '부분 관찰' if line.name == 'life' else '관찰 불가',
            }) for line in value.lines]
            return value.model_copy(update={'quality': 'usable', 'hand': 'unknown', 'lines': lines})

    repo, analyzer = Repository(), PartialPalm()
    run(repo, analyzer)
    result, error = repo.results[0]
    assert error is None
    assert analyzer.calls == ['observe', 'narrate']
    assert result.hand == 'unknown'
    assert sum(line.visibility == 'visible' for line in result.lines) == 1
    assert all('보류' in line.reading for line in result.lines if line.visibility != 'visible')
    assert repo.reasons == [None]
