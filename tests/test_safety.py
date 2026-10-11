import asyncio

import pytest

from palm_backend.errors import ProviderError
from palm_backend.models import BoothConfig
from palm_backend.providers import DemoAnalyzer
from palm_backend.safety import validate_story


def story():
    async def run():
        analyzer = DemoAnalyzer()
        observation = await analyzer.observe(None)
        return await analyzer.narrate(observation, BoothConfig())
    return asyncio.run(run())


@pytest.mark.parametrize('phrase', ['수명은 90년입니다', '곧 질병을 앓습니다', '반드시 부자가 됩니다', '실제 전생을 알아냈습니다'])
def test_unsafe_reading_is_not_shown(phrase):
    value = story()
    value.readings[0].reading = phrase
    with pytest.raises(ProviderError) as error:
        validate_story(value)
    assert error.value.code == 'unsafe_provider_result'
    assert not error.value.retryable


def test_unsafe_vision_is_blocked_and_demo_stays_valid():
    value = story()
    assert validate_story(value) is value
    value.visions = ['당신의 죽음을 예측합니다.']
    with pytest.raises(ProviderError):
        validate_story(value)
