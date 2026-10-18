import asyncio

import pytest
from pydantic import ValidationError

from palm_backend.models import BoothConfig, Story
from palm_backend.providers import DemoAnalyzer
from palm_backend.safety import validate_story


def story():
    async def run():
        analyzer = DemoAnalyzer()
        observation = await analyzer.observe(None)
        return await analyzer.narrate(observation, BoothConfig())
    return asyncio.run(run())


@pytest.mark.parametrize('phrase', [
    '손금으로 수명을 예측할 수 없습니다.',
    '이 관찰은 질병의 진단이나 치료를 대신하지 않습니다.',
    '실제 전생을 알아냈다는 뜻은 아닙니다.',
    '반드시 성공한다고 단정할 수 없습니다.',
])
def test_words_in_readings_do_not_discard_whole_result(phrase):
    value = story()
    value.readings[0].reading = phrase
    assert validate_story(value) is value
    assert value.readings[0].reading == phrase


def test_visions_are_not_replaced_or_keyword_filtered():
    value = story()
    value.visions = ['전생의 사실로 확인된 기억은 아닙니다.']
    assert validate_story(value) is value
    assert value.visions == ['전생의 사실로 확인된 기억은 아닙니다.']


def test_story_schema_validation_still_rejects_missing_readings():
    with pytest.raises(ValidationError):
        Story.model_validate({'readings': [], 'visions': ['이야기']})
