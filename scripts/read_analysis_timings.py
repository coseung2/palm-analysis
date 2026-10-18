"""Read timing-only diagnostics locally on the VM; no credentials are required."""
import argparse
import json
from collections import deque
from datetime import datetime
from pathlib import Path

from palm_backend.timing import STAGES, STATUSES

ROOT = Path(__file__).resolve().parents[1]


def public_event(row):
    if not isinstance(row, dict) or not isinstance(row.get('at'), str):
        return None
    try:
        timestamp = datetime.fromisoformat(row['at'])
        if timestamp.tzinfo is None:
            return None
    except ValueError:
        return None
    event = row.get('event')
    result = {'event':event, 'at':timestamp.isoformat()}
    def bounded(value, upper=900000):
        return type(value) is int and 0 <= value <= upper
    if event == 'analysis_summary':
        result['outcome'] = row.get('outcome') if row.get('outcome') in STATUSES else 'unknown'
        for key in ('consumer_ms','enqueue_to_claim_ms'):
            if bounded(row.get(key)):
                result[key] = row[key]
        for key in ('stages_ms','stage_calls'):
            values = row.get(key)
            result[key] = {name:value for name,value in values.items() if name in STAGES and bounded(value,100 if key=='stage_calls' else 900000)} if isinstance(values,dict) else {}
    elif event in ('stage_started','stage_finished'):
        if row.get('stage') not in STAGES:
            return None
        result['stage'] = row['stage']
        if event == 'stage_finished':
            if not bounded(row.get('duration_ms')) or row.get('outcome') not in ('completed','failed'):
                return None
            result.update(duration_ms=row['duration_ms'], outcome=row['outcome'])
    elif event == 'analysis_started':
        if bounded(row.get('enqueue_to_claim_ms')):
            result['enqueue_to_claim_ms'] = row['enqueue_to_claim_ms']
    else:
        return None
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--limit', type=int, choices=range(1,21), default=5)
    args = parser.parse_args()
    path = ROOT / 'data/analysis-timing.jsonl'
    if not path.exists():
        print(json.dumps({'summaries':[], 'latest_event':None, 'status':'no_timed_analysis_yet'}))
        return
    with path.open(encoding='utf-8') as stream:
        lines = deque(stream,maxlen=1000)
    events = []
    for line in lines:
        if len(line) > 8192:
            continue
        try:
            safe = public_event(json.loads(line))
            if safe:
                events.append(safe)
        except (ValueError, TypeError):
            continue
    summaries = [row for row in events if row['event']=='analysis_summary'][-args.limit:]
    print(json.dumps({'summaries':summaries,'latest_event':events[-1] if events else None},indent=2))


if __name__ == '__main__':
    main()
