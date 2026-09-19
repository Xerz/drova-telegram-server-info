"""Single non-overlapping catalog and Steam observation loop."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from datetime import UTC, datetime

import structlog

from drova_bot.application.protocols import DrovaClientProtocol
from drova_bot.game_updates.models import steam_games
from drova_bot.steam_watcher.steamcmd import SteamCmd, SteamMetadataError
from drova_bot.steam_watcher.storage import WatcherStore

logger = structlog.get_logger(__name__)


class Watcher:
    def __init__(
        self,
        store: WatcherStore,
        catalog: DrovaClientProtocol,
        steam: SteamCmd,
        *,
        clock: Callable[[], datetime] | None = None,
        poll_seconds: float = 300,
        catalog_seconds: float = 3600,
    ) -> None:
        self.store, self.catalog, self.steam = store, catalog, steam
        self.clock = clock or (lambda: datetime.now(UTC))
        self.poll_seconds, self.catalog_seconds = poll_seconds, catalog_seconds
        self.last_catalog: datetime | None = None

    async def cycle(self) -> bool:
        started = time.monotonic()
        now = self.clock()
        if (
            self.last_catalog is None
            or (now - self.last_catalog).total_seconds() >= self.catalog_seconds
        ):
            try:
                products = await self.catalog.get_products_full()
                await self.store.replace_games(steam_games(products), now)
                self.last_catalog = now
            except Exception:
                logger.warning("steam_catalog_unavailable", error_code="catalog_failed")
        feed = await self.store.games()
        feed.games = [g for g in feed.games if g.provider == "steam"]
        if not feed.games:
            return False
        errors = 0
        try:
            await self.steam.refresh()
        except SteamMetadataError:
            for game in feed.games:
                await self.store.record_error(game.id, "steamcmd_refresh")
            logger.warning("steam_refresh_failed", games=len(feed.games))
            return False
        transport_ok = True
        for index, game in enumerate(feed.games):
            try:
                assert game.appid is not None
                buildid = await self.steam.buildid(game.appid)
                await self.store.observe(game.appid, buildid, self.clock())
            except SteamMetadataError as exc:
                if str(exc) in {"steamcmd_start", "steamcmd_transport"}:
                    transport_ok = False
                    for remaining in feed.games[index:]:
                        errors += 1
                        await self.store.record_error(remaining.id, "steamcmd_transport")
                    break
                errors += 1
                await self.store.record_error(game.id, "metadata_unavailable")
        await self.store.mark_checked(self.clock())
        logger.info(
            "steam_cycle_complete",
            games=len(feed.games),
            errors=errors,
            duration_ms=round((time.monotonic() - started) * 1000),
        )
        return transport_ok

    async def run(self) -> None:
        failures = 0
        while True:
            started = time.monotonic()
            try:
                success = await self.cycle()
                failures = 0 if success else failures + 1
            except Exception:
                failures += 1
                logger.error("steam_cycle_failed", error_code="cycle_failed")
            interval = (
                self.poll_seconds
                if failures == 0
                else min(1800, self.poll_seconds * 2 ** min(failures - 1, 8))
            )
            await asyncio.sleep(max(1, interval - (time.monotonic() - started)))
