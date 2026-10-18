"""Bounded timing only: never persist photos, results, identifiers or errors."""
import json
import logging
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOGGER = logging.getLogger('palm_analysis_timing')
STAGES = frozenset({
    'photo_total', 'photo_fetch', 'image_normalize', 'palm_roi', 'image_enhance', 'line_mask',
    'observation_total', 'observe_gateway', 'narration_total', 'narrate_gateway',
    'reservation_rpc', 'result_save',
})
STATUSES = frozenset({'completed', 'failed', 'interrupted', 'late_result', 'unknown'})
CURRENT = ContextVar('palm_analysis_timing', default=None)


@dataclass
class Measurement:
    durations: dict = field(default_factory=dict)
    calls: dict = field(default_factory=dict)
    outcome: str = 'unknown'


def configure_timing():
    if LOGGER.handlers:
        return
    try:
        path = Path(__file__).resolve().parents[2] / 'data/analysis-timing.jsonl'
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(path, maxBytes=262144, backupCount=2, encoding='utf-8')
        handler.setFormatter(logging.Formatter('%(message)s'))
        LOGGER.addHandler(handler)
        LOGGER.setLevel(logging.INFO)
        LOGGER.propagate = False
    except OSError:
        pass  # Observability must not make an otherwise valid analysis fail.


def _emit(event, **fields):
    try:
        payload = {'event': event, 'at': datetime.now(UTC).isoformat(), **fields}
        LOGGER.info(json.dumps(payload))
    except Exception:
        pass


def mark_outcome(value):
    measurement = CURRENT.get()
    if measurement is not None and value in STATUSES:
        measurement.outcome = value


def _elapsed(start):
    return max(0, min(900000, int((time.monotonic() - start) * 1000)))


def enqueue_age_ms(value):
    # This includes upload + queue wait + claim, NOT pure queue wait.
    if not isinstance(value, str):
        return None
    try:
        created = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if created.tzinfo is None:
            return None
        elapsed = int((datetime.now(UTC) - created).total_seconds() * 1000)
        return elapsed if 0 <= elapsed <= 900000 else None
    except (ValueError, OverflowError):
        return None


@contextmanager
def analysis_timing(*, enqueued_at=None):
    measurement = Measurement()
    token = CURRENT.set(measurement)
    start = time.monotonic()
    age = enqueue_age_ms(enqueued_at)
    _emit('analysis_started', **({'enqueue_to_claim_ms': age} if age is not None else {}))
    try:
        yield
    except BaseException:
        measurement.outcome = 'interrupted'
        raise
    finally:
        # Only hard-coded stage names and bounded integer metrics can leave this module.
        durations = {k: v for k, v in measurement.durations.items() if k in STAGES and type(v) is int and 0 <= v <= 900000}
        calls = {k: v for k, v in measurement.calls.items() if k in STAGES and type(v) is int and 1 <= v <= 100}
        _emit('analysis_summary', outcome=measurement.outcome if measurement.outcome in STATUSES else 'unknown',
              consumer_ms=_elapsed(start), stages_ms=durations, stage_calls=calls,
              **({'enqueue_to_claim_ms': age} if age is not None else {}))
        CURRENT.reset(token)


@contextmanager
def stage(name):
    if name not in STAGES:
        raise ValueError('Unknown timing stage')
    measurement = CURRENT.get()
    if measurement is None:
        yield
        return
    start = time.monotonic()
    outcome = 'failed'
    _emit('stage_started', stage=name)
    try:
        yield
        outcome = 'completed'
    finally:
        elapsed = _elapsed(start)
        measurement.durations[name] = min(900000, measurement.durations.get(name, 0) + elapsed)
        measurement.calls[name] = measurement.calls.get(name, 0) + 1
        _emit('stage_finished', stage=name, duration_ms=elapsed, outcome=outcome)
