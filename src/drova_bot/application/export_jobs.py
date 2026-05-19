"""Application DTOs for export job lifecycle."""

from __future__ import annotations

from dataclasses import dataclass

from drova_bot.exports import ExportKind


@dataclass(frozen=True, slots=True)
class ExportJob:
    id: str
    telegram_chat_id: int
    kind: ExportKind
    status: str
    error_code: str | None = None
