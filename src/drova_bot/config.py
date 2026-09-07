"""Application settings."""

from __future__ import annotations

from pydantic import Field, SecretStr
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
    geolite_city_db: str = Field(
        default="/data/GeoLite2-City.mmdb",
        alias="GEOLITE_CITY_DB",
    )
    geolite_asn_db: str = Field(
        default="/data/GeoLite2-ASN.mmdb",
        alias="GEOLITE_ASN_DB",
    )

    game_updates_enabled: bool = Field(default=False, alias="GAME_UPDATES_ENABLED")
    steam_watcher_url: str = Field(default="http://steam-watcher:8080", alias="STEAM_WATCHER_URL")
    steam_watcher_token: SecretStr | None = Field(default=None, alias="STEAM_WATCHER_TOKEN")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    def require_runtime_secrets(self) -> None:
        """Fail fast when production startup lacks mandatory secrets."""
        missing = []
        if not self.telegram_bot_token:
            missing.append("TELEGRAM_BOT_TOKEN")
        if not self.bot_secret_key:
            missing.append("BOT_SECRET_KEY")
        if self.game_updates_enabled and (
            self.steam_watcher_token is None
            or not self.steam_watcher_token.get_secret_value().strip()
        ):
            missing.append("STEAM_WATCHER_TOKEN")
        if missing:
            joined = ", ".join(missing)
            raise RuntimeError(f"Missing required runtime environment: {joined}")
