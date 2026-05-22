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
    "sessions_page": "sg",
    "sessions_short_page": "sq",
    "current_refresh": "cr",
    "current_refresh_panel": "co",
    "publish_panel": "pp",
    "publish_hide": "ph",
    "publish_select": "ps",
    "publish_confirm": "pc",
    "publish_cancel": "px",
    "game_page": "gp",
    "game_select": "gs",
    "game_hide": "gh",
    "game_show": "gw",
    "game_hide_all": "ga",
    "game_hide_all_prompt": "gt",
    "game_hide_all_confirm": "gc",
    "station_manage_page": "mp",
    "station_manage_select": "ms",
    "station_panel": "mn",
    "station_publish_prompt": "mt",
    "station_publish_confirm": "mf",
    "station_control_toggle": "mo",
    "station_games": "mg",
    "station_source": "mx",
    "station_description_begin": "mb",
    "station_description_apply": "ma",
    "station_description_cancel": "mz",
    "account_menu": "am",
    "account_balance": "ab",
    "account_usage": "au",
    "account_promocodes": "ap",
}
ACTION_BY_ALIAS = {alias: action for action, alias in ACTION_ALIASES.items()}
KEY_ALIASES = {
    "station": "s",
    "product": "g",
    "page": "p",
    "published": "e",
    "expected": "x",
    "draft": "d",
    "control": "c",
}
KEY_BY_ALIAS = {alias: key for key, alias in KEY_ALIASES.items()}


@dataclass(frozen=True, slots=True)
class CallbackSpec:
    action: str
    station_id: str | None = None
    product_id: str | None = None
    page: int | None = None
    expected_published: bool | None = None
    expected_state: bool | None = None
    draft_id: str | None = None
    control: str | None = None

    def pack(self) -> str:
        parts = [_pack_action(self.action)]
        if self.station_id is not None:
            parts.append(f"{KEY_ALIASES['station']}={self.station_id}")
        if self.product_id is not None:
            parts.append(f"{KEY_ALIASES['product']}={self.product_id}")
        if self.page is not None:
            parts.append(f"{KEY_ALIASES['page']}={self.page}")
        if self.expected_published is not None:
            parts.append(f"{KEY_ALIASES['published']}={int(self.expected_published)}")
        if self.expected_state is not None:
            parts.append(f"{KEY_ALIASES['expected']}={int(self.expected_state)}")
        if self.draft_id is not None:
            parts.append(f"{KEY_ALIASES['draft']}={self.draft_id}")
        if self.control is not None:
            parts.append(f"{KEY_ALIASES['control']}={self.control}")
        return "|".join(parts)


@dataclass(frozen=True, slots=True)
class ParsedCallback:
    action: str
    station_id: str | None = None
    product_id: str | None = None
    page: int | None = None
    expected_published: bool | None = None
    expected_state: bool | None = None
    draft_id: str | None = None
    control: str | None = None


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

    expected_state: bool | None = None
    if "expected" in values:
        if values["expected"] not in {"0", "1"}:
            raise InvalidCallbackData("invalid expected flag")
        expected_state = values["expected"] == "1"

    return ParsedCallback(
        action=action,
        station_id=values.get("station"),
        product_id=values.get("product"),
        page=page,
        expected_published=expected_published,
        expected_state=expected_state,
        draft_id=values.get("draft"),
        control=values.get("control"),
    )


def _pack_action(action: str) -> str:
    return ACTION_ALIASES.get(action, action)


def _unpack_action(value: str) -> str:
    return ACTION_BY_ALIAS.get(value, value)


def _unpack_key(value: str) -> str:
    return KEY_BY_ALIAS.get(value, value)
