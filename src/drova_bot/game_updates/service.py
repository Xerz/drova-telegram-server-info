"""Subscription application behavior, independent of aiogram transport."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from drova_bot.game_updates.renderers import MODES, render_panel
from drova_bot.game_updates.storage import NotificationStore, chat_lock
from drova_bot.telegram.callbacks import ParsedCallback
from drova_bot.telegram.renderers import RenderedMessage, render_error


class GameUpdatesService:
    def __init__(
        self,
        store: NotificationStore,
        *,
        enabled: bool,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.store = store
        self.enabled = enabled
        self.clock = clock or (lambda: datetime.now(UTC))

    async def panel(
        self, chat_id: int, *, search: str | None = None, page: int = 0
    ) -> RenderedMessage:
        async with chat_lock(chat_id):
            if search is not None and self.enabled and await self.store.profile(chat_id):
                await self.store.search(chat_id, search)
            return await self._panel(chat_id, page)

    async def _panel(self, chat_id: int, page: int) -> RenderedMessage:
        profile = await self.store.profile(chat_id)
        if profile is None:
            return render_error("not_connected")
        if not self.enabled:
            return RenderedMessage("Сервис уведомлений об обновлениях игр выключен оператором.")
        feed, fetched_at = await self.store.feed()
        return render_panel(
            feed,
            await self.store.settings(chat_id),
            page=page,
            fetched_at=fetched_at,
            now=self.clock(),
            timezone=profile.timezone,
        )

    async def callback(self, chat_id: int, callback: ParsedCallback) -> RenderedMessage:
        async with chat_lock(chat_id):
            if not self.enabled or await self.store.profile(chat_id) is None:
                return await self._panel(chat_id, 0)
            if callback.action == "game_updates_mode":
                if callback.control not in MODES:
                    return render_error("unknown_command")
                await self.store.set_mode(chat_id, callback.control or "off", self.clock())
            elif callback.action in {"game_updates_add", "game_updates_remove"}:
                try:
                    appid = int(callback.product_id or "")
                except ValueError:
                    return render_error("unknown_command")
                feed, _ = await self.store.feed()
                sub = await self.store.settings(chat_id)
                if appid not in {g.appid for g in feed.games} and appid not in sub.selected:
                    return RenderedMessage("Игра больше не доступна в каталоге. Обновите список.")
                await self.store.select(
                    chat_id, appid, callback.action == "game_updates_add", self.clock()
                )
            elif callback.action not in {"game_updates", "game_updates_page"}:
                return render_error("unknown_command")
            return await self._panel(chat_id, callback.page or 0)
