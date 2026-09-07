"""Public metadata contracts shared by the watcher and bot."""

from __future__ import annotations

import re
from typing import Literal
from urllib.parse import urlsplit

from pydantic import AwareDatetime, BaseModel, Field

from drova_bot.domain.models import CatalogProduct


class SteamGame(BaseModel):
    appid: int = Field(gt=0, le=4294967295)
    title: str = Field(min_length=1, max_length=1000)
    buildid: str | None = None
    last_success_at: AwareDatetime | None = None
    error_code: str | None = None


class GameFeed(BaseModel):
    games: list[SteamGame]
    catalog_updated_at: AwareDatetime | None = None
    checked_at: AwareDatetime | None = None


class SteamEvent(BaseModel):
    stream_id: str = Field(pattern=r"^[0-9a-f-]{36}$")
    seq: int = Field(gt=0)
    appid: int = Field(gt=0, le=4294967295)
    title: str = Field(min_length=1, max_length=1000)
    branch: Literal["public"] = "public"
    previous_buildid: str = Field(pattern=r"^[0-9]+$")
    buildid: str = Field(pattern=r"^[0-9]+$")
    observed_at: AwareDatetime


class EventPage(BaseModel):
    events: list[SteamEvent]
    next_cursor: str
    has_more: bool


class Subscription(BaseModel):
    mode: Literal["off", "selected", "all"] = "off"
    enabled_since: float = 0
    selected: dict[int, float] = Field(default_factory=dict)
    suspended: bool = False
    search: str = ""
    last_digest_hour: int = 0

    def accepts(self, event: SteamEvent) -> bool:
        observed = event.observed_at.timestamp()
        if self.suspended or self.mode == "off" or observed <= self.enabled_since:
            return False
        return self.mode == "all" or (
            event.appid in self.selected and observed > self.selected[event.appid]
        )


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
