"""Stable callback payload helpers."""

from __future__ import annotations

from dataclasses import dataclass


class InvalidCallbackData(ValueError):
    """Callback payload does not match the stable V2 callback format."""


ACTION_ALIASES = {
    "station_all": "sa",
    "station_select": "ss",
    "station_page": "sp",
    "sessions_refresh": "sr",
    "sessions_short": "sh",
    "sessions_all": "sl",
    "current_refresh": "cr",
    "current_refresh_panel": "co",
    "publish_panel": "pp",
    "publish_hide": "ph",
    "publish_select": "ps",
    "publish_confirm": "pc",
    "publish_cancel": "px",
}
ACTION_BY_ALIAS = {alias: action for action, alias in ACTION_ALIASES.items()}
KEY_ALIASES = {
    "station": "s",
    "page": "p",
    "published": "e",
}
KEY_BY_ALIAS = {alias: key for key, alias in KEY_ALIASES.items()}


@dataclass(frozen=True, slots=True)
class CallbackSpec:
    action: str
    station_id: str | None = None
    page: int | None = None
    expected_published: bool | None = None

    def pack(self) -> str:
        parts = [_pack_action(self.action)]
        if self.station_id is not None:
            parts.append(f"{KEY_ALIASES['station']}={self.station_id}")
        if self.page is not None:
            parts.append(f"{KEY_ALIASES['page']}={self.page}")
        if self.expected_published is not None:
            parts.append(f"{KEY_ALIASES['published']}={int(self.expected_published)}")
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
    action = _unpack_action(raw_parts[0])
    if not action:
        raise InvalidCallbackData("missing action")

    values: dict[str, str] = {}
    for raw_part in raw_parts[1:]:
        key, separator, value = raw_part.partition("=")
        if not separator or not key:
            raise InvalidCallbackData("invalid callback part")
        values[_unpack_key(key)] = value

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


def _pack_action(action: str) -> str:
    return ACTION_ALIASES.get(action, action)


def _unpack_action(value: str) -> str:
    return ACTION_BY_ALIAS.get(value, value)


def _unpack_key(value: str) -> str:
    return KEY_BY_ALIAS.get(value, value)
