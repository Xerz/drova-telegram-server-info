"""Production runtime entrypoint for Drova Bot V2."""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass

import structlog
from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine

from drova_bot.application.services import BotService, DefaultDrovaClientFactory
from drova_bot.config import Settings
from drova_bot.feedback_notifications.service import FeedbackService
from drova_bot.feedback_notifications.storage import FeedbackStore
from drova_bot.feedback_notifications.worker import FeedbackWorker, TelegramFeedbackSender
from drova_bot.game_updates.client import WatcherClient
from drova_bot.game_updates.service import GameUpdatesService
from drova_bot.game_updates.storage import NotificationStore
from drova_bot.game_updates.worker import NotificationWorker, TelegramDigestSender
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
    BotCommand(command="sessions", description="Последние сессии"),
    BotCommand(command="current", description="Текущее состояние станций"),
    BotCommand(command="account_menu", description="Меню аккаунта"),
    BotCommand(command="usage", description="Статистика использования"),
    BotCommand(command="help", description="Справка по командам"),
    BotCommand(command="start", description="Подключение и состояние бота"),
    BotCommand(command="token", description="Подключить Drova proxy token"),
    BotCommand(command="logout", description="Удалить токен и настройки"),
    BotCommand(command="station", description="Выбрать станцию"),
    BotCommand(command="station_all", description="Выбрать все станции"),
    BotCommand(command="station_manage", description="Меню управления станцией"),
    BotCommand(command="limit", description="Настроить лимит сессий"),
    BotCommand(command="sessions_short", description="Сессии дольше 5 минут"),
    BotCommand(command="account", description="Баланс минут и выплаты"),
    BotCommand(command="disabled", description="Проблемы с продуктами"),
    BotCommand(command="stations", description="Станции и эндпоинты"),
    BotCommand(command="games", description="Выбрать игру на станции"),
    BotCommand(command="desktop_on", description="Включить полный доступ"),
    BotCommand(command="desktop_off", description="Выключить полный доступ"),
    BotCommand(command="updates_on", description="Включить обновления"),
    BotCommand(command="updates_off", description="Выключить обновления"),
    BotCommand(command="server_source", description="Исходник описания станции"),
    BotCommand(command="server_description", description="Обновить описание станции"),
    BotCommand(command="promocode", description="Выпустить prepaid-промокод"),
    BotCommand(command="promocodes", description="Неактивированные промокоды"),
    BotCommand(command="export_sessions", description="Сессии одним XLSX"),
    BotCommand(command="export_sessions_csv", description="Сессии CSV по станциям"),
    BotCommand(command="export_products", description="Матрица продуктов XLSX"),
    BotCommand(command="export_product_time", description="Время по продуктам XLSX"),
    BotCommand(command="game_updates", description="Обновления игр в Steam"),
    BotCommand(command="feedback_notifications", description="Уведомления об отзывах"),
]


@dataclass(slots=True)
class Runtime:
    bot: Bot
    dispatcher: Dispatcher
    engine: AsyncEngine
    geo_resolver: GeoLiteResolver | None = None

    watcher_client: WatcherClient | None = None
    notification_worker: NotificationWorker | None = None
    notification_task: asyncio.Task[None] | None = None
    feedback_worker: FeedbackWorker | None = None
    feedback_task: asyncio.Task[None] | None = None

    def start_background(self) -> None:
        if self.feedback_worker is not None:
            self.feedback_task = asyncio.create_task(
                self.feedback_worker.run(), name="feedback-notifications"
            )
        if self.notification_worker is not None:
            self.notification_task = asyncio.create_task(
                self.notification_worker.run(), name="steam-notifications"
            )

    async def close(self) -> None:
        if self.feedback_task is not None:
            self.feedback_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.feedback_task
        if self.feedback_worker is not None:
            await self.feedback_worker.close()
        if self.notification_task is not None:
            self.notification_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.notification_task
        if self.watcher_client is not None:
            await self.watcher_client.close()
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
    notification_store = NotificationStore(session_factory)
    updates_service = GameUpdatesService(notification_store, enabled=settings.game_updates_enabled)
    feedback_store = FeedbackStore(session_factory, encryptor)
    client_factory = DefaultDrovaClientFactory(settings)
    service = BotService(
        feedback_service=FeedbackService(feedback_store),
        game_updates_service=updates_service,
        uow_factory=uow_factory,
        client_factory=client_factory,
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
    runtime = Runtime(bot=bot, dispatcher=dispatcher, engine=engine, geo_resolver=geo_resolver)
    runtime.feedback_worker = FeedbackWorker(
        feedback_store, client_factory, TelegramFeedbackSender(bot)
    )
    if settings.game_updates_enabled:
        assert settings.steam_watcher_token is not None
        runtime.watcher_client = WatcherClient(
            settings.steam_watcher_url, settings.steam_watcher_token.get_secret_value()
        )
        runtime.notification_worker = NotificationWorker(
            notification_store, runtime.watcher_client, TelegramDigestSender(bot)
        )
    return runtime


async def register_bot_commands(bot: Bot) -> None:
    """Register BotFather command list from runtime code."""
    await bot.set_my_commands(BOT_COMMANDS)


async def run_polling(settings: Settings) -> None:
    """Start aiogram polling and close runtime resources on shutdown."""
    runtime = build_runtime(settings)
    try:
        await register_bot_commands(runtime.bot)
        runtime.start_background()
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
