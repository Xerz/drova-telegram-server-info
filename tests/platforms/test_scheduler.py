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


async def test_xml_providers_baseline_error_recovery_and_restart(tmp_path: Path) -> None:
    import httpx

    from drova_bot.steam_watcher.registry import catalog_objects
    from tests.platforms.test_registry import product

    url = f"sqlite+aiosqlite:///{tmp_path / 'xml.db'}"
    store = WatcherStore(url)
    await store.initialize()
    objects, unmapped = catalog_objects(
        [
            product("c1661a7c-4950-4346-a193-103fb385b6d6", "WoT", "Wargaming"),
            product("21d8c648-8d39-4b3f-8989-69d58fbe7dff", "Ships", "Lesta"),
            product("3d02d4c9-0dfb-44fd-aeb2-2a00d288bf11", "NTE", "NTE"),
        ],
        {"wargaming", "lesta", "nte"},
    )
    await store.replace_objects(objects, NOW, unmapped=unmapped)
    state = "original"
    fixtures = Path("specs/v2/fixtures/platforms")

    def handler(req: httpx.Request) -> httpx.Response:
        if state == "error":
            return httpx.Response(200, content=b"<broken/>")
        if "perfectworld" in req.url.host:
            body = (fixtures / "nte.xml").read_bytes()
            if state == "changed":
                body = body.replace(b"1.3.10", b"1.3.11")
        else:
            name = (
                "wgc" if "wguswgc" in req.url.host else "wot" if "woteu" in req.url.host else "mk"
            )
            kind = "meta" if "metadata" in req.url.path else "chain"
            body = (fixtures / f"{name}-{kind}.xml").read_bytes()
            if state == "changed" and kind == "chain":
                body = body.replace(b"<version_to>", b"<version_to>9.")
        return httpx.Response(200, content=body)

    workers = [ProviderLoop(p, store) for p in ["wargaming", "lesta", "nte"]]
    try:
        for worker in workers:
            await worker.client.http.aclose()
            worker.client.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        for _ in range(2):
            for worker in workers:
                assert await worker.cycle()
        feed = await store.games()
        assert feed.providers["nte"].total == feed.providers["nte"].covered == 1
        assert feed.providers["wargaming"].total == feed.providers["wargaming"].covered == 2
        assert feed.providers["lesta"].covered == 1
        assert not (await store.events()).events
        state = "error"
        for worker in workers:
            assert not await worker.cycle()
        assert not (await store.events()).events
        state = "changed"
        for worker in workers:
            assert await worker.cycle()
        assert len((await store.events()).events) == 4
        state = "original"
        for worker in workers:
            assert await worker.cycle()
        page = await store.events()
        assert len(page.events) == 8
        assert all(e.id != "nte:global" for e in page.events)
        cursor = page.next_cursor
    finally:
        for worker in workers:
            await worker.close()
        await store.close()
    reopened = WatcherStore(url)
    try:
        await reopened.initialize()
        assert (await reopened.events()).next_cursor == cursor
        assert (await reopened.games()).providers["nte"].covered == 1
    finally:
        await reopened.close()
