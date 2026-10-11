"""Launch the local booth from any working directory without printing credentials."""

import os
from pathlib import Path

import uvicorn

os.chdir(Path(__file__).resolve().parents[1])

if __name__ == "__main__":
    uvicorn.run("palm_backend.app:create_app", factory=True, host="127.0.0.1", port=8000)
