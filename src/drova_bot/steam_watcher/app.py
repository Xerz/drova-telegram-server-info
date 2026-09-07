"""Standalone watcher runtime; needs no bot credentials."""

from __future__ import annotations

import asyncio
import contextlib
import signal

from aiohttp import web

from drova_bot.drova.client import DrovaClient
from drova_bot.observability.logging import configure_logging
from drova_bot.steam_watcher.api import create_api
from drova_bot.steam_watcher.config import WatcherSettings
from drova_bot.steam_watcher.runner import Watcher
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
    task: asyncio.Task[None] | None = None
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    try:
        await store.initialize()
        await runner.setup()
        await web.TCPSite(runner, settings.api_host, settings.api_port).start()
        watcher = Watcher(
            store,
            catalog,
            steam,
            poll_seconds=settings.poll_seconds,
            catalog_seconds=settings.catalog_seconds,
        )
        task = asyncio.create_task(watcher.run(), name="steam-watcher")
        await stop.wait()
    finally:
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
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
