"""Stable callback payload helpers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CallbackSpec:
    action: str
    station_id: str | None = None
    page: int | None = None
    expected_published: bool | None = None

    def pack(self) -> str:
        parts = [self.action]
        if self.station_id is not None:
            parts.append(f"station={self.station_id}")
        if self.page is not None:
            parts.append(f"page={self.page}")
        if self.expected_published is not None:
            parts.append(f"published={int(self.expected_published)}")
        return "|".join(parts)

