import json
import logging

import pytest

from palm_backend.runtime_logging import event


def test_runtime_events_are_allowlisted_and_exclude_user_data(caplog):
    with caplog.at_level(logging.INFO, logger='palm_runtime_events'):
        event('job_finished', outcome='failed')
        event('job_cycle_duration', duration_ms=1000)
    payloads = [json.loads(record.message) for record in caplog.records]
    assert len(payloads) == 2
    assert set(payloads[0]) == {'event', 'at', 'outcome'}
    assert set(payloads[1]) == {'event', 'at', 'duration_ms'}
    with pytest.raises(TypeError):
        event('job_finished', token='test-private-token')
    with pytest.raises(ValueError):
        event('private-photo-text')
