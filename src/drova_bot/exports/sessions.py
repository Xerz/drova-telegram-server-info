"""Session export boundary for the first V2 slice."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class ExportFile:
    filename: str
    content_type: str
    payload: bytes


class SessionExportService:
    """Placeholder service boundary; XLSX generation lands after renderer/storage base."""

    def sessions_filename(self, now: datetime) -> str:
        return f"drova-sessions-{now.strftime('%Y%m%d-%H%M%S')}.xlsx"

