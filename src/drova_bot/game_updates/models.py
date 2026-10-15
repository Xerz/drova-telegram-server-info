"""Versioned public metadata contracts, including legacy Steam payload decoding."""

from __future__ import annotations

import re
from typing import Any, Literal
from urllib.parse import urlsplit

from pydantic import AwareDatetime, BaseModel, Field, field_validator, model_validator

from drova_bot.domain.models import CatalogProduct

PROVIDERS = {"steam", "hoyo", "wuwa", "endfield", "battlenet", "bsg", "epic"}
LABELS = {
    "steam": "Steam",
    "hoyo": "HoYoverse",
    "wuwa": "WuWa",
    "endfield": "Endfield",
    "battlenet": "Battle.net",
    "bsg": "BSG",
    "epic": "Epic Games",
}


def object_id(value: str | int) -> str:
    value = str(value)
    return f"steam:{value}" if value.isascii() and value.isdecimal() else value


class UpdateObject(BaseModel):
    id: str = Field(default="", max_length=40, pattern=r"^[a-z0-9:_-]*$")
    appid: int | None = Field(default=None, gt=0, le=4294967295)
    provider: Literal["steam", "hoyo", "wuwa", "endfield", "battlenet", "bsg", "epic"] = "steam"
    external_id: str = ""
    platform: Literal["windows"] = "windows"
    channel: str = "public"
    kind: Literal["game", "resources", "launcher"] = "game"
    title: str = Field(min_length=1, max_length=1000)
    related_games: list[str] = Field(default_factory=list)
    linked_objects: list[str] = Field(default_factory=list)
    coverage: Literal["full", "launcher_only"] = "full"
    news_url: str = Field(default="", max_length=500)
    version: str | None = Field(default=None, max_length=100)
    buildid: str | None = Field(default=None, max_length=256)
    last_success_at: AwareDatetime | None = None
    error_code: str | None = None

    @model_validator(mode="before")
    @classmethod
    def legacy(cls, raw: Any) -> Any:
        if isinstance(raw, dict) and raw.get("appid") and not raw.get("id"):
            raw = dict(raw)
            raw["id"] = f"steam:{raw['appid']}"
            raw.setdefault("external_id", str(raw["appid"]))
            raw.setdefault("news_url", f"https://store.steampowered.com/news/app/{raw['appid']}")
        return raw

    @model_validator(mode="after")
    def identity(self) -> UpdateObject:
        if not self.id or not self.id.startswith(self.provider + ":"):
            raise ValueError("invalid_object_identity")
        if self.provider == "steam" and self.id != f"steam:{self.appid}":
            raise ValueError("invalid_steam_identity")
        if self.provider != "steam" and self.appid is not None:
            raise ValueError("nonsteam_appid")
        if self.news_url:
            url = urlsplit(self.news_url)
            if url.scheme != "https" or not url.hostname or url.username or url.password:
                raise ValueError("invalid_news_url")
        return self


class ProviderStatus(BaseModel):
    checked_at: AwareDatetime | None = None
    total: int = 0
    covered: int = 0
    unmapped: int = 0
    error_code: str | None = None


class GameFeed(BaseModel):
    games: list[UpdateObject]
    objects: list[UpdateObject] = Field(default_factory=list)
    providers: dict[str, ProviderStatus] = Field(default_factory=dict)
    catalog_updated_at: AwareDatetime | None = None
    checked_at: AwareDatetime | None = None


class UpdateEvent(UpdateObject):
    stream_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    seq: int = Field(gt=0)
    branch: str = "public"
    previous_buildid: str = Field(min_length=1, max_length=256)
    buildid: str = Field(min_length=1, max_length=256)
    observed_at: AwareDatetime

    @model_validator(mode="after")
    def steam_builds(self) -> UpdateEvent:
        if self.provider == "steam" and any(
            not b.isascii() or not b.isdecimal() or int(b) <= 0
            for b in (self.previous_buildid, self.buildid)
        ):
            raise ValueError("invalid_steam_buildid")
        return self


class EventPage(BaseModel):
    events: list[UpdateEvent]
    next_cursor: str
    has_more: bool


class Subscription(BaseModel):
    mode: Literal["off", "selected", "all", "all_supported"] = "off"
    enabled_since: float = 0
    selected: dict[str, float] = Field(default_factory=dict)
    suspended: bool = False
    search: str = ""
    last_digest_hour: int = 0

    @field_validator("selected", mode="before")
    @classmethod
    def legacy_selection(cls, value: Any) -> Any:
        return {object_id(k): v for k, v in value.items()} if isinstance(value, dict) else value

    def accepts(self, event: UpdateEvent) -> bool:
        observed = event.observed_at.timestamp()
        if self.suspended or self.mode == "off" or observed <= self.enabled_since:
            return False
        if self.mode == "all":
            return event.provider == "steam"
        if self.mode == "all_supported":
            return event.kind == "game" or bool(event.related_games)
        ids = [event.id] if event.kind == "game" else event.related_games
        return any(i in self.selected and observed > self.selected[i] for i in ids)


# Source-compatible names for the Steam transport and existing integrations.
SteamGame = UpdateObject
SteamEvent = UpdateEvent


def steam_games(products: list[CatalogProduct]) -> list[SteamGame]:
    """Map only explicit Steam products; never infer app IDs from game names."""
    games: dict[int, SteamGame] = {}
    for product in sorted(products, key=lambda p: (p.title.casefold(), p.product_id)):
        if product.required_account != "Steam" or not product.in_shop_url:
            continue
        try:
            url = urlsplit(product.in_shop_url)
            match = re.fullmatch(r"/app/([0-9]+)(?:/.*)?", url.path)
            if (
                url.scheme not in {"http", "https"}
                or url.hostname != "store.steampowered.com"
                or url.username
                or url.password
                or url.port not in {None, 80, 443}
                or not match
            ):
                continue
            appid = int(match[1])
            if 0 < appid <= 4294967295 and product.title.strip():
                games.setdefault(appid, SteamGame(appid=appid, title=product.title[:1000]))
        except ValueError:
            continue
    return list(games.values())
