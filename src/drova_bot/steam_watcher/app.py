"""Standalone watcher runtime; needs no bot credentials."""

from __future__ import annotations

import asyncio
import signal

from aiohttp import web

from drova_bot.drova.client import DrovaClient
from drova_bot.observability.logging import configure_logging
from drova_bot.steam_watcher.api import create_api
from drova_bot.steam_watcher.config import WatcherSettings
from drova_bot.steam_watcher.scheduler import CatalogLoop, ProviderLoop, periodic
from drova_bot.steam_watcher.steamcmd import SteamCmd
from drova_bot.steam_watcher.storage import WatcherStore


async def run(settings: WatcherSettings) -> None:
    store = WatcherStore(settings.database_url)
    steam = SteamCmd(
        [settings.steamcmd_path],
        timeout=settings.command_timeout,
        startup_timeout=settings.startup_timeout,
    )
    catalog = DrovaClient(
        proxy_token="",
        base_url=settings.drova_base_url,
        proxy=settings.https_proxy or settings.http_proxy or None,
    )
    runner = web.AppRunner(
        create_api(store, settings.api_token.get_secret_value()), access_log=None
    )
    stop = asyncio.Event()
    tasks: list[asyncio.Task[None]] = []
    providers: list[ProviderLoop] = []
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    try:
        await store.initialize()
        await runner.setup()
        await web.TCPSite(runner, settings.api_host, settings.api_port).start()
        enabled = set(settings.update_providers.split(","))
        catalog_loop = CatalogLoop(store, catalog, enabled)
        await catalog_loop.cycle()
        tasks.append(asyncio.create_task(periodic(catalog_loop.cycle, settings.catalog_seconds)))
        limiter = asyncio.Semaphore(4)
        for name in sorted(enabled):
            provider = ProviderLoop(
                name,
                store,
                steam=steam,
                proxy=settings.https_proxy or settings.http_proxy or None,
                limiter=limiter,
                epic_client_id=settings.epic_client_id.get_secret_value(),
                epic_client_secret=settings.epic_client_secret.get_secret_value(),
            )
            providers.append(provider)
            tasks.append(
                asyncio.create_task(
                    periodic(provider.cycle, settings.poll_seconds), name=f"updates-{name}"
                )
            )
        await stop.wait()
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        for provider in providers:
            await provider.close()
        await steam.close()
        await runner.cleanup()
        await catalog.aclose()
        await store.close()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.remove_signal_handler(sig)


def main() -> None:
    settings = WatcherSettings()
    configure_logging(settings.log_level)
    asyncio.run(run(settings))


if __name__ == "__main__":
    main()
