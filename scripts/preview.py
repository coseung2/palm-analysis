"""Isolated local demo preview; never reads .env or sends a photo to AI."""
from pathlib import Path

import uvicorn

from palm_backend.app import create_app
from palm_backend.config import Settings

ROOT = Path(__file__).resolve().parents[1]
app = create_app(Settings(
    _env_file=None, operator_key='synthetic-preview-key-not-a-real-secret',
    database_path=ROOT / 'data/preview.sqlite3', analysis_mode='demo', public_sessions=True,
))

if __name__ == '__main__':
    uvicorn.run(app, host='127.0.0.1', port=8001)
