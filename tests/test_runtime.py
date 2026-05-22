from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, cast

import pytest
from aiogram.types import Message, TelegramObject

from drova_bot import app
from drova_bot.config import Settings
from drova_bot.storage import TokenEncryptor, run_migrations
from drova_bot.telegram.middleware import RequestContextMiddleware, hash_chat_id


def test_build_runtime_requires_secrets() -> None:
    settings = _settings(telegram_bot_token=None, bot_secret_key=None)

    with pytest.raises(RuntimeError, match="TELEGRAM_BOT_TOKEN, BOT_SECRET_KEY"):
        app.build_runtime(settings)


def test_migration_runner_creates_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "drova.sqlite3"

    run_migrations(f"sqlite+aiosqlite:///{db_path}")

    with sqlite3.connect(db_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "select name from sqlite_master where type = 'table'",
            )
        }
    assert {"chat_profiles", "station_cache", "product_cache", "export_jobs"} <= tables
    assert "alembic_version" in tables


@pytest.mark.asyncio
async def test_build_runtime_wires_service_and_router(tmp_path: Path) -> None:
    db_path = tmp_path / "drova.sqlite3"
    settings = _settings(
        telegram_bot_token="123456:test-token",
        bot_secret_key=TokenEncryptor.generate_key(),
        database_url=f"sqlite+aiosqlite:///{db_path}",
    )

    runtime = app.build_runtime(settings)
    try:
        assert "bot_service" in runtime.dispatcher.workflow_data
        assert runtime.dispatcher.sub_routers[0].name == "drova_bot_core"
    finally:
        await runtime.close()


@pytest.mark.asyncio
async def test_register_bot_commands_uses_runtime_command_list() -> None:
    fake_bot = FakeBot()

    await app.register_bot_commands(cast(Any, fake_bot))

    assert [command.command for command in fake_bot.commands] == [
        "start",
        "help",
        "token",
        "logout",
        "station",
        "station_all",
        "station_manage",
        "limit",
        "sessions",
        "sessions_short",
        "current",
        "account_menu",
        "account",
        "usage",
        "disabled",
        "stations",
        "games",
        "desktop_on",
        "desktop_off",
        "updates_on",
        "updates_off",
        "server_source",
        "server_description",
        "promocode",
        "promocodes",
        "export_sessions",
        "export_sessions_csv",
        "export_products",
        "export_product_time",
    ]


@pytest.mark.asyncio
async def test_run_polling_registers_commands_and_closes_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_runtime = FakeRuntime()
    calls: list[str] = []

    def fake_build_runtime(settings: Settings) -> FakeRuntime:
        calls.append(settings.timezone)
        return fake_runtime

    async def fake_register_bot_commands(bot: object) -> None:
        assert bot is fake_runtime.bot
        calls.append("commands")

    monkeypatch.setattr(app, "build_runtime", fake_build_runtime)
    monkeypatch.setattr(app, "register_bot_commands", fake_register_bot_commands)

    await app.run_polling(_settings(telegram_bot_token="123456:test", bot_secret_key="unused"))

    assert calls == ["Asia/Yekaterinburg", "commands"]
    assert fake_runtime.dispatcher.started_with == {
        "bot": fake_runtime.bot,
        "allowed_updates": ["message", "callback_query"],
    }
    assert fake_runtime.closed


@pytest.mark.asyncio
async def test_request_context_middleware_adds_non_sensitive_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_logger = FakeLogger()
    monkeypatch.setattr("drova_bot.telegram.middleware.logger", fake_logger)
    data: dict[str, Any] = {}
    message = Message.model_validate(
        {
            "message_id": 1,
            "date": 0,
            "chat": {"id": 10001, "type": "private"},
            "text": "/start",
        },
    )

    async def handler(event: TelegramObject, handler_data: dict[str, Any]) -> str:
        assert event is message
        assert handler_data["chat_id_hash"] == hash_chat_id(10001)
        assert handler_data["request_id"]
        return "ok"

    result = await RequestContextMiddleware()(handler, message, data)

    assert result == "ok"
    assert data["chat_id_hash"] == hash_chat_id(10001)
    assert "10001" not in repr(fake_logger.records)


def test_deployment_files_keep_secrets_out_of_image() -> None:
    root = Path(__file__).resolve().parents[1]
    dockerfile = (root / "Dockerfile").read_text(encoding="utf-8")
    compose = (root / "docker-compose.yml").read_text(encoding="utf-8")

    assert "FROM python:3.12-slim" in dockerfile
    assert "uv sync --frozen --no-dev" in dockerfile
    assert "python -m drova_bot.tools.healthcheck" in dockerfile
    assert "env_file:" in compose
    assert "TELEGRAM_BOT_TOKEN" not in dockerfile
    assert "BOT_SECRET_KEY" not in dockerfile


class FakeBot:
    def __init__(self) -> None:
        self.commands: list[Any] = []

    async def set_my_commands(self, commands: list[Any]) -> None:
        self.commands = commands


class FakeSession:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class FakeDispatcher:
    def __init__(self) -> None:
        self.started_with: dict[str, Any] | None = None

    def resolve_used_update_types(self) -> list[str]:
        return ["message", "callback_query"]

    async def start_polling(self, bot: object, *, allowed_updates: list[str]) -> None:
        self.started_with = {"bot": bot, "allowed_updates": allowed_updates}


class FakeRuntime:
    def __init__(self) -> None:
        self.bot = object()
        self.dispatcher = FakeDispatcher()
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class FakeLogger:
    def __init__(self) -> None:
        self.records: list[tuple[str, dict[str, Any]]] = []

    def bind(self, **kwargs: Any) -> FakeLogger:
        self.records.append(("bind", kwargs))
        return self

    def info(self, event: str, **kwargs: Any) -> None:
        self.records.append((event, kwargs))

    def exception(self, event: str, **kwargs: Any) -> None:
        self.records.append((event, kwargs))


def _settings(**values: object) -> Settings:
    return Settings.model_validate(values)
