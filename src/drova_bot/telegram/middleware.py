"""Aiogram middleware for request-scoped structured logging context."""

from __future__ import annotations

import hashlib
import time
from collections.abc import Awaitable, Callable
from typing import Any
from uuid import uuid4

import structlog
from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

logger = structlog.get_logger(__name__)

Handler = Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]]


class RequestContextMiddleware(BaseMiddleware):
    """Attach non-sensitive request metadata to aiogram handler data and logs."""

    async def __call__(
        self,
        handler: Handler,
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        request_id = uuid4().hex
        chat_id_hash = hash_chat_id(_extract_chat_id(event))
        data["request_id"] = request_id
        data["chat_id_hash"] = chat_id_hash

        started_at = time.perf_counter()
        bound_logger = logger.bind(request_id=request_id, chat_id_hash=chat_id_hash)
        bound_logger.info("telegram_update_start")
        try:
            result = await handler(event, data)
        except Exception as exc:
            bound_logger.exception(
                "telegram_update_failed",
                duration_ms=_duration_ms(started_at),
                error_code=type(exc).__name__,
            )
            raise
        bound_logger.info("telegram_update_finished", duration_ms=_duration_ms(started_at))
        return result


AuthMiddleware = RequestContextMiddleware


def hash_chat_id(chat_id: int | None) -> str | None:
    if chat_id is None:
        return None
    return hashlib.sha256(str(chat_id).encode("ascii")).hexdigest()[:16]


def _extract_chat_id(event: TelegramObject) -> int | None:
    if isinstance(event, Message):
        return event.chat.id
    if isinstance(event, CallbackQuery):
        if event.message is not None:
            return event.message.chat.id
        return event.from_user.id
    return None


def _duration_ms(started_at: float) -> int:
    return round((time.perf_counter() - started_at) * 1000)
