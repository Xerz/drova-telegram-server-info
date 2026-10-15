"""Independent provider schedules and catalog refresh, isolated from Telegram."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

import structlog

from drova_bot.application.protocols import DrovaClientProtocol
from drova_bot.game_updates.models import UpdateObject
from drova_bot.steam_watcher.epic import SAFE_EPIC_ERRORS
from drova_bot.steam_watcher.providers import MetadataClient, MetadataError, Observation, observe
from drova_bot.steam_watcher.registry import catalog_objects
from drova_bot.steam_watcher.steamcmd import SteamCmd, SteamMetadataError
from drova_bot.steam_watcher.storage import WatcherStore

log = structlog.get_logger(__name__)


async def periodic(cycle: Callable[[], Awaitable[bool]], seconds: float) -> None:
    failures = 0
    while True:
        started = time.monotonic()
        try:
            failures = 0 if await cycle() else failures + 1
        except Exception:
            failures += 1
            log.error("update_cycle_failed", error_code="cycle_failed")
        delay = min(max(1800, seconds), seconds * 2 ** min(max(failures - 1, 0), 8))
        await asyncio.sleep(max(1, delay - (time.monotonic() - started)))


class CatalogLoop:
    def __init__(
        self, store: WatcherStore, catalog: DrovaClientProtocol, enabled: set[str]
    ) -> None:
        self.store, self.catalog, self.enabled = store, catalog, enabled

    async def cycle(self) -> bool:
        try:
            products = await self.catalog.get_products_full()
            if not products:
                raise ValueError("empty_catalog")
            objects, unmapped = catalog_objects(products, self.enabled)
            await self.store.replace_objects(objects, datetime.now(UTC), unmapped=unmapped)
            return True
        except Exception:
            log.warning("update_catalog_unavailable", error_code="catalog_failed")
            return False


class ProviderLoop:
    def __init__(
        self,
        provider: str,
        store: WatcherStore,
        *,
        steam: SteamCmd | None = None,
        proxy: str | None = None,
        limiter: asyncio.Semaphore | None = None,
        epic_client_id: str = "",
        epic_client_secret: str = "",
        probe: Callable[[MetadataClient, UpdateObject], Awaitable[Observation]] = observe,
    ) -> None:
        self.provider, self.store, self.steam = provider, store, steam
        from drova_bot.steam_watcher.epic import EpicClient

        self.client = (
            EpicClient(
                client_id=epic_client_id,
                client_secret=epic_client_secret,
                proxy=proxy,
                limiter=limiter,
            )
            if provider == "epic"
            else MetadataClient(proxy=proxy, limiter=limiter)
        )
        self.probe = probe

    async def close(self) -> None:
        await self.client.http.aclose()

    async def cycle(self) -> bool:
        started = time.monotonic()
        objects = [
            o
            for o in (await self.store.games()).objects
            if o.provider == self.provider and o.coverage == "full"
        ]
        self.client.clear()
        errors = 0
        error_code = "metadata_unavailable"
        if self.provider == "steam" and objects:
            assert self.steam
            try:
                await self.steam.refresh()
            except SteamMetadataError:
                for obj in objects:
                    await self.store.record_error(obj.id, "steamcmd_refresh")
                await self.store.mark_checked(datetime.now(UTC), self.provider, "steamcmd_refresh")
                return False
        for index, obj in enumerate(objects):
            try:
                if self.provider == "steam":
                    assert self.steam and obj.appid is not None
                    build = await self.steam.buildid(obj.appid)
                    result = Observation(build, build)
                else:
                    result = await self.probe(self.client, obj)
                await self.store.observe(
                    obj.id, result.fingerprint, datetime.now(UTC), version=result.version
                )
            except SteamMetadataError as exc:
                if str(exc) in {"steamcmd_transport", "steamcmd_start"}:
                    for remaining in objects[index:]:
                        await self.store.record_error(remaining.id, "steamcmd_transport")
                        errors += 1
                    break
                errors += 1
                await self.store.record_error(obj.id, "metadata_unavailable")
            except (MetadataError, ValueError) as exc:
                errors += 1
                error_code = (
                    str(exc)
                    if self.provider == "epic" and str(exc) in SAFE_EPIC_ERRORS
                    else "metadata_unavailable"
                )
                await self.store.record_error(obj.id, error_code)
        await self.store.mark_checked(
            datetime.now(UTC), self.provider, error_code if errors else None
        )
        log.info(
            "update_cycle_complete",
            provider=self.provider,
            objects=len(objects),
            errors=errors,
            duration_ms=round((time.monotonic() - started) * 1000),
        )
        return not errors
