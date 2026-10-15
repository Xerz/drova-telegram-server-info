from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncGenerator
from dataclasses import replace
from datetime import datetime, timedelta
from html import unescape
from pathlib import Path
from typing import Any, cast

import httpx
import pytest
import respx
from aiogram import Bot as AiogramBot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.methods import SendMessage
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from drova_bot.domain.models import SessionPage
from drova_bot.drova.client import DrovaClient
from drova_bot.drova.errors import DrovaUnauthorized, DrovaUnavailable
from drova_bot.drova.models import SessionPageResponse, SessionResponse
from drova_bot.feedback_notifications.models import StaleFeedbackContext
from drova_bot.feedback_notifications.renderers import (
    client_usage,
    rating_stars,
    render_notification,
)
from drova_bot.feedback_notifications.service import FeedbackService
from drova_bot.feedback_notifications.storage import FeedbackStore
from drova_bot.feedback_notifications.tables import FeedbackPartRow, FeedbackSeenRow
from drova_bot.feedback_notifications.worker import FeedbackWorker, TelegramFeedbackSender
from drova_bot.storage import (
    TokenEncryptor,
    create_database_engine,
    create_schema,
    make_session_factory,
)
from drova_bot.storage.repositories import ChatProfileRepository

FIXTURES = Path(__file__).resolve().parents[1] / "specs/v2/fixtures"
DATA = json.loads((FIXTURES / "ui/feedback.json").read_text())
API_DATA = json.loads((FIXTURES / "api/feedback_sessions.json").read_text())
NOW = datetime.fromisoformat(DATA["now"])
SESSIONS = SessionPageResponse.parse_payload(DATA).to_domain().sessions


def notification(session: Any = None, sessions: Any = None) -> list[str]:
    return render_notification(
        session or SESSIONS[0],
        SESSIONS if sessions is None else sessions,
        DATA["stations"],
        DATA["products"],
        now=NOW,
        timezone=DATA["timezone"],
    )


@pytest.mark.parametrize("score", [1, 2, 3, 4, 5])
def test_five_star_positions(score: int) -> None:
    assert rating_stars(score) == "⭐" * score + "☆" * (5 - score)


@pytest.mark.parametrize("score", [None, 0, 6, -1, True, False, "3", 3.0, {}, []])
def test_invalid_api_scores_normalize_without_rejecting_session(score: Any) -> None:
    parsed = SessionResponse.model_validate({**API_DATA["sessions"][0], "score": score})
    assert parsed.to_domain().score is None


def test_usage_uses_full_id_overlap_and_active_time() -> None:
    usage = client_usage(SESSIONS[0], SESSIONS, now=NOW)
    assert usage is not None
    assert usage.total_seconds == (28 * 60 + 47) * 60
    assert usage.station_seconds == (2 * 60 + 47) * 60
    assert not usage.incomplete
    assert client_usage(replace(SESSIONS[0], client_id=None), SESSIONS, now=NOW) is None


def test_partial_window_is_lower_bound_and_bad_durations_add_zero() -> None:
    recent = [replace(SESSIONS[0], uuid=str(i)) for i in range(1000)]
    usage = client_usage(SESSIONS[0], recent, now=NOW)
    assert usage is not None and usage.incomplete
    assert "не менее" in notification(sessions=recent)[0]
    bad = replace(SESSIONS[0], finished_on_ms=SESSIONS[0].created_on_ms - 1000)
    bad_usage = client_usage(bad, [bad], now=NOW)
    assert bad_usage is not None and bad_usage.total_seconds == 0


def test_notification_midnight_html_and_score_only() -> None:
    text = notification()[0]
    assert "⭐⭐⭐☆☆" in text
    assert "13.10 21:50 → 14.10 00:37" in text
    assert "28 ч 47 мин" in text and "2 ч 47 мин" in text
    assert "Станция &lt;А&gt;" in text and "&lt;спасибо&gt; &amp;" in text
    assert "synthetic-client" not in text
    assert "Комментарий не оставлен" in notification(SESSIONS[-1])[0]
    assert "Оценка не указана" in notification(replace(SESSIONS[0], score=None))[0]


def test_long_comment_is_lossless_and_every_part_is_valid_html() -> None:
    comment = "<>&😀\n" * 3000
    parts = notification(replace(SESSIONS[0], score_text=comment))
    assert len(parts) > 1
    assert all(len(part.encode("utf-16-le")) // 2 <= 3500 for part in parts)
    recovered = []
    for index, part in enumerate(parts):
        body = part.split("Комментарий:\n", 1)[1] if index == 0 else part.split("\n", 1)[1]
        if index == 0:
            body = body.split("\n\n<b>Этот клиент", 1)[0]
        recovered.append(unescape(body))
        assert part.count("<b>") == part.count("</b>")
        assert part.count("<code>") == part.count("</code>")
    assert "".join(recovered) == comment


@pytest.mark.asyncio
@respx.mock
async def test_feedback_api_account_query_and_token_renewal() -> None:
    route = respx.get("https://services.drova.io/session-manager/sessions").mock(
        side_effect=[httpx.Response(401), httpx.Response(200, json=API_DATA)]
    )
    renewal = respx.post("https://services.drova.io/token-verifier/renewProxyToken").respond(
        200, json={"proxyToken": "renewed"}
    )
    saved: list[str] = []

    async def persist(token: str) -> None:
        saved.append(token)

    async with DrovaClient(proxy_token="old", token_persister=persist) as client:
        page = await client.get_sessions(merchant_id="owner-1", limit=1000)
    assert page.sessions[0].score == 3
    assert renewal.call_count == 1 and route.call_count == 2
    assert saved == ["renewed"]
    assert dict(route.calls[0].request.url.params) == {"merchant_id": "owner-1", "limit": "1000"}
    assert route.calls[0].request.headers["X-Auth-Token"] == "old"
    assert route.calls[1].request.headers["X-Auth-Token"] == "renewed"


@pytest.fixture
async def store(tmp_path: Path) -> AsyncGenerator[FeedbackStore]:
    engine = create_database_engine(f"sqlite+aiosqlite:///{tmp_path / 'feedback.sqlite'}")
    await create_schema(engine)
    factory = make_session_factory(engine)
    encryptor = TokenEncryptor(TokenEncryptor.generate_key())
    async with factory.begin() as session:
        repo = ChatProfileRepository(session, encryptor)
        await repo.connect_token(101, drova_user_id="owner-1", proxy_token="secret-1")
        await repo.connect_token(202, drova_user_id="owner-2", proxy_token="secret-2")
    yield FeedbackStore(factory, encryptor)
    await engine.dispose()


async def ingest(store: FeedbackStore, ctx: Any, messages: Any = None) -> int:
    return await store.ingest(
        ctx, {"review-1": notification()} if messages is None else messages, notification()[0], NOW
    )


@pytest.mark.asyncio
async def test_panel_auth_defaults_and_idempotent_buttons(store: FeedbackStore) -> None:
    service = FeedbackService(store)
    assert "/token" in (await service.panel(999)).text
    panel = await service.panel(101)
    assert "Сейчас: выключены" in panel.text and "Демонстрационный пример" in panel.text
    assert panel.keyboard is not None
    assert [[b.text for b in row] for row in panel.keyboard.rows] == [["Включить", "Выключить"]]
    assert "включены" in (await service.set_enabled(101, True)).text
    state = await store.settings(101)
    await service.set_enabled(101, True)
    assert (await store.settings(101)).generation == state.generation
    assert "выключены" in (await service.set_enabled(101, False)).text


@pytest.mark.asyncio
async def test_baseline_late_review_edits_restart_and_reenable(store: FeedbackStore) -> None:
    await store.set_enabled(101, True)
    ctx = await store.begin_poll(101, NOW)
    assert ctx is not None
    assert await ingest(store, ctx) == 0
    assert await store.pending(101) == []
    assert await store.begin_poll(101, NOW + timedelta(seconds=59)) is None
    ctx = await store.begin_poll(101, NOW + timedelta(seconds=60))
    assert ctx is not None
    assert await ingest(store, ctx, {"review-1": ["changed"], "late-review": ["first"]}) == 1
    reopened = FeedbackStore(store.session_factory, store.encryptor)
    assert (await reopened.pending(101))[0].text == "first"
    ctx = await reopened.begin_poll(101, NOW + timedelta(seconds=120))
    assert ctx is not None
    assert await ingest(reopened, ctx, {"late-review": ["later comment"]}) == 0
    await reopened.set_enabled(101, False)
    assert await reopened.pending(101) == []
    await reopened.set_enabled(101, True)
    ctx = await reopened.begin_poll(101, NOW + timedelta(seconds=180))
    assert ctx is not None
    assert await ingest(reopened, ctx, {"while-off": ["old"]}) == 0
    assert await reopened.pending(101) == []


@pytest.mark.asyncio
async def test_disable_and_account_changes_reject_inflight_results_and_renewals(
    store: FeedbackStore,
) -> None:
    await store.set_enabled(101, True)
    ctx = await store.begin_poll(101, NOW)
    assert ctx is not None
    await store.set_enabled(101, False)
    assert await ingest(store, ctx) == 0
    with pytest.raises(StaleFeedbackContext):
        await store.persist_token(ctx, "stale-token")
    await store.set_enabled(101, True)
    ctx = await store.begin_poll(101, NOW + timedelta(seconds=60))
    assert ctx is not None
    async with store.session_factory.begin() as session:
        await ChatProfileRepository(session, store.encryptor).connect_token(
            101, drova_user_id="owner-2", proxy_token="new-account"
        )
    assert not (await store.settings(101)).enabled
    assert await ingest(store, ctx) == 0
    with pytest.raises(StaleFeedbackContext):
        await store.persist_token(ctx, "old-owner-renewal")


@pytest.mark.asyncio
async def test_same_owner_credentials_preserve_baseline_and_queue_and_logout_clears(
    store: FeedbackStore,
) -> None:
    await store.set_enabled(101, True)
    ctx = await store.begin_poll(101, NOW)
    assert ctx is not None
    await ingest(store, ctx, {})
    ctx = await store.begin_poll(101, NOW + timedelta(seconds=60))
    assert ctx is not None
    await ingest(store, ctx)
    await store.suspend(101, "auth", ctx)
    async with store.session_factory.begin() as session:
        await ChatProfileRepository(session, store.encryptor).connect_token(
            101, drova_user_id="owner-1", proxy_token="replacement"
        )
    state = await store.settings(101)
    assert state.enabled and state.initialized and state.suspended is None
    assert len(await store.pending(101)) == 1
    with pytest.raises(StaleFeedbackContext):
        await store.persist_token(ctx, "stale-same-owner")
    async with store.session_factory.begin() as session:
        await ChatProfileRepository(session, store.encryptor).logout(101)
    assert not (await store.settings(101)).enabled
    assert await store.pending(101) == []
    async with store.session_factory() as session:
        assert (await session.scalars(select(FeedbackSeenRow))).all() == []
        assert (await session.scalars(select(FeedbackPartRow))).all() == []


class Client:
    def __init__(self) -> None:
        self.rows = SESSIONS
        self.calls: list[Any] = []
        self.failure = False
        self.closed = 0
        self.gate: asyncio.Event | None = None

    async def get_sessions(self, **kwargs: Any) -> SessionPage:
        self.calls.append(kwargs)
        if self.gate:
            await self.gate.wait()
        if self.failure:
            raise DrovaUnavailable("synthetic")
        return SessionPage(sessions=self.rows)

    async def get_servers(self, _: str) -> list[Any]:
        return []

    async def get_products_full(self) -> list[Any]:
        return []

    async def aclose(self) -> None:
        self.closed += 1


class Factory:
    def __init__(self, client: Client) -> None:
        self.client = client
        self.tokens: list[str] = []

    def create(self, proxy_token: str, **kwargs: Any) -> Any:
        self.tokens.append(proxy_token)
        return self.client


class Sender:
    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []
        self.failure: Exception | None = None

    async def send(self, chat: int, text: str) -> None:
        if self.failure:
            raise self.failure
        self.sent.append((chat, text))


@pytest.mark.asyncio
async def test_worker_minute_account_scope_and_late_feedback(store: FeedbackStore) -> None:
    client, sender = Client(), Sender()
    factory = Factory(client)
    now = NOW
    worker = FeedbackWorker(store, factory, sender, clock=lambda: now)
    await store.set_enabled(101, True)
    client.rows = [replace(s, score=None, score_text=None) for s in SESSIONS]
    await worker.scan(101)
    await worker.scan(101)
    assert len(client.calls) == 1
    assert client.calls[0] == {"merchant_id": "owner-1", "limit": 1000}
    assert factory.tokens == ["secret-1"]
    now += timedelta(seconds=60)
    client.rows = SESSIONS
    await worker.scan(101)
    await worker.deliver(101)
    assert len(sender.sent) == 2
    assert any("⭐⭐⭐☆☆" in text for _, text in sender.sent)
    now += timedelta(seconds=60)
    client.rows = [
        replace(s, score_text="edited") if s.uuid in {"review-1", "score-only"} else s
        for s in SESSIONS
    ]
    await worker.scan(101)
    await worker.deliver(101)
    assert len(sender.sent) == 2
    assert client.closed == 3


@pytest.mark.asyncio
async def test_worker_disable_while_request_inflight(store: FeedbackStore) -> None:
    client, sender = Client(), Sender()
    client.gate = asyncio.Event()
    worker = FeedbackWorker(store, Factory(client), sender, clock=lambda: NOW)
    await store.set_enabled(101, True)
    task = asyncio.create_task(worker.scan(101))
    for _ in range(100):
        if client.calls:
            break
        await asyncio.sleep(0.001)
    assert client.calls
    await store.set_enabled(101, False)
    client.gate.set()
    await task
    assert not (await store.settings(101)).initialized
    assert await store.pending(101) == []


@pytest.mark.asyncio
async def test_delivery_retries_parts_without_repeating_completed_parts(
    store: FeedbackStore,
) -> None:
    sender = Sender()
    now = NOW
    worker = FeedbackWorker(store, Factory(Client()), sender, clock=lambda: now)
    await store.set_enabled(101, True)
    ctx = await store.begin_poll(101, now)
    assert ctx is not None
    await ingest(store, ctx, {})
    now += timedelta(seconds=60)
    ctx = await store.begin_poll(101, now)
    assert ctx is not None
    await ingest(store, ctx, {"multi": ["part-1", "part-2"]})
    jobs = await store.pending(101)
    await store.complete(jobs[0].id)
    sender.failure = RuntimeError("do not log this private exception")
    await worker.deliver(101)
    sender.failure = None
    await worker.deliver(101)
    assert not sender.sent
    now += timedelta(seconds=60)
    await worker.deliver(101)
    assert sender.sent == [(101, "part-2")]
    assert not await store.pending(101)


@pytest.mark.asyncio
async def test_foreign_snapshot_is_not_accepted_or_shown_in_example(store: FeedbackStore) -> None:
    client = Client()
    worker = FeedbackWorker(store, Factory(client), Sender(), clock=lambda: NOW)
    await store.set_enabled(202, True)
    await worker.scan(202)
    state = await store.settings(202)
    assert not state.initialized and state.example_text is None
    assert "Демонстрационный" in (await FeedbackService(store).panel(202)).text


@pytest.mark.asyncio
async def test_supervisor_cleanup(store: FeedbackStore) -> None:
    worker = FeedbackWorker(store, Factory(Client()), Sender())
    await store.set_enabled(101, True)
    await worker.reconcile()
    assert 101 in worker.tasks
    await store.set_enabled(101, False)
    await worker.reconcile()
    assert not worker.tasks
    await worker.close()


def test_only_safe_rendered_data_is_in_notification() -> None:
    text = "\n".join(notification())
    assert not re.search(r"(?:\d{1,3}\.){3}\d{1,3}", text)
    assert SESSIONS[0].client_id is not None
    assert SESSIONS[0].client_id not in text


@pytest.mark.asyncio
async def test_valid_renewal_persists_before_scan_commit(store: FeedbackStore) -> None:
    await store.set_enabled(101, True)
    ctx = await store.begin_poll(101, NOW)
    assert ctx is not None
    await store.persist_token(ctx, "renewed-secret")
    assert store.encryptor.decrypt(ctx.encrypted_token) == "renewed-secret"
    assert await ingest(store, ctx) == 0
    assert (await store.settings(101)).initialized
    async with store.session_factory() as session:
        assert (
            await ChatProfileRepository(session, store.encryptor).decrypt_token(101)
            == "renewed-secret"
        )


@pytest.mark.asyncio
async def test_network_failure_preserves_baseline_and_does_not_block_pending_delivery(
    store: FeedbackStore,
) -> None:
    client, sender = Client(), Sender()
    now = NOW
    worker = FeedbackWorker(store, Factory(client), sender, clock=lambda: now)
    await store.set_enabled(101, True)
    ctx = await store.begin_poll(101, now)
    assert ctx is not None
    await ingest(store, ctx, {})
    now += timedelta(seconds=60)
    ctx = await store.begin_poll(101, now)
    assert ctx is not None
    await ingest(store, ctx, {"queued": ["pending"]})
    client.failure = True
    now += timedelta(seconds=60)
    await worker.scan(101)
    await worker.deliver(101)
    assert (await store.settings(101)).initialized
    assert sender.sent == [(101, "pending")]


@pytest.mark.asyncio
async def test_rate_limit_and_block_suspend_without_discarding_pending(
    store: FeedbackStore,
) -> None:
    sender = Sender()
    now = NOW
    worker = FeedbackWorker(store, Factory(Client()), sender, clock=lambda: now)
    await store.set_enabled(101, True)
    ctx = await store.begin_poll(101, now)
    assert ctx is not None
    await ingest(store, ctx, {})
    now += timedelta(seconds=60)
    ctx = await store.begin_poll(101, now)
    assert ctx is not None
    await ingest(store, ctx)
    method = SendMessage(chat_id=101, text="test")
    sender.failure = TelegramRetryAfter(method=method, message="rate limit", retry_after=120)
    await worker.deliver(101)
    assert (await store.pending(101))[0].next_attempt_at == now.timestamp() + 120
    now += timedelta(seconds=120)
    sender.failure = TelegramForbiddenError(method=method, message="blocked")
    await worker.deliver(101)
    assert (await store.settings(101)).suspended == "telegram"
    assert 101 not in await store.eligible_chats()
    await store.set_enabled(101, False)
    assert (await store.settings(101)).suspended is None
    assert not await store.pending(101)


@pytest.mark.asyncio
async def test_auth_failure_suspends_but_active_feedback_is_not_an_event(
    store: FeedbackStore,
) -> None:
    class UnauthorizedClient(Client):
        async def get_sessions(self, **kwargs: Any) -> SessionPage:
            raise DrovaUnauthorized("synthetic")

    await store.set_enabled(101, True)
    worker = FeedbackWorker(store, Factory(UnauthorizedClient()), Sender(), clock=lambda: NOW)
    await worker.scan(101)
    assert (await store.settings(101)).suspended == "auth"
    await store.set_enabled(101, True)
    client = Client()
    client.rows = [replace(SESSIONS[0], finished_on_ms=None)]
    worker = FeedbackWorker(
        store, Factory(client), Sender(), clock=lambda: NOW + timedelta(seconds=60)
    )
    await worker.scan(101)
    async with store.session_factory() as session:
        assert not (await session.scalars(select(FeedbackSeenRow))).all()


@pytest.mark.asyncio
async def test_at_most_four_scans_and_duplicate_concurrent_scan_does_not_overlap(
    store: FeedbackStore,
) -> None:
    active = peak = calls = 0
    gate = asyncio.Event()

    class BlockingClient(Client):
        async def get_sessions(self, **kwargs: Any) -> SessionPage:
            nonlocal active, peak, calls
            active += 1
            peak = max(peak, active)
            calls += 1
            try:
                await gate.wait()
                return SessionPage(sessions=[])
            finally:
                active -= 1

    async with store.session_factory.begin() as session:
        repo = ChatProfileRepository(session, store.encryptor)
        for chat_id in range(301, 307):
            await repo.connect_token(chat_id, drova_user_id="owner-1", proxy_token="synthetic")
    for chat_id in range(301, 307):
        await store.set_enabled(chat_id, True)
    worker = FeedbackWorker(store, Factory(BlockingClient()), Sender(), clock=lambda: NOW)
    tasks = [asyncio.create_task(worker.scan(chat_id)) for chat_id in range(301, 307)]
    tasks.append(asyncio.create_task(worker.scan(301)))
    try:
        for _ in range(1000):
            if active == 4:
                break
            await asyncio.sleep(0.001)
        assert active == 4 and calls == 4
    finally:
        gate.set()
        await asyncio.gather(*tasks)
    assert peak == 4 and calls == 6


@pytest.mark.asyncio
async def test_atomic_queue_failure_does_not_mark_review_seen(store: FeedbackStore) -> None:
    await store.set_enabled(101, True)
    ctx = await store.begin_poll(101, NOW)
    assert ctx is not None
    await ingest(store, ctx, {})
    ctx = await store.begin_poll(101, NOW + timedelta(seconds=60))
    assert ctx is not None
    with pytest.raises(IntegrityError):
        await ingest(store, ctx, {"broken": [None]})
    async with store.session_factory() as session:
        assert not (await session.scalars(select(FeedbackSeenRow))).all()
    assert not await store.pending(101)
    assert await ingest(store, ctx, {"broken": ["recovered"]}) == 1


@pytest.mark.asyncio
async def test_sender_plain_fallback_preserves_user_text_and_disables_previews() -> None:
    class Bot:
        def __init__(self) -> None:
            self.calls: list[tuple[int, str, dict[str, Any]]] = []

        async def send_message(self, chat_id: int, text: str, **kwargs: Any) -> None:
            self.calls.append((chat_id, text, kwargs))
            if len(self.calls) == 1:
                raise TelegramBadRequest(
                    method=SendMessage(chat_id=chat_id, text=text), message="can't parse entities"
                )

    bot = Bot()
    await TelegramFeedbackSender(cast(AiogramBot, bot)).send(
        101, "<b>Отзыв</b> &lt;test&gt; <code>…123456</code>"
    )
    assert bot.calls[1][1] == "Отзыв <test> …123456"
    assert bot.calls[1][2]["parse_mode"] is None
    assert bot.calls[1][2]["link_preview_options"].is_disabled


def test_aborted_session_keeps_its_actual_status() -> None:
    assert "прервана" in notification(replace(SESSIONS[0], status="ABORTED"))[0]


@pytest.mark.asyncio
async def test_each_chat_has_independent_seen_keys_and_examples(store: FeedbackStore) -> None:
    for chat_id in (101, 202):
        await store.set_enabled(chat_id, True)
        ctx = await store.begin_poll(chat_id, NOW)
        assert ctx is not None
        await store.ingest(ctx, {}, None, NOW)
        ctx = await store.begin_poll(chat_id, NOW + timedelta(seconds=60))
        assert ctx is not None
        await store.ingest(ctx, {"same-session-id": [f"chat-{chat_id}"]}, f"example-{chat_id}", NOW)
    assert [part.text for part in await store.pending(101)] == ["chat-101"]
    assert [part.text for part in await store.pending(202)] == ["chat-202"]
    assert (await FeedbackService(store).panel(101)).text.endswith("example-101")
    assert (await FeedbackService(store).panel(202)).text.endswith("example-202")
