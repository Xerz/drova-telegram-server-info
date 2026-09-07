"""Recoverable source ingestion and hourly Telegram delivery."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable
from datetime import UTC, datetime
from html import unescape
from typing import Protocol

import structlog
from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import LinkPreviewOptions

from drova_bot.game_updates.client import WatcherClient, WatcherUnavailable
from drova_bot.game_updates.storage import NotificationStore, chat_lock
from drova_bot.steam_watcher.storage import CursorConflict
from drova_bot.telegram.middleware import hash_chat_id

logger = structlog.get_logger(__name__)


class DigestSender(Protocol):
    async def send(self, chat_id: int, text: str) -> None: ...


class TelegramDigestSender:
    def __init__(self, bot: Bot) -> None:
        self.bot = bot

    async def send(self, chat_id: int, text: str) -> None:
        try:
            await self.bot.send_message(
                chat_id,
                text,
                parse_mode="HTML",
                link_preview_options=LinkPreviewOptions(is_disabled=True),
                request_timeout=15,
            )
        except TelegramBadRequest as exc:
            if not any(
                marker in exc.message.lower()
                for marker in ("parse entities", "unsupported start tag", "entity")
            ):
                raise
            logger.warning("telegram_digest_html_fallback", chat_id_hash=hash_chat_id(chat_id))
            plain = re.sub(r'<a href="([^"]+)">([^<]*)</a>', r"\2 (\1)", text)
            plain = unescape(re.sub(r"</?b>", "", plain))
            await self.bot.send_message(
                chat_id,
                plain,
                parse_mode=None,
                link_preview_options=LinkPreviewOptions(is_disabled=True),
                request_timeout=15,
            )


class NotificationWorker:
    def __init__(
        self,
        store: NotificationStore,
        client: WatcherClient,
        sender: DigestSender,
        *,
        clock: Callable[[], datetime] | None = None,
        poll_seconds: float = 60,
    ) -> None:
        self.store = store
        self.client = client
        self.sender = sender
        self.clock = clock or (lambda: datetime.now(UTC))
        self.poll_seconds = poll_seconds

    async def tick(self) -> None:
        try:
            await self.store.replace_feed(await self.client.games(), self.clock())
        except WatcherUnavailable:
            logger.warning("steam_feed_unavailable")
        try:
            for _ in range(100):
                cursor = await self.store.cursor()
                try:
                    page = await self.client.events(cursor)
                except CursorConflict as exc:
                    await self.store.reset_cursor(exc.next_cursor)
                    logger.warning("steam_stream_reset")
                    continue
                if page.has_more and page.next_cursor == cursor:
                    raise WatcherUnavailable("non_advancing_cursor")
                await self.store.ingest(page)
                if not page.has_more:
                    break
            else:
                logger.warning("steam_feed_catching_up")
                return
        except (WatcherUnavailable, ValueError):
            logger.warning("steam_events_unavailable")
        await self.deliver(self.clock())

    async def deliver(self, now: datetime) -> None:
        for chat_id in await self.store.chats():
            async with chat_lock(chat_id):
                jobs = await self.store.prepare(chat_id, now)
                for job in jobs:
                    if job.next_attempt_at > now.timestamp():
                        break  # Preserve part order while an earlier part is backing off.
                    try:
                        await self.sender.send(chat_id, job.text)
                    except TelegramForbiddenError:
                        await self.store.suspend(chat_id)
                        logger.warning("steam_digest_suspended", chat_id_hash=hash_chat_id(chat_id))
                        break
                    except TelegramRetryAfter as exc:
                        await self.store.retry(job.id, now, max(1, exc.retry_after))
                        break
                    except Exception:
                        delay = min(3600, 60 * 2 ** min(job.attempts, 6))
                        await self.store.retry(job.id, now, delay)
                        logger.warning(
                            "steam_digest_retry",
                            chat_id_hash=hash_chat_id(chat_id),
                            error_code="telegram_delivery_failed",
                        )
                        break
                    else:
                        await self.store.complete(job.id)
                        logger.info(
                            "steam_digest_sent",
                            chat_id_hash=hash_chat_id(chat_id),
                            delay_seconds=max(0, now.timestamp() - job.created_at),
                        )

    async def run(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception:
                logger.error("steam_notification_worker_error", error_code="worker_failed")
            # Wake at minute boundaries so hourly delivery does not drift with IO duration.
            now = self.clock().timestamp()
            await asyncio.sleep(max(0.1, self.poll_seconds - now % self.poll_seconds))
