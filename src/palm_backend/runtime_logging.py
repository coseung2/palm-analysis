"""Bounded operational events: no photos, observations, IDs, tokens or provider bodies."""
import json
import logging
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOGGER = logging.getLogger('palm_runtime_events')
EVENTS = {'job_finished', 'late_result_dropped', 'consumer_cycle_failed', 'job_cycle_duration'}


def configure():
    if LOGGER.handlers:
        return
    path = Path(__file__).resolve().parents[2] / 'data/runtime-events.jsonl'
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(path, maxBytes=262144, backupCount=2, encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(message)s'))
    LOGGER.addHandler(handler)
    LOGGER.setLevel(logging.INFO)
    LOGGER.propagate = False


def event(name, *, outcome=None, duration_ms=None):
    if name not in EVENTS:
        raise ValueError('Unknown runtime event')
    payload = {'event': name, 'at': datetime.now(UTC).isoformat()}
    if outcome in ('completed', 'failed'):
        payload['outcome'] = outcome
    if isinstance(duration_ms, int) and 0 <= duration_ms <= 300000:
        payload['duration_ms'] = duration_ms
    LOGGER.info(json.dumps(payload))
