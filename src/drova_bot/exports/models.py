"""Export DTOs and constants."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ExportKind(StrEnum):
    SESSIONS = "sessions"
    SESSIONS_CSV = "sessions_csv"
    PRODUCTS = "products"
    PRODUCT_TIME = "product_time"


@dataclass(frozen=True, slots=True)
class ExportFile:
    filename: str
    content_type: str
    payload: bytes


@dataclass(frozen=True, slots=True)
class ExportResult:
    files: list[ExportFile]
    message: str

