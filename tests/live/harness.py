"""Shared helpers for opt-in live Drova API contract tests."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from drova_bot.drova.client import DrovaClient

ROOT = Path(__file__).resolve().parents[2]
ENV_SPECING_PATH = ROOT / ".env.specing"
DEFAULT_DROVA_BASE_URL = "https://services.drova.io"


class MissingLiveEnvironment(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class LiveSettings:
    drova_proxy_token: str
    test_station_uuid: str | None = None
    test_product_uuid: str | None = None
    telegram_bot_token: str | None = None
    http_proxy: str | None = None
    https_proxy: str | None = None
    drova_base_url: str = DEFAULT_DROVA_BASE_URL


@dataclass(frozen=True, slots=True)
class LiveClientConfig:
    proxy_token: str
    base_url: str
    proxy: str | None


def load_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    result: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key.strip()] = value.strip().strip("'\"")
    return result


def load_live_settings(path: Path = ENV_SPECING_PATH) -> LiveSettings:
    env = load_env_file(path)
    proxy_token = _optional(env.get("DROVA_PROXY_TOKEN"))
    if proxy_token is None:
        raise MissingLiveEnvironment("DROVA_PROXY_TOKEN is required in .env.specing")
    return LiveSettings(
        drova_proxy_token=proxy_token,
        test_station_uuid=_optional(env.get("TEST_STATION_UUID")),
        test_product_uuid=_optional(env.get("TEST_PRODUCT_UUID")),
        telegram_bot_token=_optional(env.get("TELEGRAM_BOT_TOKEN")),
        http_proxy=_optional(env.get("HTTP_PROXY")),
        https_proxy=_optional(env.get("HTTPS_PROXY")),
        drova_base_url=_optional(env.get("DROVA_BASE_URL")) or DEFAULT_DROVA_BASE_URL,
    )


def live_client_config(settings: LiveSettings) -> LiveClientConfig:
    return LiveClientConfig(
        proxy_token=settings.drova_proxy_token,
        base_url=settings.drova_base_url,
        proxy=settings.https_proxy or settings.http_proxy,
    )


def build_live_client(settings: LiveSettings) -> DrovaClient:
    client_config = live_client_config(settings)
    return DrovaClient(
        proxy_token=client_config.proxy_token,
        base_url=client_config.base_url,
        proxy=client_config.proxy,
    )


def live_skip_reason(
    *,
    is_live: bool,
    is_live_write: bool,
    run_live: bool,
    run_live_write: bool,
) -> str | None:
    if is_live_write and not run_live:
        return "live write contract tests require --run-live"
    if is_live and not run_live:
        return "live contract tests require --run-live"
    if is_live_write and not run_live_write:
        return "live write contract tests require --run-live-write"
    return None


def _optional(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None
