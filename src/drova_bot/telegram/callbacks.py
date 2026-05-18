"""Stable callback payload helpers."""

from __future__ import annotations

from dataclasses import dataclass


class InvalidCallbackData(ValueError):
    """Callback payload does not match the stable V2 callback format."""


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


@dataclass(frozen=True, slots=True)
class ParsedCallback:
    action: str
    station_id: str | None = None
    page: int | None = None
    expected_published: bool | None = None


def parse_callback_data(data: str | None) -> ParsedCallback:
    if not data:
        raise InvalidCallbackData("empty callback data")
    raw_parts = data.split("|")
    action = raw_parts[0]
    if not action:
        raise InvalidCallbackData("missing action")

    values: dict[str, str] = {}
    for raw_part in raw_parts[1:]:
        key, separator, value = raw_part.partition("=")
        if not separator or not key:
            raise InvalidCallbackData("invalid callback part")
        values[key] = value

    page: int | None = None
    if "page" in values:
        try:
            page = int(values["page"])
        except ValueError as exc:
            raise InvalidCallbackData("invalid page") from exc

    expected_published: bool | None = None
    if "published" in values:
        if values["published"] not in {"0", "1"}:
            raise InvalidCallbackData("invalid published flag")
        expected_published = values["published"] == "1"

    return ParsedCallback(
        action=action,
        station_id=values.get("station"),
        page=page,
        expected_published=expected_published,
    )
