"""Initialize local demo settings without printing secrets or overwriting an existing .env."""

import secrets
from pathlib import Path

root = Path(__file__).resolve().parents[1]
template = (root / ".env.example").read_text(encoding="utf-8")
content = template.replace(
    "PALM_OPERATOR_KEY=\n", f"PALM_OPERATOR_KEY={secrets.token_urlsafe(32)}\n", 1
)
try:
    with (root / ".env").open("x", encoding="utf-8") as file:
        file.write(content)
except FileExistsError:
    print("Existing .env preserved; no changes made.")
else:
    print("Local demo .env created; operator key is stored locally and was not printed.")
