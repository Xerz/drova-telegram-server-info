"""Framework-neutral keyboard specs for renderers."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ButtonSpec:
    text: str
    callback_data: str


@dataclass(frozen=True, slots=True)
class KeyboardSpec:
    rows: list[list[ButtonSpec]]

