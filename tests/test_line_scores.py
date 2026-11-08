import pytest
from pydantic import ValidationError

from palm_backend.models import LINE_TRAITS, LineReading, Story
from palm_backend.providers import STORY_SYSTEM, provider_schema


def scores(name, value=70):
    return [{'trait': t, 'score': value, 'basis': '선이 길고 깊음'} for t in LINE_TRAITS[name]]


def test_each_line_scores_its_own_five_traits_in_order():
    reading = LineReading(name='head', reading='곧은 두뇌선입니다.', scores=scores('head'))
    assert [s.trait for s in reading.scores] == ['상상력', '직관력', '논리력', '신중함', '집중력']
    with pytest.raises(ValidationError):
        LineReading(name='head', reading='x', scores=scores('life'))
    with pytest.raises(ValidationError):
        LineReading(name='head', reading='x', scores=list(reversed(scores('head'))))


def test_scores_are_bounded_and_optional_for_withheld_lines():
    with pytest.raises(ValidationError):
        LineReading(name='fate', reading='x', scores=scores('fate', 101))
    assert LineReading(name='fate', reading='보류합니다.').scores == []


def test_health_lifespan_and_wealth_are_scored_but_kept_light():
    assert '건강운' in LINE_TRAITS['life'] and '수명운' in LINE_TRAITS['life'] and '재물운' in LINE_TRAITS['fate']
    assert 'never name a disease' in STORY_SYSTEM and 'year of death' in STORY_SYSTEM
    schema = provider_schema(Story)
    assert 'scores' in schema['$defs']['LineReading']['required']
