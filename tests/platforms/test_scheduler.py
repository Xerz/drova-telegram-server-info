import asyncio
from pathlib import Path
from typing import Any, cast

from drova_bot.game_updates.models import SteamGame, UpdateObject
from drova_bot.steam_watcher.providers import MetadataClient, Observation
from drova_bot.steam_watcher.scheduler import ProviderLoop
from drova_bot.steam_watcher.storage import WatcherStore
from tests.platforms.test_contract import NOW


async def test_hung_steam_does_not_block_http_and_errors_keep_baseline(tmp_path: Path) -> None:
    store = WatcherStore(f"sqlite+aiosqlite:///{tmp_path / 's.db'}")
    await store.initialize()
    await store.replace_objects(
        [
            SteamGame(appid=730, title="CS2"),
            UpdateObject(
                id="bsg:launcher",
                provider="bsg",
                external_id="launcher",
                kind="launcher",
                title="BSG",
            ),
        ],
        NOW,
    )
    entered = asyncio.Event()

    class Steam:
        async def refresh(self) -> None:
            entered.set()
            await asyncio.Event().wait()

    async def probe(client: MetadataClient, obj: UpdateObject) -> Observation:
        return Observation("hash", "1")

    slow = ProviderLoop("steam", store, steam=cast(Any, Steam()))
    fast = ProviderLoop("bsg", store, probe=probe)
    task = asyncio.create_task(slow.cycle())
    try:
        await entered.wait()
        async with asyncio.timeout(2):
            await fast.cycle()
        obj = next(o for o in (await store.games()).objects if o.provider == "bsg")
        assert obj.buildid == "hash" and not task.done()
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        await fast.close()
        await slow.close()
        await store.close()


async def test_provider_failure_keeps_baseline_then_recovers(tmp_path: Path) -> None:
    from drova_bot.steam_watcher.providers import MetadataError

    store = WatcherStore(f"sqlite+aiosqlite:///{tmp_path / 'failure.db'}")
    await store.initialize()
    obj = UpdateObject(
        id="bsg:launcher", provider="bsg", external_id="launcher", title="BSG", kind="launcher"
    )
    await store.replace_objects([obj], NOW)
    await store.observe(obj.id, "a", NOW, version="1")
    failure = True

    async def probe(client: MetadataClient, obj: UpdateObject) -> Observation:
        if failure:
            raise MetadataError("bad_data")
        return Observation("b", "1")

    worker = ProviderLoop("bsg", store, probe=probe)
    try:
        assert not await worker.cycle()
        state = (await store.games()).objects[0]
        assert state.buildid == "a" and state.error_code
        assert not (await store.events()).events
        failure = False
        assert await worker.cycle()
        assert (await store.events()).events[0].previous_buildid == "a"
        assert not (await store.games()).objects[0].error_code
    finally:
        await worker.close()
        await store.close()


async def test_catalog_schedule_preserves_hourly_interval(monkeypatch: Any) -> None:
    import pytest

    from drova_bot.steam_watcher.scheduler import periodic

    async def cycle() -> bool:
        return True

    async def sleep(seconds: float) -> None:
        assert seconds == 3600
        raise asyncio.CancelledError

    monkeypatch.setattr("drova_bot.steam_watcher.scheduler.time.monotonic", lambda: 0)
    monkeypatch.setattr("drova_bot.steam_watcher.scheduler.asyncio.sleep", sleep)
    with pytest.raises(asyncio.CancelledError):
        await periodic(cycle, 3600)


async def test_epic_missing_credentials_is_safe_status_and_preserves_state(tmp_path: Path) -> None:
    store = WatcherStore(f"sqlite+aiosqlite:///{tmp_path / 'epic.db'}")
    await store.initialize()
    game = UpdateObject(
        id="epic:fortnite", provider="epic", external_id="Fortnite", title="Fortnite"
    )
    await store.replace_objects([game], NOW)
    await store.observe(game.id, "previous", NOW, version="1")
    worker = ProviderLoop("epic", store)
    try:
        assert not await worker.cycle()
        feed = await store.games()
        assert feed.objects[0].buildid == "previous"
        assert feed.objects[0].error_code == "epic_credentials_missing"
        assert feed.providers["epic"].error_code == "epic_credentials_missing"
        assert not (await store.events()).events
    finally:
        await worker.close()
        await store.close()
