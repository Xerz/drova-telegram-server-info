"""Telegram delivery helpers for rendered messages."""

from __future__ import annotations

from html import unescape
from typing import Any, cast

import structlog
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from drova_bot.drova.errors import TelegramDeliveryFailed
from drova_bot.exports import ExportFile
from drova_bot.telegram.keyboards import KeyboardSpec
from drova_bot.telegram.renderers import RenderedMessage

logger = structlog.get_logger(__name__)


def to_aiogram_keyboard(keyboard: KeyboardSpec | None) -> InlineKeyboardMarkup | None:
    if keyboard is None:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=button.text, callback_data=button.callback_data)
                for button in row
            ]
            for row in keyboard.rows
        ]
    )


async def answer_rendered(message: Message, rendered: RenderedMessage) -> Any:
    markup = to_aiogram_keyboard(rendered.keyboard)
    try:
        return await message.answer(
            rendered.text,
            parse_mode=rendered.parse_mode,
            reply_markup=markup,
        )
    except TelegramBadRequest:
        logger.warning("telegram_html_fallback")
        try:
            return await message.answer(
                _plain_text(rendered.text),
                parse_mode=None,
                reply_markup=markup,
            )
        except TelegramBadRequest as exc:
            raise TelegramDeliveryFailed("telegram answer failed after fallback") from exc


async def edit_rendered_message(message: Message, rendered: RenderedMessage) -> Any:
    markup = to_aiogram_keyboard(rendered.keyboard)
    try:
        return await message.edit_text(
            rendered.text,
            parse_mode=rendered.parse_mode,
            reply_markup=markup,
        )
    except TelegramBadRequest:
        logger.warning("telegram_html_fallback")
        try:
            return await message.edit_text(
                _plain_text(rendered.text),
                parse_mode=None,
                reply_markup=markup,
            )
        except TelegramBadRequest as exc:
            raise TelegramDeliveryFailed("telegram edit failed after fallback") from exc


async def edit_or_answer_rendered(callback: CallbackQuery, rendered: RenderedMessage) -> Any:
    markup = to_aiogram_keyboard(rendered.keyboard)
    if callback.message is None:
        return await callback.answer(_plain_text(rendered.text), show_alert=True)
    message = cast(Message, callback.message)
    try:
        return await message.edit_text(
            rendered.text,
            parse_mode=rendered.parse_mode,
            reply_markup=markup,
        )
    except TelegramBadRequest:
        logger.warning("telegram_html_fallback")
        try:
            return await message.edit_text(
                _plain_text(rendered.text),
                parse_mode=None,
                reply_markup=markup,
            )
        except TelegramBadRequest as exc:
            raise TelegramDeliveryFailed("telegram callback edit failed after fallback") from exc


async def send_export_file(message: Message, export_file: ExportFile) -> Any:
    try:
        return await message.answer_document(
            BufferedInputFile(export_file.payload, filename=export_file.filename),
        )
    except TelegramBadRequest as exc:
        raise TelegramDeliveryFailed("telegram document delivery failed") from exc


def _plain_text(text: str) -> str:
    return unescape(text)
