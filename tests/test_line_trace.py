import pytest

from palm_backend.models import LineObservation, Observation, ResultLine
from palm_backend.providers import provider_schema


def line(**changes):
    return LineObservation.model_validate({'name':'life','visibility':'visible','trait':'관찰','description':'주름',**changes})


def test_trace_is_preserved_on_visible_lines_and_result():
    points = [{'x':.1,'y':.2},{'x':.8,'y':.9}]
    observed = line(trace=points)
    result = ResultLine(**observed.model_dump(), reading='해석')
    assert result.model_dump()['trace'] == points


@pytest.mark.parametrize('trace', [None, [], [{'x':.1,'y':.2}], [{'x':0,'y':0}]*25,
    [{'x':-1,'y':0},{'x':1,'y':1}], [{'x':float('nan'),'y':0},{'x':1,'y':1}],
    [{'x':True,'y':0},{'x':1,'y':1}], [{'x':'0.5','y':0},{'x':1,'y':1}]])
def test_bad_coordinates_are_omitted_without_discarding_reading(trace):
    assert line(trace=trace).trace == []


@pytest.mark.parametrize('visibility', ['unclear','not_visible'])
def test_uncertain_line_never_draws_a_trace(visibility):
    assert line(visibility=visibility, trace=[{'x':0,'y':0},{'x':1,'y':1}]).trace == []


def test_old_results_without_coordinates_remain_readable():
    assert line().trace == []


def test_strict_provider_schema_requires_trace_and_point_coordinates():
    schema = provider_schema(Observation)
    observation = schema['$defs']['LineObservation']
    assert set(observation['required']) == set(observation['properties'])
    assert 'trace' in observation['required']
    assert schema['$defs']['TracePoint']['required'] == ['x', 'y']
