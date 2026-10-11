from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PALM_", env_file=".env", extra="ignore", validate_assignment=True
    )

    operator_key: SecretStr
    database_path: Path = Path("data/palm.sqlite3")
    analysis_mode: Literal["demo", "claude", "ocx"] = "demo"
    public_sessions: bool = False
    public_starts_per_minute: int = Field(default=6, ge=1, le=60)
    session_ttl_seconds: int = Field(default=3600, ge=60, le=86400)
    analysis_timeout_seconds: int = Field(default=45, ge=1, le=120)
    max_upload_bytes: int = Field(default=5 * 1024 * 1024, ge=1024, le=10 * 1024 * 1024)
    max_active_analyses: int = Field(default=2, ge=1, le=8)
    max_sessions: int = Field(default=500, ge=1, le=10000)
    cors_origins: list[str] = Field(default_factory=list)
    anthropic_api_key: SecretStr | None = None
    anthropic_model: str = "claude-opus-5-5"

    ocx_base_url: str | None = None
    ocx_api_key: SecretStr | None = None
    ocx_model: str = "gpt-6.1-sol"

    def validate_runtime(self) -> None:
        if len(self.operator_key.get_secret_value()) < 32:
            raise ValueError("PALM_OPERATOR_KEY must contain at least 32 characters")
        if "*" in self.cors_origins:
            raise ValueError("Set exact CORS origins; wildcard origins are not supported")
        if self.analysis_mode == "claude" and (
            not self.anthropic_api_key or not self.anthropic_api_key.get_secret_value()
        ):
            raise ValueError("PALM_ANTHROPIC_API_KEY is required for claude mode")
        if self.analysis_mode == "ocx":
            url = urlparse(self.ocx_base_url or "")
            if (
                url.scheme not in ("http", "https") or not url.hostname
                or url.username or url.password or url.query or url.fragment
                or url.path not in ("", "/")
            ):
                raise ValueError("PALM_OCX_BASE_URL must be an explicit OCX origin")
            if not self.ocx_api_key or not self.ocx_api_key.get_secret_value():
                raise ValueError("PALM_OCX_API_KEY is required for ocx mode")
            if not self.ocx_model.strip():
                raise ValueError("PALM_OCX_MODEL is required for ocx mode")
