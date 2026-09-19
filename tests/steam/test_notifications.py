from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import pytest
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.methods import SendMessage

from drova_bot.game_updates.models import EventPage, GameFeed, SteamEvent, SteamGame
from drova_bot.game_updates.renderers import render_digest
from drova_bot.game_updates.service import GameUpdatesService
from drova_bot.game_updates.storage import NotificationStore
from drova_bot.game_updates.worker import NotificationWorker
from drova_bot.storage import (
    TokenEncryptor,
    create_database_engine,
    create_schema,
    make_session_factory,
)
from drova_bot.storage.repositories import ChatProfileRepository
from drova_bot.telegram.callbacks import CallbackSpec, parse_callback_data
from drova_bot.telegram.routers.core import game_updates_command
from tests.test_handlers import FakeMessage

NOW = datetime(2026, 9, 7, 9, tzinfo=UTC)
STREAM = "00000000-0000-0000-0000-000000000001"


def event(seq: int, *, appid: int = 730, minute: int = 10) -> SteamEvent:
    return SteamEvent(
        stream_id=STREAM,
        seq=seq,
        appid=appid,
        title="Counter-Strike & 2",
        previous_buildid=str(seq),
        buildid=str(seq + 1),
        observed_at=NOW + timedelta(minutes=minute),
    )


def page(*events: SteamEvent) -> EventPage:
    return EventPage(
        events=list(events), next_cursor=f"{STREAM}:{max(e.seq for e in events)}", has_more=False
    )


@pytest.fixture
async def store(tmp_path: Path):  # type: ignore[no-untyped-def]
    engine = create_database_engine(f"sqlite+aiosqlite:///{tmp_path / 'bot.sqlite'}")
    await create_schema(engine)
    factory = make_session_factory(engine)
    async with factory.begin() as session:
        repo = ChatProfileRepository(session, TokenEncryptor(TokenEncryptor.generate_key()))
        await repo.connect_token(10001, drova_user_id="owner", proxy_token="test-secret")
    value = NotificationStore(factory)
    await value.replace_feed(
        GameFeed(
            games=[SteamGame(appid=730, title="CS2"), SteamGame(appid=570, title="Dota")],
            catalog_updated_at=NOW,
            checked_at=NOW,
        ),
        NOW,
    )
    yield value
    await engine.dispose()


async def test_subscription_ingestion_restart_cursor_and_hour_boundaries(
    store: NotificationStore,
) -> None:
    await store.set_mode(10001, "all", NOW)
    await store.ingest(page(event(1, minute=-1), event(2), event(3, minute=40)))
    assert len(await store.pending(10001)) == 2
    assert await store.cursor() == f"{STREAM}:3"
    await store.ingest(page(event(1, minute=-1), event(2), event(3, minute=40)))
    assert len(await store.pending(10001)) == 2
    assert await store.prepare(10001, NOW + timedelta(minutes=59)) == []
    jobs = await store.prepare(10001, NOW + timedelta(hours=1))
    assert len(jobs) == 1
    assert "обновлений: 2" in jobs[0].text
    await store.complete(jobs[0].id)
    assert await store.pending(10001) == []
    assert await store.prepare(10001, NOW + timedelta(hours=2)) == []
    # Persisted cursor and completed state survive a new repository instance.
    restarted = NotificationStore(store.session_factory)
    assert await restarted.cursor() == f"{STREAM}:3"
    assert await restarted.prepare(10001, NOW + timedelta(hours=3)) == []


async def test_selected_modes_new_games_cancel_and_logout(store: NotificationStore) -> None:
    await store.select(10001, 730, True, NOW)
    await store.set_mode(10001, "selected", NOW)
    await store.ingest(page(event(1), event(2, appid=570)))
    assert len(await store.pending(10001)) == 1
    await store.set_mode(10001, "off", NOW + timedelta(minutes=15))
    assert await store.pending(10001) == []
    assert "steam:730" in (await store.settings(10001)).selected
    await store.set_mode(10001, "all", NOW + timedelta(minutes=20))
    await store.ingest(page(event(3, appid=123, minute=30)))
    assert len(await store.pending(10001)) == 1  # all includes future catalog games
    await store.reset(10001)
    assert (await store.settings(10001)).mode == "off"
    assert (await store.settings(10001)).selected == {}
    assert await store.pending(10001) == []


async def test_removing_one_game_rebuilds_unsent_parts_only(store: NotificationStore) -> None:
    for appid in [730, 570]:
        await store.select(10001, appid, True, NOW)
    await store.set_mode(10001, "selected", NOW)
    await store.ingest(page(event(1), event(2, appid=570)))
    jobs = await store.prepare(10001, NOW + timedelta(hours=1))
    assert len(jobs) == 1
    await store.select(10001, 730, False, NOW + timedelta(hours=1))
    jobs = await store.prepare(10001, NOW + timedelta(hours=1))
    assert len(jobs) == 1
    assert "/730" not in jobs[0].text and "/570" in jobs[0].text


def test_digest_exact_fixture_and_splitting() -> None:
    parts = render_digest([event(1), event(2, minute=40)], "Asia/Yekaterinburg")
    expected = (
        (Path(__file__).resolve().parents[2] / "specs/v2/fixtures/ui/steam-digest.html")
        .read_text()
        .rstrip("\n")
    )
    assert parts == [expected]
    many = [event(n, appid=n).model_copy(update={"title": "A<&" * 200}) for n in range(1, 100)]
    parts = render_digest(many, "UTC")
    assert len(parts) > 1
    assert all(len(p) <= 3900 for p in parts)
    assert all(p.count("<a ") == p.count("</a>") for p in parts)


async def test_panel_auth_search_callbacks_and_no_secret_payloads(store: NotificationStore) -> None:
    service = GameUpdatesService(store, enabled=True, clock=lambda: NOW)
    assert "подключ" in (await service.panel(999)).text.lower()
    assert "Выключено" in (await service.panel(10001)).text
    rendered = await service.panel(10001, search="dOtA")
    assert rendered.keyboard is not None
    assert any("Dota" in b.text for row in rendered.keyboard.rows for b in row)
    assert not any("CS2" in b.text for row in rendered.keyboard.rows for b in row)
    for action, kwargs in [
        ("game_updates_mode", {"control": "selected"}),
        ("game_updates_add", {"product_id": "570"}),
        ("game_updates_remove", {"product_id": "570"}),
        ("game_updates_page", {"page": 99}),
    ]:
        callback = CallbackSpec(action=action, **kwargs)  # type: ignore[arg-type]
        assert len(callback.pack().encode()) <= 64
        await service.callback(10001, parse_callback_data(callback.pack()))
    assert (await store.settings(10001)).mode == "selected"
    assert (await store.settings(10001)).selected == {}
    disabled = GameUpdatesService(store, enabled=False, clock=lambda: NOW)
    assert "выключен" in (await disabled.panel(10001)).text.lower()


async def test_new_command_is_thin() -> None:
    class Service:
        async def game_updates(self, chat_id: int, *, search: str):  # type: ignore[no-untyped-def]
            from drova_bot.telegram.renderers import RenderedMessage

            assert chat_id == 10001 and search == "Dota"
            return RenderedMessage("panel")

    message = FakeMessage("/game_updates Dota")
    await game_updates_command(cast(Any, message), cast(Any, Service()))
    assert message.answers[0][0] == "panel"


class Sender:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.failure: Exception | None = None

    async def send(self, chat_id: int, text: str) -> None:
        self.calls.append(text)
        if self.failure:
            failure, self.failure = self.failure, None
            raise failure


async def test_delivery_retry_after_block_and_recovery(store: NotificationStore) -> None:
    await store.set_mode(10001, "all", NOW)
    await store.ingest(page(event(1)))
    sender = Sender()
    method = SendMessage(chat_id=10001, text="digest")
    sender.failure = TelegramRetryAfter(method=method, message="retry", retry_after=120)
    worker = NotificationWorker(store, cast(Any, None), sender)
    due = NOW + timedelta(hours=1)
    await worker.deliver(due)
    await worker.deliver(due + timedelta(seconds=60))
    assert len(sender.calls) == 1
    await worker.deliver(due + timedelta(seconds=120))
    assert len(sender.calls) == 2 and await store.pending(10001) == []
    await store.ingest(page(event(2, minute=80)))
    sender.failure = TelegramForbiddenError(method=method, message="blocked")
    await worker.deliver(NOW + timedelta(hours=2))
    assert (await store.settings(10001)).suspended
    await store.set_mode(10001, "all", NOW + timedelta(hours=3))
    assert not (await store.settings(10001)).suspended
    assert await store.pending(10001) == []


async def test_ingestion_rollback_does_not_advance_cursor(
    store: NotificationStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy.ext.asyncio import AsyncSession

    await store.set_mode(10001, "all", NOW)
    original = AsyncSession.flush

    async def fail_flush(self: AsyncSession, *args: Any, **kwargs: Any) -> None:
        raise RuntimeError("simulated write failure")

    monkeypatch.setattr(AsyncSession, "flush", fail_flush)
    with pytest.raises(RuntimeError):
        await store.ingest(page(event(1)))
    monkeypatch.setattr(AsyncSession, "flush", original)
    assert await store.cursor() is None
    assert await store.pending(10001) == []
    await store.ingest(page(event(1)))
    assert len(await store.pending(10001)) == 1


async def test_offline_watcher_still_delivers_accepted_events(store: NotificationStore) -> None:
    from drova_bot.game_updates.client import WatcherUnavailable

    class Client:
        async def games(self) -> GameFeed:
            raise WatcherUnavailable()

        async def events(self, cursor: str | None) -> EventPage:
            raise WatcherUnavailable()

    await store.set_mode(10001, "all", NOW)
    await store.ingest(page(event(1)))
    sender = Sender()
    worker = NotificationWorker(
        store, cast(Any, Client()), sender, clock=lambda: NOW + timedelta(hours=5)
    )
    await worker.tick()
    assert len(sender.calls) == 1
    assert await store.pending(10001) == []


async def test_logout_clears_subscription_and_queue_through_real_bot_service(
    store: NotificationStore,
) -> None:
    from drova_bot.application.services import BotService
    from drova_bot.storage.uow import StorageUnitOfWorkFactory

    updates = GameUpdatesService(store, enabled=True)
    service = BotService(
        uow_factory=StorageUnitOfWorkFactory(
            store.session_factory, TokenEncryptor(TokenEncryptor.generate_key())
        ),
        client_factory=cast(Any, None),
        game_updates_service=updates,
    )
    await store.set_mode(10001, "all", NOW)
    await store.ingest(page(event(1)))
    await store.prepare(10001, NOW + timedelta(hours=1))
    await service.logout(10001)
    assert await store.profile(10001) is None
    assert await store.pending(10001) == []
    assert (await store.settings(10001)).mode == "off"


async def test_partial_delivery_does_not_repeat_successful_parts(store: NotificationStore) -> None:
    await store.set_mode(10001, "all", NOW)
    many = [
        event(n, appid=n).model_copy(update={"title": f"Game {n:03} " + "long " * 30})
        for n in range(1, 61)
    ]
    await store.ingest(page(*many))
    due = NOW + timedelta(hours=1)
    jobs = await store.prepare(10001, due)
    assert len(jobs) > 1
    first = jobs[0].text
    await store.complete(jobs[0].id)
    sender = Sender()
    worker = NotificationWorker(NotificationStore(store.session_factory), cast(Any, None), sender)
    await worker.deliver(due)
    assert first not in sender.calls
    assert len(sender.calls) == len(jobs) - 1
    assert await store.pending(10001) == []


async def test_callback_auth_and_pagination_bounds(store: NotificationStore) -> None:
    service = GameUpdatesService(store, enabled=True, clock=lambda: NOW)
    for action in [
        "game_updates",
        "game_updates_mode",
        "game_updates_add",
        "game_updates_remove",
        "game_updates_page",
    ]:
        reply = await service.callback(
            999,
            parse_callback_data(
                CallbackSpec(action=action, control="all", product_id="730", page=2).pack()
            ),
        )
        assert "подключ" in reply.text.lower()
        assert (await store.settings(999)).mode == "off"
    await store.replace_feed(
        GameFeed(games=[SteamGame(appid=n, title=f"Game {n:03}") for n in range(1, 24)]), NOW
    )
    first = await service.panel(10001, search="Game")
    last = await service.callback(
        10001, parse_callback_data(CallbackSpec(action="game_updates_page", page=1000).pack())
    )
    assert "Страница 1/3" in first.text and "Страница 3/3" in last.text
    assert first.keyboard and last.keyboard
    assert sum("Game " in b.text for row in first.keyboard.rows for b in row) == 10
    assert sum("Game " in b.text for row in last.keyboard.rows for b in row) == 3


async def test_logout_waits_for_inflight_ingestion_transaction(store: NotificationStore) -> None:
    import asyncio

    from drova_bot.application.services import BotService
    from drova_bot.storage.uow import StorageUnitOfWorkFactory

    service = BotService(
        uow_factory=StorageUnitOfWorkFactory(
            store.session_factory, TokenEncryptor(TokenEncryptor.generate_key())
        ),
        client_factory=cast(Any, None),
        game_updates_service=GameUpdatesService(store, enabled=True),
    )
    async with store.transaction_lock:
        task = asyncio.create_task(service.logout(10001))
        await asyncio.sleep(0.02)
        assert not task.done()
    await task


async def test_stream_reset_recovers_without_repeating_delivered_events(
    store: NotificationStore,
) -> None:
    from drova_bot.steam_watcher.storage import CursorConflict

    new_stream = "00000000-0000-0000-0000-000000000002"
    await store.set_mode(10001, "all", NOW)
    await store.ingest(page(event(1)))
    old = await store.prepare(10001, NOW + timedelta(hours=1))
    await store.complete(old[0].id)
    fresh_event = event(1, minute=80).model_copy(update={"stream_id": new_stream})

    class Client:
        async def games(self) -> GameFeed:
            return GameFeed(games=[])

        async def events(self, cursor: str | None) -> EventPage:
            if cursor == f"{STREAM}:1":
                raise CursorConflict(f"{new_stream}:0")
            assert cursor == f"{new_stream}:0"
            return EventPage(events=[fresh_event], next_cursor=f"{new_stream}:1", has_more=False)

    sender = Sender()
    worker = NotificationWorker(
        store, cast(Any, Client()), sender, clock=lambda: NOW + timedelta(hours=2)
    )
    await worker.tick()
    assert len(sender.calls) == 1
    assert await store.cursor() == f"{new_stream}:1"
    assert await store.pending(10001) == []


async def test_digest_html_fallback_preserves_links() -> None:
    from aiogram.exceptions import TelegramBadRequest

    from drova_bot.game_updates.worker import TelegramDigestSender

    class Bot:
        calls: list[tuple[str, dict[str, Any]]]

        def __init__(self) -> None:
            self.calls = []

        async def send_message(self, chat_id: int, text: str, **kwargs: Any) -> None:
            self.calls.append((text, kwargs))
            if kwargs["parse_mode"] == "HTML":
                raise TelegramBadRequest(
                    method=SendMessage(chat_id=chat_id, text=text), message="can't parse entities"
                )

    bot = Bot()
    await TelegramDigestSender(cast(Any, bot)).send(10001, render_digest([event(1)], "UTC")[0])
    assert len(bot.calls) == 2
    plain, options = bot.calls[1]
    assert "https://store.steampowered.com/news/app/730" in plain
    assert "Counter-Strike & 2" in plain and "<a" not in plain and "<b>" not in plain
    assert options["parse_mode"] is None


def test_digest_limits_include_astral_unicode() -> None:
    many = [event(n, appid=n).model_copy(update={"title": "😀" * 160}) for n in range(1, 100)]
    parts = render_digest(many, "UTC")
    assert all(len(text.encode("utf-16-le")) // 2 <= 3900 for text in parts)
