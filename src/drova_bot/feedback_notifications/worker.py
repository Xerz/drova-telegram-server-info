"""Independent per-chat scans and recoverable Telegram delivery."""

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
from cryptography.fernet import InvalidToken

from drova_bot.application.protocols import DrovaClientFactory
from drova_bot.drova.errors import DrovaPermissionDenied, DrovaUnauthorized, DrovaUnavailable
from drova_bot.feedback_notifications.models import StaleFeedbackContext, has_feedback
from drova_bot.feedback_notifications.renderers import render_notification
from drova_bot.feedback_notifications.storage import FeedbackStore
from drova_bot.storage.locks import chat_lock
from drova_bot.telegram.middleware import hash_chat_id

logger = structlog.get_logger(__name__)


class FeedbackSender(Protocol):
    async def send(self, chat_id: int, text: str) -> None: ...


class TelegramFeedbackSender:
    def __init__(self, bot: Bot) -> None:
        self.bot = bot

    async def send(self, chat_id: int, text: str) -> None:
        options = LinkPreviewOptions(is_disabled=True)
        try:
            await self.bot.send_message(
                chat_id, text, parse_mode="HTML", link_preview_options=options, request_timeout=15
            )
        except TelegramBadRequest as exc:
            if not any(
                s in exc.message.lower()
                for s in ("parse entities", "unsupported start tag", "entity")
            ):
                raise
            logger.warning("feedback_html_fallback", chat_id_hash=hash_chat_id(chat_id))
            plain = unescape(re.sub(r"</?(?:b|code)>", "", text))
            await self.bot.send_message(
                chat_id, plain, parse_mode=None, link_preview_options=options, request_timeout=15
            )


class FeedbackWorker:
    def __init__(
        self,
        store: FeedbackStore,
        factory: DrovaClientFactory,
        sender: FeedbackSender,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.store, self.factory, self.sender = store, factory, sender
        self.clock = clock or (lambda: datetime.now(UTC))
        self.semaphore = asyncio.Semaphore(4)
        self.tasks: dict[int, asyncio.Task[None]] = {}

    async def scan(self, chat_id: int) -> None:
        async with self.semaphore:
            ctx = await self.store.begin_poll(chat_id, self.clock())
            if ctx is None:
                return
            client = None
            try:
                token = self.store.encryptor.decrypt(ctx.encrypted_token)

                async def persist_token(new_token: str) -> None:
                    await self.store.persist_token(ctx, new_token)

                client = self.factory.create(token, token_persister=persist_token)
                page = await client.get_sessions(merchant_id=ctx.account_id, limit=1000)
                sessions = page.sessions
                if any(s.merchant_id != ctx.account_id for s in sessions) or len(
                    {s.uuid for s in sessions}
                ) != len(sessions):
                    raise DrovaUnavailable("invalid_feedback_snapshot")
                reviews = sorted(
                    (
                        s
                        for s in sessions
                        if s.finished_on_ms is not None and has_feedback(s.score, s.score_text)
                    ),
                    key=lambda s: s.created_on_ms,
                )
                stations, products = await self.store.names(chat_id)
                if reviews and (
                    any(s.server_id not in stations for s in reviews)
                    or any(s.product_id not in products for s in reviews)
                ):
                    try:
                        new_stations = await client.get_servers(ctx.account_id)
                        new_products = await client.get_products_full()
                        await self.store.cache_names(ctx, new_stations, new_products)
                        stations, products = await self.store.names(chat_id)
                    except (DrovaUnavailable, DrovaUnauthorized, DrovaPermissionDenied):
                        pass  # Names are best-effort; feedback itself is still valid.
                now = self.clock()
                messages = {
                    s.uuid: render_notification(
                        s, sessions, stations, products, now=now, timezone=ctx.timezone
                    )
                    for s in reviews
                }
                example = messages[reviews[-1].uuid][0] if reviews else None
                count = await self.store.ingest(ctx, messages, example, now)
                logger.info(
                    "feedback_scan",
                    chat_id_hash=hash_chat_id(chat_id),
                    sessions=len(sessions),
                    accepted=count,
                )
            except (DrovaUnauthorized, DrovaPermissionDenied, InvalidToken):
                async with chat_lock(chat_id):
                    await self.store.suspend(chat_id, "auth", ctx)
                logger.warning(
                    "feedback_suspended", chat_id_hash=hash_chat_id(chat_id), error_code="auth"
                )
            except StaleFeedbackContext:
                pass
            except Exception:
                logger.warning(
                    "feedback_scan_failed",
                    chat_id_hash=hash_chat_id(chat_id),
                    error_code="scan_failed",
                )
            finally:
                if client is not None:
                    await client.aclose()

    async def deliver(self, chat_id: int) -> None:
        async with chat_lock(chat_id):
            for job in await self.store.pending(chat_id):
                now = self.clock()
                if job.next_attempt_at > now.timestamp():
                    break
                try:
                    await self.sender.send(chat_id, job.text)
                except TelegramForbiddenError:
                    await self.store.suspend(chat_id, "telegram")
                    break
                except TelegramRetryAfter as exc:
                    await self.store.retry(job.id, now, max(1, exc.retry_after))
                    break
                except Exception:
                    await self.store.retry(job.id, now, min(3600, 60 * 2 ** min(job.attempts, 6)))
                    logger.warning(
                        "feedback_delivery_retry",
                        chat_id_hash=hash_chat_id(chat_id),
                        error_code="delivery_failed",
                    )
                    break
                else:
                    await self.store.complete(job.id)
                    logger.info("feedback_sent", chat_id_hash=hash_chat_id(chat_id))

    async def _run_chat(self, chat_id: int) -> None:
        while True:
            try:
                await self.scan(chat_id)
                await self.deliver(chat_id)
            except Exception:
                logger.warning(
                    "feedback_chat_failed",
                    chat_id_hash=hash_chat_id(chat_id),
                    error_code="worker_failed",
                )
            await asyncio.sleep(5)

    async def reconcile(self) -> None:
        wanted = set(await self.store.eligible_chats())
        for chat_id in list(self.tasks):
            if chat_id not in wanted or self.tasks[chat_id].done():
                task = self.tasks.pop(chat_id)
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        for chat_id in wanted - self.tasks.keys():
            self.tasks[chat_id] = asyncio.create_task(self._run_chat(chat_id), name="feedback-chat")

    async def run(self) -> None:
        try:
            while True:
                try:
                    await self.reconcile()
                except Exception:
                    logger.error("feedback_supervisor_failed", error_code="storage_unavailable")
                await asyncio.sleep(5)
        finally:
            await self.close()

    async def close(self) -> None:
        tasks = list(self.tasks.values())
        self.tasks.clear()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
