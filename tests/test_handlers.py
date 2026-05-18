from __future__ import annotations

from typing import Any, cast

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import SendMessage
from aiogram.types import CallbackQuery, Message

from drova_bot.exports import ExportFile, ExportKind, ExportResult
from drova_bot.telegram.callbacks import CallbackSpec
from drova_bot.telegram.delivery import answer_rendered
from drova_bot.telegram.renderers import RenderedMessage
from drova_bot.telegram.routers import build_router
from drova_bot.telegram.routers.core import (
    callback_query,
    export_command,
    export_kind_from_message,
    limit_command,
    logout_command,
    sessions_command,
    station_command,
    token_command,
    unknown_command,
    unknown_text,
)


class FakeChat:
    def __init__(self, chat_id: int = 10001) -> None:
        self.id = chat_id


class FakeUser:
    def __init__(self, user_id: int = 10001) -> None:
        self.id = user_id


class FakeMessage:
    def __init__(self, text: str | None = None, *, fail_html_once: bool = False) -> None:
        self.text = text
        self.chat = FakeChat()
        self.fail_html_once = fail_html_once
        self.answers: list[tuple[str, dict[str, Any]]] = []
        self.documents: list[tuple[Any, dict[str, Any]]] = []
        self.edits: list[tuple[str, dict[str, Any]]] = []

    async def answer(self, text: str, **kwargs: Any) -> None:
        if self.fail_html_once and kwargs.get("parse_mode") == "HTML":
            self.fail_html_once = False
            raise _telegram_bad_request()
        self.answers.append((text, kwargs))

    async def edit_text(self, text: str, **kwargs: Any) -> None:
        self.edits.append((text, kwargs))

    async def answer_document(self, document: Any, **kwargs: Any) -> None:
        self.documents.append((document, kwargs))


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

    async def handle_callback(self, chat_id: int, callback: object) -> RenderedMessage:
        self.calls.append(("handle_callback", (chat_id, callback), {}))
        return RenderedMessage("callback")

    async def export(self, chat_id: int, kind: ExportKind) -> ExportResult:
        self.calls.append(("export", (chat_id, kind), {}))
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


def test_build_router_exposes_aiogram_router() -> None:
    router = build_router()
    assert router.name == "drova_bot_core"


@pytest.mark.asyncio
async def test_token_limit_sessions_and_station_handlers_parse_arguments() -> None:
    service = FakeService()

    token_message = FakeMessage("/token proxy-token")
    await token_command(cast(Message, token_message), service)  # type: ignore[arg-type]
    await limit_command(cast(Message, FakeMessage("/limit 25")), service)  # type: ignore[arg-type]
    await sessions_command(cast(Message, FakeMessage("/sessions short")), service)  # type: ignore[arg-type]
    await station_command(cast(Message, FakeMessage("/station all")), service)  # type: ignore[arg-type]

    assert service.calls == [
        ("connect_token", (10001, "proxy-token"), {}),
        ("set_limit", (10001, "25"), {}),
        ("sessions", (10001,), {"short_mode": True}),
        ("select_all_stations", (10001,), {}),
    ]
    assert token_message.answers[0][0] == "token:proxy-token"


@pytest.mark.asyncio
async def test_legacy_logout_and_export_command() -> None:
    service = FakeService()
    logout_message = FakeMessage("/removeToken")
    export_message = FakeMessage("/dumpall")

    await logout_command(cast(Message, logout_message), service)  # type: ignore[arg-type]
    await export_command(cast(Message, export_message), service)  # type: ignore[arg-type]

    assert service.calls == [
        ("logout", (10001,), {}),
        ("export", (10001, ExportKind.SESSIONS_CSV), {}),
    ]
    assert export_message.answers[0][0] == "Готовлю файл..."
    assert export_message.documents[0][0].filename == "sessions_csv.xlsx"
    assert export_message.answers[-1][0] == "Файл готов."


def test_export_kind_mapping() -> None:
    assert export_kind_from_message("/export sessions") == ExportKind.SESSIONS
    assert export_kind_from_message("/export products") == ExportKind.PRODUCTS
    assert export_kind_from_message("/export product-time") == ExportKind.PRODUCT_TIME
    assert export_kind_from_message("/dumpOnefile") == ExportKind.SESSIONS
    assert export_kind_from_message("/dumpall") == ExportKind.SESSIONS_CSV
    assert export_kind_from_message("/dumpStationsProducts") == ExportKind.PRODUCTS
    assert export_kind_from_message("/dumpStationsProductsMonth") == ExportKind.PRODUCT_TIME
    assert export_kind_from_message("/export nope") is None


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


def _telegram_bad_request() -> TelegramBadRequest:
    return TelegramBadRequest(
        method=SendMessage(chat_id=10001, text="x"),
        message="bad request",
    )
