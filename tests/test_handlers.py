from __future__ import annotations

from typing import Any, cast

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import SendMessage
from aiogram.types import CallbackQuery, Message

from drova_bot.drova.errors import TelegramDeliveryFailed
from drova_bot.exports import ExportFile, ExportKind, ExportResult
from drova_bot.telegram.callbacks import CallbackSpec, parse_callback_data
from drova_bot.telegram.delivery import answer_rendered
from drova_bot.telegram.renderers import RenderedMessage
from drova_bot.telegram.routers import build_router
from drova_bot.telegram.routers.core import (
    account_command,
    callback_query,
    current_command,
    deliver_export_job,
    desktop_off_command,
    desktop_off_confirm_command,
    desktop_on_command,
    desktop_on_confirm_command,
    disabled_command,
    export_command,
    export_kind_from_message,
    game_command,
    game_hide_all_command,
    game_hide_command,
    game_show_command,
    games_command,
    help_command,
    limit_command,
    logout_command,
    promocode_command,
    promocodes_command,
    server_description_apply_command,
    server_description_command,
    server_source_command,
    sessions_command,
    sessions_short_command,
    start_command,
    station_all_command,
    station_command,
    stations_command,
    token_command,
    unknown_command,
    unknown_text,
    updates_off_command,
    updates_off_confirm_command,
    updates_on_command,
    updates_on_confirm_command,
    usage_command,
)


class FakeChat:
    def __init__(self, chat_id: int = 10001) -> None:
        self.id = chat_id


class FakeUser:
    def __init__(self, user_id: int = 10001) -> None:
        self.id = user_id


class FakeMessage:
    def __init__(
        self,
        text: str | None = None,
        *,
        fail_html_once: bool = False,
        fail_html_always: bool = False,
        fail_document: bool = False,
    ) -> None:
        self.text = text
        self.chat = FakeChat()
        self.fail_html_once = fail_html_once
        self.fail_html_always = fail_html_always
        self.fail_document = fail_document
        self.answers: list[tuple[str, dict[str, Any]]] = []
        self.documents: list[tuple[Any, dict[str, Any]]] = []
        self.edits: list[tuple[str, dict[str, Any]]] = []

    async def answer(self, text: str, **kwargs: Any) -> FakeMessage:
        if self.fail_html_always:
            raise _telegram_bad_request()
        if self.fail_html_once and kwargs.get("parse_mode") == "HTML":
            self.fail_html_once = False
            raise _telegram_bad_request()
        self.answers.append((text, kwargs))
        return self

    async def edit_text(self, text: str, **kwargs: Any) -> FakeMessage:
        self.edits.append((text, kwargs))
        return self

    async def answer_document(self, document: Any, **kwargs: Any) -> FakeMessage:
        if self.fail_document:
            raise _telegram_bad_request()
        self.documents.append((document, kwargs))
        return self


class FakeCallback:
    def __init__(self, data: str | None) -> None:
        self.data = data
        self.message = FakeMessage()
        self.from_user = FakeUser()
        self.answers: list[dict[str, Any]] = []

    async def answer(self, *args: Any, **kwargs: Any) -> None:
        self.answers.append({"args": args, "kwargs": kwargs})


class FakeService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    async def start(self, chat_id: int) -> RenderedMessage:
        self.calls.append(("start", (chat_id,), {}))
        return RenderedMessage("start")

    async def connect_token(self, chat_id: int, token: str) -> RenderedMessage:
        self.calls.append(("connect_token", (chat_id, token), {}))
        return RenderedMessage(f"token:{token}")

    async def logout(self, chat_id: int) -> RenderedMessage:
        self.calls.append(("logout", (chat_id,), {}))
        return RenderedMessage("logout")

    async def select_all_stations(self, chat_id: int) -> RenderedMessage:
        self.calls.append(("select_all_stations", (chat_id,), {}))
        return RenderedMessage("all")

    async def station_picker(self, chat_id: int) -> RenderedMessage:
        self.calls.append(("station_picker", (chat_id,), {}))
        return RenderedMessage("picker")

    async def set_limit(self, chat_id: int, raw_limit: str) -> RenderedMessage:
        self.calls.append(("set_limit", (chat_id, raw_limit), {}))
        return RenderedMessage(f"limit:{raw_limit}")

    async def sessions(self, chat_id: int, *, short_mode: bool = False) -> RenderedMessage:
        self.calls.append(("sessions", (chat_id,), {"short_mode": short_mode}))
        return RenderedMessage(f"sessions:{short_mode}")

    async def current(self, chat_id: int) -> RenderedMessage:
        self.calls.append(("current", (chat_id,), {}))
        return RenderedMessage("current")

    async def account_billing(self, chat_id: int) -> RenderedMessage:
        self.calls.append(("account_billing", (chat_id,), {}))
        return RenderedMessage("account")

    async def usage_statistics(self, chat_id: int) -> RenderedMessage:
        self.calls.append(("usage_statistics", (chat_id,), {}))
        return RenderedMessage("usage")

    async def disabled(self, chat_id: int) -> RenderedMessage:
        self.calls.append(("disabled", (chat_id,), {}))
        return RenderedMessage("disabled")

    async def stations(self, chat_id: int) -> RenderedMessage:
        self.calls.append(("stations", (chat_id,), {}))
        return RenderedMessage("stations")

    async def station_games(self, chat_id: int) -> RenderedMessage:
        self.calls.append(("station_games", (chat_id,), {}))
        return RenderedMessage("games")

    async def station_game(self, chat_id: int, product_id: str) -> RenderedMessage:
        self.calls.append(("station_game", (chat_id, product_id), {}))
        return RenderedMessage(f"game:{product_id}")

    async def set_station_game_enabled(
        self,
        chat_id: int,
        product_id: str,
        *,
        enabled: bool,
    ) -> RenderedMessage:
        self.calls.append(("set_station_game_enabled", (chat_id, product_id), {"enabled": enabled}))
        return RenderedMessage(f"game_enabled:{enabled}:{product_id}")

    async def hide_game_all(self, chat_id: int, product_id: str) -> RenderedMessage:
        self.calls.append(("hide_game_all", (chat_id, product_id), {}))
        return RenderedMessage(f"hide_all:{product_id}")

    async def server_control_confirmation(self, chat_id: int, action: str) -> RenderedMessage:
        self.calls.append(("server_control_confirmation", (chat_id, action), {}))
        return RenderedMessage(f"control:{action}")

    async def server_control_confirm(
        self,
        chat_id: int,
        action: str,
        expected_state: str,
    ) -> RenderedMessage:
        self.calls.append(("server_control_confirm", (chat_id, action, expected_state), {}))
        return RenderedMessage(f"control_confirm:{action}:{expected_state}")

    async def server_source(self, chat_id: int) -> RenderedMessage:
        self.calls.append(("server_source", (chat_id,), {}))
        return RenderedMessage("server_source")

    async def server_description_preview(
        self,
        chat_id: int,
        description: str,
    ) -> RenderedMessage:
        self.calls.append(("server_description_preview", (chat_id, description), {}))
        return RenderedMessage(f"server_description:{description}")

    async def server_description_apply(
        self,
        chat_id: int,
        payload: str,
    ) -> RenderedMessage:
        self.calls.append(("server_description_apply", (chat_id, payload), {}))
        return RenderedMessage(f"server_description_apply:{payload}")

    async def issue_promocode(self, chat_id: int, raw_minutes: str) -> RenderedMessage:
        self.calls.append(("issue_promocode", (chat_id, raw_minutes), {}))
        return RenderedMessage(f"promocode:{raw_minutes}")

    async def unused_promocodes(self, chat_id: int) -> RenderedMessage:
        self.calls.append(("unused_promocodes", (chat_id,), {}))
        return RenderedMessage("promocodes")

    async def handle_callback(self, chat_id: int, callback: object) -> RenderedMessage:
        self.calls.append(("handle_callback", (chat_id, callback), {}))
        return RenderedMessage("callback")

    async def export(self, chat_id: int, kind: ExportKind) -> ExportResult:
        self.calls.append(("export", (chat_id, kind), {}))
        return await self._export_result(kind)

    async def create_export_job(self, chat_id: int, kind: ExportKind) -> object:
        self.calls.append(("create_export_job", (chat_id, kind), {}))
        return FakeExportJob("job-1")

    async def run_export_job(
        self,
        *,
        job_id: str,
        telegram_chat_id: int,
        kind: ExportKind,
    ) -> ExportResult:
        self.calls.append(("run_export_job", (job_id, telegram_chat_id, kind), {}))
        return await self._export_result(kind)

    async def fail_export_job(self, job_id: str, error_code: str) -> None:
        self.calls.append(("fail_export_job", (job_id, error_code), {}))

    async def _export_result(self, kind: ExportKind) -> ExportResult:
        return ExportResult(
            files=[
                ExportFile(
                    filename=f"{kind.value}.xlsx",
                    content_type="application/octet-stream",
                    payload=b"payload",
                )
            ],
            message="Файл готов.",
        )


class FakeExportJob:
    def __init__(self, job_id: str) -> None:
        self.id = job_id


def test_build_router_exposes_aiogram_router() -> None:
    router = build_router()
    assert router.name == "drova_bot_core"


@pytest.mark.asyncio
async def test_basic_command_handlers_route_to_service_or_help() -> None:
    service = FakeService()
    start_message = FakeMessage("/start")
    help_message = FakeMessage("/help")
    current_message = FakeMessage("/current")
    account_message = FakeMessage("/account")
    usage_message = FakeMessage("/usage")
    server_source_message = FakeMessage("/server_source")
    disabled_message = FakeMessage("/disabled")
    stations_message = FakeMessage("/stations")

    await start_command(cast(Message, start_message), service)  # type: ignore[arg-type]
    await help_command(cast(Message, help_message))
    await current_command(cast(Message, current_message), service)  # type: ignore[arg-type]
    await account_command(cast(Message, account_message), service)  # type: ignore[arg-type]
    await usage_command(cast(Message, usage_message), service)  # type: ignore[arg-type]
    await server_source_command(cast(Message, server_source_message), service)  # type: ignore[arg-type]
    await disabled_command(cast(Message, disabled_message), service)  # type: ignore[arg-type]
    await stations_command(cast(Message, stations_message), service)  # type: ignore[arg-type]

    assert service.calls == [
        ("start", (10001,), {}),
        ("current", (10001,), {}),
        ("account_billing", (10001,), {}),
        ("usage_statistics", (10001,), {}),
        ("server_source", (10001,), {}),
        ("disabled", (10001,), {}),
        ("stations", (10001,), {}),
    ]
    assert start_message.answers[0][0] == "start"
    assert "Команды:" in help_message.answers[0][0]
    assert current_message.answers[0][0] == "current"
    assert account_message.answers[0][0] == "account"
    assert usage_message.answers[0][0] == "usage"
    assert server_source_message.answers[0][0] == "server_source"
    assert disabled_message.answers[0][0] == "disabled"
    assert stations_message.answers[0][0] == "stations"


@pytest.mark.asyncio
async def test_token_limit_sessions_and_station_handlers_parse_arguments() -> None:
    service = FakeService()

    token_message = FakeMessage("/token proxy-token")
    await token_command(cast(Message, token_message), service)  # type: ignore[arg-type]
    await limit_command(cast(Message, FakeMessage("/limit 25")), service)  # type: ignore[arg-type]
    await sessions_short_command(cast(Message, FakeMessage("/sessions_short")), service)  # type: ignore[arg-type]
    await station_all_command(cast(Message, FakeMessage("/station_all")), service)  # type: ignore[arg-type]
    await promocode_command(cast(Message, FakeMessage("/promocode 60")), service)  # type: ignore[arg-type]
    await promocodes_command(cast(Message, FakeMessage("/promocodes")), service)  # type: ignore[arg-type]
    await games_command(cast(Message, FakeMessage("/games")), service)  # type: ignore[arg-type]
    await game_command(cast(Message, FakeMessage("/game product-a")), service)  # type: ignore[arg-type]
    await game_hide_command(cast(Message, FakeMessage("/game_hide product-a")), service)  # type: ignore[arg-type]
    await game_show_command(cast(Message, FakeMessage("/game_show product-a")), service)  # type: ignore[arg-type]
    await game_hide_all_command(cast(Message, FakeMessage("/game_hide_all product-b")), service)  # type: ignore[arg-type]
    await desktop_on_command(cast(Message, FakeMessage("/desktop_on")), service)  # type: ignore[arg-type]
    await desktop_on_confirm_command(
        cast(Message, FakeMessage("/desktop_on_confirm off")), service  # type: ignore[arg-type]
    )
    await desktop_off_command(cast(Message, FakeMessage("/desktop_off")), service)  # type: ignore[arg-type]
    await desktop_off_confirm_command(
        cast(Message, FakeMessage("/desktop_off_confirm on")), service  # type: ignore[arg-type]
    )
    await updates_on_command(cast(Message, FakeMessage("/updates_on")), service)  # type: ignore[arg-type]
    await updates_on_confirm_command(
        cast(Message, FakeMessage("/updates_on_confirm off")), service  # type: ignore[arg-type]
    )
    await updates_off_command(cast(Message, FakeMessage("/updates_off")), service)  # type: ignore[arg-type]
    await updates_off_confirm_command(
        cast(Message, FakeMessage("/updates_off_confirm on")), service  # type: ignore[arg-type]
    )
    await server_description_command(
        cast(Message, FakeMessage("/server_description New source")),
        service,  # type: ignore[arg-type]
    )
    await server_description_apply_command(
        cast(Message, FakeMessage("/server_description_apply abc123 New source")),
        service,  # type: ignore[arg-type]
    )

    assert service.calls == [
        ("connect_token", (10001, "proxy-token"), {}),
        ("set_limit", (10001, "25"), {}),
        ("sessions", (10001,), {"short_mode": True}),
        ("select_all_stations", (10001,), {}),
        ("issue_promocode", (10001, "60"), {}),
        ("unused_promocodes", (10001,), {}),
        ("station_games", (10001,), {}),
        ("station_game", (10001, "product-a"), {}),
        ("set_station_game_enabled", (10001, "product-a"), {"enabled": False}),
        ("set_station_game_enabled", (10001, "product-a"), {"enabled": True}),
        ("hide_game_all", (10001, "product-b"), {}),
        ("server_control_confirmation", (10001, "desktop_on"), {}),
        ("server_control_confirm", (10001, "desktop_on", "off"), {}),
        ("server_control_confirmation", (10001, "desktop_off"), {}),
        ("server_control_confirm", (10001, "desktop_off", "on"), {}),
        ("server_control_confirmation", (10001, "updates_on"), {}),
        ("server_control_confirm", (10001, "updates_on", "off"), {}),
        ("server_control_confirmation", (10001, "updates_off"), {}),
        ("server_control_confirm", (10001, "updates_off", "on"), {}),
        ("server_description_preview", (10001, "New source"), {}),
        ("server_description_apply", (10001, "abc123 New source"), {}),
    ]
    assert token_message.answers[0][0] == "token:proxy-token"


@pytest.mark.asyncio
async def test_legacy_multiword_command_aliases_still_work() -> None:
    service = FakeService()

    await sessions_command(cast(Message, FakeMessage("/sessions short")), service)  # type: ignore[arg-type]
    await station_command(cast(Message, FakeMessage("/station all")), service)  # type: ignore[arg-type]

    assert service.calls == [
        ("sessions", (10001,), {"short_mode": True}),
        ("select_all_stations", (10001,), {}),
    ]


@pytest.mark.asyncio
async def test_legacy_logout_and_one_word_export_command(monkeypatch: pytest.MonkeyPatch) -> None:
    from drova_bot.telegram.routers import core

    service = FakeService()
    logout_message = FakeMessage("/removeToken")
    export_message = FakeMessage("/export_sessions_csv")
    scheduled: list[Any] = []

    def capture_task(coro: Any) -> None:
        scheduled.append(coro)

    monkeypatch.setattr(core, "schedule_background_task", capture_task)

    await logout_command(cast(Message, logout_message), service)  # type: ignore[arg-type]
    await export_command(cast(Message, export_message), service)  # type: ignore[arg-type]

    assert service.calls == [
        ("logout", (10001,), {}),
        ("create_export_job", (10001, ExportKind.SESSIONS_CSV), {}),
    ]
    assert export_message.answers[0][0] == "Готовлю файл..."
    assert export_message.documents == []
    assert scheduled

    await scheduled[0]

    assert service.calls[-1] == (
        "run_export_job",
        ("job-1", 10001, ExportKind.SESSIONS_CSV),
        {},
    )
    assert export_message.documents[0][0].filename == "sessions_csv.xlsx"
    assert export_message.edits[-1][0] == "Файл готов."


def test_export_kind_mapping() -> None:
    assert export_kind_from_message("/export_sessions") == ExportKind.SESSIONS
    assert export_kind_from_message("/export_sessions_csv") == ExportKind.SESSIONS_CSV
    assert export_kind_from_message("/export_products") == ExportKind.PRODUCTS
    assert export_kind_from_message("/export_product_time") == ExportKind.PRODUCT_TIME
    assert export_kind_from_message("/export sessions") == ExportKind.SESSIONS
    assert export_kind_from_message("/export products") == ExportKind.PRODUCTS
    assert export_kind_from_message("/export product-time") == ExportKind.PRODUCT_TIME
    assert export_kind_from_message("/dumpOnefile") == ExportKind.SESSIONS
    assert export_kind_from_message("/dumpall") == ExportKind.SESSIONS_CSV
    assert export_kind_from_message("/dumpStationsProducts") == ExportKind.PRODUCTS
    assert export_kind_from_message("/dumpStationsProductsMonth") == ExportKind.PRODUCT_TIME
    assert export_kind_from_message("/export nope") is None


def test_callback_payloads_fit_telegram_limit_and_parse_legacy_format() -> None:
    station_uuid = "000019ee-2466-41ef-9ff8-4bfe7aa9fd4f"
    select_payload = CallbackSpec(
        action="publish_select",
        station_id=station_uuid,
        expected_published=True,
    ).pack()
    confirm_payload = CallbackSpec(
        action="publish_confirm",
        station_id=station_uuid,
        expected_published=False,
    ).pack()

    assert len(select_payload.encode("utf-8")) <= 64
    assert len(confirm_payload.encode("utf-8")) <= 64
    assert parse_callback_data(select_payload).action == "publish_select"
    assert parse_callback_data(select_payload).station_id == station_uuid
    assert parse_callback_data(select_payload).expected_published is True
    page_payload = CallbackSpec(action="sessions_short_page", page=12).pack()
    assert len(page_payload.encode("utf-8")) <= 64
    parsed_page = parse_callback_data(page_payload)
    assert parsed_page.action == "sessions_short_page"
    assert parsed_page.page == 12

    legacy = f"publish_select|station={station_uuid}|published=1"
    parsed_legacy = parse_callback_data(legacy)
    assert parsed_legacy.action == "publish_select"
    assert parsed_legacy.station_id == station_uuid
    assert parsed_legacy.expected_published is True


@pytest.mark.asyncio
async def test_callback_handler_parses_payload_and_answers() -> None:
    service = FakeService()
    callback = FakeCallback(CallbackSpec(action="sessions_short").pack())

    await callback_query(cast(CallbackQuery, callback), service)  # type: ignore[arg-type]

    assert service.calls[0][0] == "handle_callback"
    assert callback.message.edits[0][0] == "callback"
    assert callback.answers


@pytest.mark.asyncio
async def test_unknown_command_and_text() -> None:
    command = FakeMessage("/wat")
    text = FakeMessage("hello")

    await unknown_command(cast(Message, command))
    await unknown_text(cast(Message, text))

    assert command.answers[0][0] == "Команда не найдена. Используйте /help."
    assert text.answers[0][0] == "Я понимаю только команды. Используйте /help."


@pytest.mark.asyncio
async def test_html_delivery_fallback_unescapes_text() -> None:
    message = FakeMessage(fail_html_once=True)

    await answer_rendered(
        cast(Message, message),
        RenderedMessage("Токен: &lt;hidden&gt;"),
    )

    assert message.answers == [("Токен: <hidden>", {"parse_mode": None, "reply_markup": None})]


@pytest.mark.asyncio
async def test_html_delivery_failure_after_fallback_raises_safe_error() -> None:
    message = FakeMessage(fail_html_always=True)

    with pytest.raises(TelegramDeliveryFailed):
        await answer_rendered(cast(Message, message), RenderedMessage("bad <b>html</b>"))


@pytest.mark.asyncio
async def test_export_delivery_failure_marks_job_failed() -> None:
    service = FakeService()
    message = FakeMessage("/dumpall", fail_document=True)

    await deliver_export_job(
        source_message=cast(Message, message),
        progress_message=cast(Message, message),
        bot_service=service,  # type: ignore[arg-type]
        telegram_chat_id=10001,
        job_id="job-1",
        kind=ExportKind.SESSIONS_CSV,
    )

    assert service.calls[-1] == (
        "fail_export_job",
        ("job-1", "telegram_delivery_failed"),
        {},
    )
    assert message.edits == []


def _telegram_bad_request() -> TelegramBadRequest:
    return TelegramBadRequest(
        method=SendMessage(chat_id=10001, text="x"),
        message="bad request",
    )
