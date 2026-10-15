"""Button-first feedback settings, without API calls in handlers."""

from drova_bot.feedback_notifications.renderers import render_panel
from drova_bot.feedback_notifications.storage import FeedbackStore
from drova_bot.telegram.renderers import RenderedMessage, render_error


class FeedbackService:
    def __init__(self, store: FeedbackStore) -> None:
        self.store = store

    async def panel(self, chat_id: int) -> RenderedMessage:
        if not await self.store.connected(chat_id):
            return render_error("not_connected")
        return render_panel(await self.store.settings(chat_id))

    async def set_enabled(self, chat_id: int, enabled: bool) -> RenderedMessage:
        if not await self.store.connected(chat_id):
            return render_error("not_connected")
        return render_panel(await self.store.set_enabled(chat_id, enabled))
