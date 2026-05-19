"""Core Telegram command and callback router."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any

import structlog
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from drova_bot.application.services import BotService
from drova_bot.drova.errors import TelegramDeliveryFailed
from drova_bot.exports import ExportKind
from drova_bot.telegram.callbacks import InvalidCallbackData, parse_callback_data
from drova_bot.telegram.delivery import (
    answer_rendered,
    edit_or_answer_rendered,
    edit_rendered_message,
    send_export_file,
)
from drova_bot.telegram.renderers import RenderedMessage, render_error, render_help

EXPORT_ALIASES = {
    "dumpall",
    "dumpOnefile",
    "dumpStationsProducts",
    "dumpStationsProductsWithTime",
    "dumpStationsProductsMonth",
}
logger = structlog.get_logger(__name__)


def build_router() -> Router:
    router = Router(name="drova_bot_core")
    router.message.register(start_command, Command("start"))
    router.message.register(help_command, Command("help"))
    router.message.register(token_command, Command("token"))
    router.message.register(logout_command, Command("logout", "removeToken"))
    router.message.register(station_command, Command("station"))
    router.message.register(station_all_command, Command("station_all"))
    router.message.register(limit_command, Command("limit"))
    router.message.register(sessions_command, Command("sessions"))
    router.message.register(sessions_short_command, Command("sessions_short"))
    router.message.register(current_command, Command("current"))
    router.message.register(account_command, Command("account"))
    router.message.register(disabled_command, Command("disabled"))
    router.message.register(stations_command, Command("stations", "stationsInfo"))
    router.message.register(games_command, Command("games"))
    router.message.register(game_command, Command("game"))
    router.message.register(game_hide_command, Command("game_hide"))
    router.message.register(game_show_command, Command("game_show"))
    router.message.register(game_hide_all_command, Command("game_hide_all"))
    router.message.register(promocode_command, Command("promocode"))
    router.message.register(promocodes_command, Command("promocodes"))
    router.message.register(
        export_command,
        Command(
            "export",
            "export_sessions",
            "export_sessions_csv",
            "export_products",
            "export_product_time",
            *EXPORT_ALIASES,
        ),
    )
    router.callback_query.register(callback_query)
    router.message.register(unknown_command, F.text.startswith("/"))
    router.message.register(unknown_text)
    return router


async def start_command(message: Message, bot_service: BotService) -> None:
    await answer_rendered(message, await bot_service.start(message.chat.id))


async def help_command(message: Message) -> None:
    await answer_rendered(message, render_help())


async def token_command(message: Message, bot_service: BotService) -> None:
    await answer_rendered(
        message,
        await bot_service.connect_token(message.chat.id, _command_args(message.text)),
    )


async def logout_command(message: Message, bot_service: BotService) -> None:
    await answer_rendered(message, await bot_service.logout(message.chat.id))


async def station_command(message: Message, bot_service: BotService) -> None:
    args = _command_args(message.text).strip()
    if args == "all":
        rendered = await bot_service.select_all_stations(message.chat.id)
    else:
        rendered = await bot_service.station_picker(message.chat.id)
    await answer_rendered(message, rendered)


async def station_all_command(message: Message, bot_service: BotService) -> None:
    await answer_rendered(message, await bot_service.select_all_stations(message.chat.id))


async def limit_command(message: Message, bot_service: BotService) -> None:
    await answer_rendered(
        message,
        await bot_service.set_limit(message.chat.id, _command_args(message.text)),
    )


async def sessions_command(message: Message, bot_service: BotService) -> None:
    await answer_rendered(
        message,
        await bot_service.sessions(
            message.chat.id,
            short_mode=_command_args(message.text).strip() == "short",
        ),
    )


async def sessions_short_command(message: Message, bot_service: BotService) -> None:
    await answer_rendered(
        message,
        await bot_service.sessions(message.chat.id, short_mode=True),
    )


async def current_command(message: Message, bot_service: BotService) -> None:
    await answer_rendered(message, await bot_service.current(message.chat.id))


async def account_command(message: Message, bot_service: BotService) -> None:
    await answer_rendered(message, await bot_service.account_billing(message.chat.id))


async def disabled_command(message: Message, bot_service: BotService) -> None:
    await answer_rendered(message, await bot_service.disabled(message.chat.id))


async def stations_command(message: Message, bot_service: BotService) -> None:
    await answer_rendered(message, await bot_service.stations(message.chat.id))


async def games_command(message: Message, bot_service: BotService) -> None:
    await answer_rendered(message, await bot_service.station_games(message.chat.id))


async def game_command(message: Message, bot_service: BotService) -> None:
    await answer_rendered(
        message,
        await bot_service.station_game(message.chat.id, _command_args(message.text)),
    )


async def game_hide_command(message: Message, bot_service: BotService) -> None:
    await answer_rendered(
        message,
        await bot_service.set_station_game_enabled(
            message.chat.id,
            _command_args(message.text),
            enabled=False,
        ),
    )


async def game_show_command(message: Message, bot_service: BotService) -> None:
    await answer_rendered(
        message,
        await bot_service.set_station_game_enabled(
            message.chat.id,
            _command_args(message.text),
            enabled=True,
        ),
    )


async def game_hide_all_command(message: Message, bot_service: BotService) -> None:
    await answer_rendered(
        message,
        await bot_service.hide_game_all(message.chat.id, _command_args(message.text)),
    )


async def promocode_command(message: Message, bot_service: BotService) -> None:
    await answer_rendered(
        message,
        await bot_service.issue_promocode(message.chat.id, _command_args(message.text)),
    )


async def promocodes_command(message: Message, bot_service: BotService) -> None:
    await answer_rendered(message, await bot_service.unused_promocodes(message.chat.id))


async def export_command(message: Message, bot_service: BotService) -> None:
    kind = export_kind_from_message(message.text)
    if kind is None:
        await answer_rendered(message, render_error("unknown_command"))
        return
    progress = await answer_rendered(message, RenderedMessage("Готовлю файл..."))
    progress_message = progress if isinstance(progress, Message) else message
    job = await bot_service.create_export_job(message.chat.id, kind)
    schedule_background_task(
        deliver_export_job(
            source_message=message,
            progress_message=progress_message,
            bot_service=bot_service,
            telegram_chat_id=message.chat.id,
            job_id=job.id,
            kind=kind,
        )
    )


async def deliver_export_job(
    *,
    source_message: Message,
    progress_message: Message,
    bot_service: BotService,
    telegram_chat_id: int,
    job_id: str,
    kind: ExportKind,
) -> None:
    result = await bot_service.run_export_job(
        job_id=job_id,
        telegram_chat_id=telegram_chat_id,
        kind=kind,
    )
    try:
        for export_file in result.files:
            await send_export_file(source_message, export_file)
        await edit_rendered_message(progress_message, RenderedMessage(result.message))
    except TelegramDeliveryFailed:
        await bot_service.fail_export_job(job_id, "telegram_delivery_failed")
        logger.warning("telegram_export_delivery_failed", export_job_id=job_id)


def schedule_background_task(coro: Coroutine[Any, Any, None]) -> asyncio.Task[None]:
    return asyncio.create_task(coro)


async def callback_query(callback: CallbackQuery, bot_service: BotService) -> None:
    try:
        parsed = parse_callback_data(callback.data)
        chat_id = (
            callback.message.chat.id if callback.message is not None else callback.from_user.id
        )
        rendered = await bot_service.handle_callback(chat_id, parsed)
    except InvalidCallbackData:
        rendered = render_error("unknown_command")
    await edit_or_answer_rendered(callback, rendered)
    await callback.answer()


async def unknown_command(message: Message) -> None:
    await answer_rendered(message, render_error("unknown_command"))


async def unknown_text(message: Message) -> None:
    await answer_rendered(message, render_error("unknown_text"))


def _command_args(text: str | None) -> str:
    if not text:
        return ""
    _, separator, tail = text.partition(" ")
    if not separator:
        return ""
    return tail.strip()


def export_kind_from_message(text: str | None) -> ExportKind | None:
    if not text:
        return None
    command = text.split(maxsplit=1)[0].removeprefix("/").split("@", maxsplit=1)[0]
    args = _command_args(text)
    one_word_mapping = {
        "export_sessions": ExportKind.SESSIONS,
        "export_sessions_csv": ExportKind.SESSIONS_CSV,
        "export_products": ExportKind.PRODUCTS,
        "export_product_time": ExportKind.PRODUCT_TIME,
    }
    if command in one_word_mapping:
        return one_word_mapping[command]
    if command == "export":
        if args == "sessions":
            return ExportKind.SESSIONS
        if args == "products":
            return ExportKind.PRODUCTS
        if args == "product-time":
            return ExportKind.PRODUCT_TIME
        return None
    legacy_mapping = {
        "dumpall": ExportKind.SESSIONS_CSV,
        "dumpOnefile": ExportKind.SESSIONS,
        "dumpStationsProducts": ExportKind.PRODUCTS,
        "dumpStationsProductsWithTime": ExportKind.PRODUCT_TIME,
        "dumpStationsProductsMonth": ExportKind.PRODUCT_TIME,
    }
    return legacy_mapping.get(command)
