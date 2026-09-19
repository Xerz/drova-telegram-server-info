"""Watcher settings deliberately do not load the bot's .env or private credentials."""

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class WatcherSettings(BaseSettings):
    update_providers: str = Field(default="steam", alias="UPDATE_PROVIDERS")

    @field_validator("update_providers")
    @classmethod
    def providers_valid(cls, value: str) -> str:
        from drova_bot.game_updates.models import PROVIDERS

        values = {p.strip() for p in value.split(",")}
        if not values or not values <= PROVIDERS:
            raise ValueError("invalid UPDATE_PROVIDERS")
        return ",".join(sorted(values))

    api_token: SecretStr = Field(default=SecretStr(""), alias="STEAM_WATCHER_TOKEN")
    database_url: str = Field(
        default="sqlite+aiosqlite:////data/steam_watcher.sqlite3", alias="STEAM_DATABASE_URL"
    )
    steamcmd_path: str = Field(default="/opt/steamcmd/steamcmd.sh", alias="STEAMCMD_PATH")
    command_timeout: float = Field(default=30, gt=0, alias="STEAM_COMMAND_TIMEOUT")
    startup_timeout: float = Field(default=180, gt=0, alias="STEAM_STARTUP_TIMEOUT")
    poll_seconds: float = Field(default=300, ge=1, alias="STEAM_POLL_SECONDS")
    catalog_seconds: float = Field(default=3600, ge=1, alias="STEAM_CATALOG_SECONDS")
    api_host: str = Field(default="0.0.0.0", alias="STEAM_API_HOST")
    api_port: int = Field(default=8080, ge=1, le=65535, alias="STEAM_API_PORT")
    drova_base_url: str = Field(default="https://services.drova.io", alias="DROVA_BASE_URL")
    http_proxy: str | None = Field(default=None, alias="HTTP_PROXY")
    https_proxy: str | None = Field(default=None, alias="HTTPS_PROXY")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    model_config = SettingsConfigDict(extra="ignore", populate_by_name=True, validate_default=True)

    @field_validator("api_token")
    @classmethod
    def nonempty_token(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().strip():
            raise ValueError("STEAM_WATCHER_TOKEN is required")
        return value
