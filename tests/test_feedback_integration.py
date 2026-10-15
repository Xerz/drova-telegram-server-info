from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from typing import Any, cast

import pytest
from alembic import command
from alembic.config import Config

from drova_bot.app import BOT_COMMANDS, build_runtime
from drova_bot.config import Settings
from drova_bot.storage import TokenEncryptor, create_schema, make_session_factory, run_migrations
from drova_bot.storage.repositories import ChatProfileRepository
from drova_bot.telegram.callbacks import CallbackSpec, parse_callback_data
from drova_bot.telegram.renderers import RenderedMessage, render_help
from drova_bot.telegram.routers.core import callback_query, feedback_notifications_command
from tests.test_handlers import FakeCallback, FakeMessage, FakeService


class Service(FakeService):
    async def feedback_notifications(self, chat_id: int) -> RenderedMessage:
        self.calls.append(("feedback_notifications", (chat_id,), {}))
        return RenderedMessage("feedback")


@pytest.mark.asyncio
async def test_command_and_both_callbacks_use_existing_delivery() -> None:
    service = Service()
    message = FakeMessage("/feedback_notifications")
    await feedback_notifications_command(cast(Any, message), cast(Any, service))
    assert service.calls == [("feedback_notifications", (10001,), {})]
    for mode in ("on", "off"):
        packed = CallbackSpec(action="feedback_notifications_mode", control=mode).pack()
        assert len(packed.encode()) <= 64
        assert parse_callback_data(packed).control == mode
        callback = FakeCallback(packed)
        await callback_query(cast(Any, callback), cast(Any, service))
        assert len(callback.message.edits) == 1
        assert len(callback.answers) == 1


def test_command_is_appended_and_documented() -> None:
    commands = [c.command for c in BOT_COMMANDS]
    assert commands[:5] == ["sessions", "current", "account_menu", "usage", "help"]
    assert commands[-1] == "feedback_notifications"
    assert len(commands) == len(set(commands))
    assert "/feedback_notifications" in render_help().text


def test_migration_preserves_populated_previous_database(tmp_path: Path) -> None:
    path = tmp_path / "old.sqlite"
    config = Config()
    config.set_main_option("script_location", "src/drova_bot/storage/migrations")
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{path}")
    command.upgrade(config, "0003_platform_updates")
    with sqlite3.connect(path) as db:
        db.execute(
            "INSERT INTO chat_profiles VALUES (101, 'owner', NULL, NULL, 5, "
            "'Asia/Yekaterinburg', '2026-01-01', '2026-01-01')"
        )
    run_migrations(f"sqlite+aiosqlite:///{path}")
    run_migrations(f"sqlite+aiosqlite:///{path}")
    with sqlite3.connect(path) as db:
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"feedback_subscriptions", "feedback_seen", "feedback_parts"} <= tables
        assert db.execute(
            "SELECT drova_user_id FROM chat_profiles WHERE telegram_chat_id=101"
        ).fetchone() == ("owner",)
        assert db.execute("SELECT count(*) FROM feedback_subscriptions").fetchone() == (0,)


@pytest.mark.asyncio
async def test_runtime_wires_feedback_without_game_watcher_and_closes(tmp_path: Path) -> None:
    url = f"sqlite+aiosqlite:///{tmp_path / 'runtime.sqlite'}"
    values: dict[str, Any] = {
        "_env_file": None,
        "telegram_bot_token": "123456:test",
        "bot_secret_key": TokenEncryptor.generate_key(),
        "database_url": url,
        "game_updates_enabled": False,
    }
    runtime = build_runtime(Settings(**values))
    try:
        assert runtime.feedback_worker is not None
        assert runtime.notification_worker is None
        await create_schema(runtime.engine)
        service = runtime.dispatcher["bot_service"]
        assert "/token" in (await service.feedback_notifications(101)).text
        # Use the runtime's own encryptor so credentials and callback settings share real storage.
        async with make_session_factory(runtime.engine).begin() as session:
            await ChatProfileRepository(
                session, runtime.feedback_worker.store.encryptor
            ).connect_token(101, drova_user_id="owner-1", proxy_token="synthetic")
        callback = parse_callback_data(
            CallbackSpec(action="feedback_notifications_mode", control="on").pack()
        )
        assert "включены" in (await service.handle_callback(101, callback)).text
        generation = (await runtime.feedback_worker.store.settings(101)).generation
        await service.handle_callback(101, callback)
        assert (await runtime.feedback_worker.store.settings(101)).generation == generation
        callback = parse_callback_data(
            CallbackSpec(action="feedback_notifications_mode", control="off").pack()
        )
        assert "выключены" in (await service.handle_callback(101, callback)).text
        runtime.start_background()
        await asyncio.sleep(0)
        assert runtime.feedback_task is not None and not runtime.feedback_task.done()
    finally:
        await runtime.close()
    assert runtime.feedback_task.done()
    assert not runtime.feedback_worker.tasks
