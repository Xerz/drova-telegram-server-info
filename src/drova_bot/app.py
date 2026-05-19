"""Production runtime entrypoint for Drova Bot V2."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import structlog
from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine

from drova_bot.application.services import BotService, DefaultDrovaClientFactory
from drova_bot.config import Settings
from drova_bot.geoip import GeoLiteResolver
from drova_bot.observability.logging import configure_logging
from drova_bot.storage import (
    StorageUnitOfWorkFactory,
    TokenEncryptor,
    create_database_engine,
    make_session_factory,
    run_migrations,
)
from drova_bot.telegram.middleware import RequestContextMiddleware
from drova_bot.telegram.routers import build_router

logger = structlog.get_logger(__name__)

BOT_COMMANDS = [
    BotCommand(command="start", description="Подключение и состояние бота"),
    BotCommand(command="help", description="Справка по командам"),
    BotCommand(command="token", description="Подключить Drova proxy token"),
    BotCommand(command="logout", description="Удалить токен и настройки"),
    BotCommand(command="station", description="Выбрать станцию"),
    BotCommand(command="station_all", description="Выбрать все станции"),
    BotCommand(command="limit", description="Настроить лимит сессий"),
    BotCommand(command="sessions", description="Последние сессии"),
    BotCommand(command="sessions_short", description="Сессии дольше 5 минут"),
    BotCommand(command="current", description="Текущее состояние станций"),
    BotCommand(command="account", description="Баланс минут и выплаты"),
    BotCommand(command="usage", description="Статистика использования"),
    BotCommand(command="disabled", description="Проблемы с продуктами"),
    BotCommand(command="stations", description="Станции и эндпоинты"),
    BotCommand(command="games", description="Игры выбранной станции"),
    BotCommand(command="game", description="Параметры запуска игры"),
    BotCommand(command="game_hide", description="Скрыть игру на станции"),
    BotCommand(command="game_show", description="Открыть игру на станции"),
    BotCommand(command="game_hide_all", description="Скрыть игру на всех станциях"),
    BotCommand(command="desktop_on", description="Включить полный доступ"),
    BotCommand(command="desktop_off", description="Выключить полный доступ"),
    BotCommand(command="updates_on", description="Включить обновления"),
    BotCommand(command="updates_off", description="Выключить обновления"),
    BotCommand(command="promocode", description="Выпустить prepaid-промокод"),
    BotCommand(command="promocodes", description="Неактивированные промокоды"),
    BotCommand(command="export_sessions", description="Сессии одним XLSX"),
    BotCommand(command="export_sessions_csv", description="Сессии CSV по станциям"),
    BotCommand(command="export_products", description="Матрица продуктов XLSX"),
    BotCommand(command="export_product_time", description="Время по продуктам XLSX"),
]


@dataclass(slots=True)
class Runtime:
    bot: Bot
    dispatcher: Dispatcher
    engine: AsyncEngine
    geo_resolver: GeoLiteResolver | None = None

    async def close(self) -> None:
        await self.bot.session.close()
        if self.geo_resolver is not None:
            self.geo_resolver.close()
        await self.engine.dispose()


def build_runtime(settings: Settings) -> Runtime:
    """Create the concrete aiogram and storage runtime graph."""
    settings.require_runtime_secrets()
    engine = create_database_engine(settings.database_url)
    session_factory = make_session_factory(engine)
    encryptor = TokenEncryptor(settings.bot_secret_key or "")
    uow_factory = StorageUnitOfWorkFactory(session_factory, encryptor)
    geo_resolver = GeoLiteResolver(
        city_db_path=settings.geolite_city_db,
        asn_db_path=settings.geolite_asn_db,
    )
    service = BotService(
        uow_factory=uow_factory,
        client_factory=DefaultDrovaClientFactory(settings),
        export_row_limit=settings.export_row_limit,
        export_timeout_seconds=settings.export_timeout_seconds,
        session_geo_resolver=geo_resolver.lookup_session,
    )

    bot = Bot(token=settings.telegram_bot_token or "")
    dispatcher = Dispatcher()
    request_context = RequestContextMiddleware()
    dispatcher.message.middleware(request_context)
    dispatcher.callback_query.middleware(request_context)
    dispatcher.include_router(build_router())
    dispatcher["bot_service"] = service
    return Runtime(bot=bot, dispatcher=dispatcher, engine=engine, geo_resolver=geo_resolver)


async def register_bot_commands(bot: Bot) -> None:
    """Register BotFather command list from runtime code."""
    await bot.set_my_commands(BOT_COMMANDS)


async def run_polling(settings: Settings) -> None:
    """Start aiogram polling and close runtime resources on shutdown."""
    runtime = build_runtime(settings)
    try:
        await register_bot_commands(runtime.bot)
        await runtime.dispatcher.start_polling(
            runtime.bot,
            allowed_updates=runtime.dispatcher.resolve_used_update_types(),
        )
    finally:
        await runtime.close()


def main() -> None:
    """Validate config, migrate storage, and run the Telegram polling loop."""
    settings = Settings()
    configure_logging(settings.log_level)
    settings.require_runtime_secrets()
    logger.info(
        "bot_starting",
        database_url=_safe_database_url(settings.database_url),
        drova_base_url=settings.drova_base_url,
        timezone=settings.timezone,
        export_row_limit=settings.export_row_limit,
        export_timeout_seconds=settings.export_timeout_seconds,
        geolite_city_db_configured=bool(settings.geolite_city_db),
        geolite_asn_db_configured=bool(settings.geolite_asn_db),
        http_proxy_configured=settings.http_proxy is not None,
        https_proxy_configured=settings.https_proxy is not None,
    )
    run_migrations(settings.database_url)
    asyncio.run(run_polling(settings))


def _safe_database_url(database_url: str) -> str:
    return make_url(database_url).render_as_string(hide_password=True)


if __name__ == "__main__":
    main()
