"""Application settings."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration sourced from environment variables."""

    telegram_bot_token: str | None = Field(default=None, alias="TELEGRAM_BOT_TOKEN")
    bot_secret_key: str | None = Field(default=None, alias="BOT_SECRET_KEY")
    database_url: str = Field(
        default="sqlite+aiosqlite:///data/drova_bot.sqlite3",
        alias="DATABASE_URL",
    )
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    timezone: str = Field(default="Asia/Yekaterinburg", alias="TZ")
    http_proxy: str | None = Field(default=None, alias="HTTP_PROXY")
    https_proxy: str | None = Field(default=None, alias="HTTPS_PROXY")
    drova_base_url: str = Field(
        default="https://services.drova.io",
        alias="DROVA_BASE_URL",
    )
    export_row_limit: int = Field(default=50_000, alias="EXPORT_ROW_LIMIT")
    export_timeout_seconds: int = Field(default=120, alias="EXPORT_TIMEOUT_SECONDS")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    def require_runtime_secrets(self) -> None:
        """Fail fast when production startup lacks mandatory secrets."""
        missing = []
        if not self.telegram_bot_token:
            missing.append("TELEGRAM_BOT_TOKEN")
        if not self.bot_secret_key:
            missing.append("BOT_SECRET_KEY")
        if missing:
            joined = ", ".join(missing)
            raise RuntimeError(f"Missing required runtime environment: {joined}")
