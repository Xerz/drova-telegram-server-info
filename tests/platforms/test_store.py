from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from aiohttp.test_utils import TestClient, TestServer

from drova_bot.game_updates.models import SteamGame, UpdateObject
from drova_bot.steam_watcher.api import create_api
from drova_bot.steam_watcher.storage import WatcherStore
from tests.platforms.test_contract import NOW


async def test_mixed_journal_baseline_rollback_and_v1_pagination(tmp_path: Path) -> None:
    store = WatcherStore(f"sqlite+aiosqlite:///{tmp_path / 'watcher.db'}")
    await store.initialize()
    bsg = UpdateObject(
        id="bsg:launcher",
        provider="bsg",
        external_id="launcher",
        title="BSG Launcher",
        kind="launcher",
        related_games=["bsg:eft"],
    )
    try:
        await store.replace_objects([SteamGame(appid=730, title="CS2"), bsg], NOW)
        observations: list[tuple[str | int, str]] = [
            (730, "1"),
            ("bsg:launcher", "a"),
            ("bsg:launcher", "b"),
            (730, "2"),
            ("bsg:launcher", "a"),
        ]
        for ident, build in observations:
            await store.observe(ident, build, NOW + timedelta(minutes=1), version=build)
        page = await store.events()
        assert [e.id for e in page.events] == ["bsg:launcher", "steam:730", "bsg:launcher"]
        before = page.next_cursor
        with pytest.raises(ValueError):
            await store.observe(730, "bad", NOW)
        assert (await store.events()).next_cursor == before
        client = TestClient(TestServer(create_api(store, "secret")))
        await client.start_server()
        try:
            for path in ["/v1/games", "/v2/games", "/v2/events", "/health"]:
                assert (await client.get(path)).status == 401
            auth = {"Authorization": "Bearer secret"}
            first = await (await client.get("/v1/events?limit=1", headers=auth)).json()
            assert first["events"] == [] and first["has_more"]
            second = await (
                await client.get(
                    "/v1/events", params={"cursor": first["next_cursor"], "limit": 1}, headers=auth
                )
            ).json()
            assert second["events"][0]["appid"] == 730
            assert "provider" not in second["events"][0]
            last = await (
                await client.get(
                    "/v1/events", params={"cursor": second["next_cursor"], "limit": 1}, headers=auth
                )
            ).json()
            assert last["events"] == [] and not last["has_more"]
            assert (await (await client.get("/v2/events", headers=auth)).json())[
                "next_cursor"
            ] == before
        finally:
            await client.close()
    finally:
        await store.close()
    store = WatcherStore(f"sqlite+aiosqlite:///{tmp_path / 'watcher.db'}")
    await store.initialize()
    assert (await store.events()).next_cursor == before
    await store.close()


async def test_atomic_observation_and_reintroduced_object_baseline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy.ext.asyncio import AsyncSession

    store = WatcherStore(f"sqlite+aiosqlite:///{tmp_path / 'atomic.db'}")
    await store.initialize()
    game = UpdateObject(id="wuwa:global", provider="wuwa", external_id="game", title="WuWa")
    try:
        await store.replace_objects([game], NOW)
        await store.observe(game.id, "a", NOW)
        original = AsyncSession.flush

        async def fail(self: AsyncSession, *args: Any, **kwargs: Any) -> None:
            raise RuntimeError("write_failed")

        monkeypatch.setattr(AsyncSession, "flush", fail)
        with pytest.raises(RuntimeError):
            await store.observe(game.id, "b", NOW)
        monkeypatch.setattr(AsyncSession, "flush", original)
        assert not (await store.events()).events
        assert (await store.games()).games[0].buildid == "a"
        await store.observe(game.id, "b", NOW)
        assert len((await store.events()).events) == 1
        await store.replace_objects([], NOW)
        await store.replace_objects([game], NOW)
        await store.observe(game.id, "c", NOW)
        assert len((await store.events()).events) == 1
    finally:
        await store.close()
