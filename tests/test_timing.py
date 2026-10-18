import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta

import pytest

from palm_backend import timing
from palm_backend.images import PreparedImage
from palm_backend.models import BoothConfig
from palm_backend.providers import DemoAnalyzer
from palm_backend.worker import Job, consume


def rows(caplog):
    return [json.loads(record.message) for record in caplog.records if record.name == timing.LOGGER.name]


def test_stages_are_bounded_and_summary_has_no_identifiers(caplog, monkeypatch):
    clock = [10.0]
    monkeypatch.setattr(timing.time, 'monotonic', lambda: clock[0])
    with caplog.at_level(logging.INFO, logger=timing.LOGGER.name), timing.analysis_timing(enqueued_at='private-invalid-timestamp'):
        with timing.stage('photo_fetch'):
            clock[0] += .25
        timing.mark_outcome('completed')
    events = rows(caplog)
    summary = events[-1]
    assert summary == {
        'event':'analysis_summary', 'at':summary['at'], 'outcome':'completed',
        'consumer_ms':250, 'stages_ms':{'photo_fetch':250}, 'stage_calls':{'photo_fetch':1},
    }
    assert 'private-invalid-timestamp' not in caplog.text
    assert set(events[1]) == {'event','at','stage'}
    with pytest.raises(ValueError):
        with timing.stage('private-image-url'):
            pass


def test_stage_failures_keep_only_duration_and_status(caplog):
    with caplog.at_level(logging.INFO, logger=timing.LOGGER.name):
        with pytest.raises(RuntimeError), timing.analysis_timing():
            with timing.stage('observe_gateway'):
                raise RuntimeError('private-provider-output-token')
    assert 'private-provider-output-token' not in caplog.text
    assert rows(caplog)[-2]['outcome'] == 'failed'
    assert rows(caplog)[-1]['outcome'] == 'interrupted'
    assert 'observe_gateway' in rows(caplog)[-1]['stages_ms']
    assert timing.CURRENT.get() is None


def test_logging_failure_never_fails_analysis(monkeypatch):
    def fail(*args, **kwargs):
        raise OSError('test disk failure')
    monkeypatch.setattr(timing.LOGGER, 'info', fail)
    with timing.analysis_timing():
        with timing.stage('image_normalize'):
            pass
        timing.mark_outcome('completed')
    assert timing.CURRENT.get() is None


def test_concurrent_contexts_do_not_mix_stage_durations(caplog):
    async def run_stage(name):
        with timing.analysis_timing():
            with timing.stage(name):
                await asyncio.sleep(0)
            timing.mark_outcome('completed')
    async def run():
        await asyncio.gather(run_stage('observe_gateway'), run_stage('narrate_gateway'))
    with caplog.at_level(logging.INFO, logger=timing.LOGGER.name):
        asyncio.run(run())
    summaries = [row for row in rows(caplog) if row['event'] == 'analysis_summary']
    assert len(summaries) == 2
    assert {tuple(row['stages_ms']) for row in summaries} == {('observe_gateway',), ('narrate_gateway',)}


def test_enqueue_age_is_not_reported_as_pure_queue_wait():
    timestamp = (datetime.now(UTC) - timedelta(seconds=2)).isoformat()
    assert 1900 <= timing.enqueue_age_ms(timestamp) <= 3000
    for value in [None, 'private-value', '2026-10-01T00:00:00', (datetime.now(UTC)+timedelta(days=1)).isoformat()]:
        assert timing.enqueue_age_ms(value) is None


def test_consumer_timing_preserves_results_and_excludes_private_content(caplog):
    saved = []
    class Repository:
        async def dispatch(self, job, stage):
            return True
        async def finish(self, job, result, error, **kwargs):
            saved.append((result,error))
            return True
    class Photos:
        async def read(self, key):
            with timing.stage('photo_fetch'):
                return PreparedImage(data=b'private-image-bytes', digest='a'*64)
    async def run():
        with timing.analysis_timing():
            await consume(Job('private-job-id','private-lease','private-photo-path',BoothConfig()), Repository(), Photos(), DemoAnalyzer())
    with caplog.at_level(logging.INFO, logger=timing.LOGGER.name):
        asyncio.run(run())
    summary = rows(caplog)[-1]
    assert summary['outcome'] == 'completed'
    assert summary['stage_calls']['reservation_rpc'] == 2
    assert summary['stage_calls']['result_save'] == 1
    assert set(summary['stages_ms']) == {'photo_total','photo_fetch','reservation_rpc','observation_total','narration_total','result_save'}
    assert len(saved) == 1 and saved[0][1] is None
    for value in ['private-job-id','private-lease','private-photo-path','private-image-bytes',saved[0][0].visions[0]]:
        assert value not in caplog.text


def test_completed_metric_shape_cannot_export_arbitrary_fields(caplog):
    with caplog.at_level(logging.INFO, logger=timing.LOGGER.name), timing.analysis_timing():
        value = timing.CURRENT.get()
        value.durations['private-token'] = 100
        value.durations['photo_fetch'] = 'private-content'
        value.calls['private-token'] = 1
        value.outcome = 'private-content'
    summary = rows(caplog)[-1]
    assert summary['stages_ms'] == summary['stage_calls'] == {}
    assert summary['outcome'] == 'unknown'
    assert 'private-content' not in caplog.text and 'private-token' not in caplog.text


def test_real_adapter_stage_boundaries_with_synthetic_image_and_mock_gateway(caplog, monkeypatch):
    import io

    import httpx
    from PIL import Image

    from palm_backend.config import Settings
    from palm_backend.images import prepare_image
    from palm_backend.providers import OCXAnalyzer

    monkeypatch.setattr('palm_backend.images.locate_palm', lambda image: (20,20,280,280))
    monkeypatch.setattr('palm_backend.line_mask.line_overlay', lambda photo,path: None)
    source = io.BytesIO()
    Image.new('RGB',(320,320),'white').save(source,'PNG')
    async def run():
        photo = PreparedImage(b'test-only', 'a'*64)
        observation = await DemoAnalyzer().observe(photo)
        story = await DemoAnalyzer().narrate(observation,BoothConfig())
        calls = []
        def handler(request):
            calls.append(json.loads(request.content))
            value = observation if len(calls)==1 else story
            return httpx.Response(200,json={'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':value.model_dump_json()}]}]})
        config = Settings(_env_file=None,operator_key='test-only-operator-key-at-least-32-characters',analysis_mode='ocx',ocx_base_url='https://ocx.test',ocx_api_key='private-test-only-key',line_model_path='test-only.pth')
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            analyzer = OCXAnalyzer(config,client)
            with timing.analysis_timing():
                prepared = prepare_image(source.getvalue(),'image/png')
                observed = await analyzer.observe(prepared)
                await analyzer.narrate(observed,BoothConfig())
                timing.mark_outcome('completed')
        assert len(calls)==2
        assert calls[0]['reasoning']=={'effort':'high'}
        assert calls[0]['store'] is False and calls[1]['store'] is False
    with caplog.at_level(logging.INFO,logger=timing.LOGGER.name):
        asyncio.run(run())
    summary = rows(caplog)[-1]
    assert set(summary['stages_ms']) == {'image_normalize','palm_roi','image_enhance','line_mask','observe_gateway','narrate_gateway'}
    assert summary['stage_calls']['observe_gateway']==summary['stage_calls']['narrate_gateway']==1
    assert 'private-test-only-key' not in caplog.text


def test_reporter_whitelists_stored_log_fields():
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / 'scripts/read_analysis_timings.py'
    spec = importlib.util.spec_from_file_location('test_timing_reporter',path)
    reporter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reporter)
    row = {'event':'analysis_summary','at':datetime.now(UTC).isoformat(),'outcome':'completed',
           'consumer_ms':20,'stages_ms':{'photo_fetch':10,'private-token':15},
           'stage_calls':{'photo_fetch':1},'token':'private-key','photo':'private-photo'}
    safe = reporter.public_event(row)
    assert safe['stages_ms'] == {'photo_fetch':10}
    assert set(safe) == {'event','at','outcome','consumer_ms','stages_ms','stage_calls'}
    assert 'private' not in json.dumps(safe)
    assert reporter.public_event({'event':'private-content','at':row['at']}) is None
