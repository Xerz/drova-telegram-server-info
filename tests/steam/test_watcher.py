from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from aiohttp.test_utils import TestClient, TestServer

from drova_bot.drova.models import CatalogProductResponse
from drova_bot.game_updates.models import SteamGame, steam_games
from drova_bot.steam_watcher.api import create_api
from drova_bot.steam_watcher.steamcmd import SteamMetadataError, parse_app_info
from drova_bot.steam_watcher.storage import CursorConflict, WatcherStore

FIXTURES = Path(__file__).resolve().parents[2] / "specs/v2/fixtures/steam"
NOW = datetime(2026, 9, 7, 9, tzinfo=UTC)


def test_catalog_fields_and_mapping() -> None:
    products = [
        CatalogProductResponse.model_validate(p).to_domain()
        for p in json.loads((FIXTURES / "catalog.json").read_text())
    ]
    assert products[0].in_shop_url == "https://store.steampowered.com/app/730/"
    assert products[0].required_account == "Steam"
    assert [(g.appid, g.title) for g in steam_games(products)] == [
        (730, "Counter-Strike 2"),
        (570, "Dota 2"),
    ]
    old = CatalogProductResponse(productId="old", title="Old").to_domain()
    assert old.in_shop_url is None
    assert steam_games([old]) == []


def test_only_public_build_is_parsed_from_noisy_vdf() -> None:
    assert parse_app_info((FIXTURES / "public.vdf").read_text(), 730) == "12345"
    escaped = 'noise\n"730" { "name" "a \\"quoted\\" { name" "depots" { "branches" { "public" { "buildid" "42" } } } }\nSteam>'  # noqa: E501
    assert parse_app_info(escaped, 730) == "42"


@pytest.mark.parametrize("filename", ["missing.vdf", "truncated.vdf", "cold.txt"])
def test_bad_metadata_never_becomes_a_build(filename: str) -> None:
    with pytest.raises(SteamMetadataError):
        parse_app_info((FIXTURES / filename).read_text(), 730)


async def test_baseline_change_rollback_errors_and_restart(tmp_path: Path) -> None:
    url = f"sqlite+aiosqlite:///{tmp_path / 'watcher.sqlite'}"
    store = WatcherStore(url)
    await store.initialize()
    await store.replace_games([SteamGame(appid=730, title="CS2")], NOW)
    await store.observe(730, "100", NOW)
    assert (await store.events()).events == []
    await store.observe(730, "100", NOW)
    await store.observe(730, "200", NOW + timedelta(minutes=5))
    await store.record_error(730, "metadata_unavailable")
    assert (await store.games()).games[0].buildid == "200"
    await store.observe(730, "100", NOW + timedelta(minutes=10))
    page = await store.events(limit=1)
    assert page.has_more and page.events[0].previous_buildid == "100"
    assert page.events[0].buildid == "200"
    cursor = page.next_cursor
    await store.close()
    store = WatcherStore(url)
    await store.initialize()
    try:
        page = await store.events(cursor=cursor)
        assert [(e.previous_buildid, e.buildid) for e in page.events] == [("200", "100")]
        assert not page.has_more
        assert (await store.events(cursor=page.next_cursor)).events == []
        with pytest.raises(CursorConflict):
            await store.events(cursor="00000000-0000-0000-0000-000000000000:0")
        with pytest.raises(CursorConflict):
            await store.events(cursor=page.next_cursor.rsplit(":", 1)[0] + ":99999")
        await store.replace_games([SteamGame(appid=570, title="Dota")], NOW)
        await store.replace_games([SteamGame(appid=730, title="CS2")], NOW)
        await store.observe(730, "300", NOW)
        assert (await store.events(cursor=page.next_cursor)).events == []
    finally:
        await store.close()


async def test_api_auth_pagination_validation_and_reset(tmp_path: Path) -> None:
    store = WatcherStore(f"sqlite+aiosqlite:///{tmp_path / 'api.sqlite'}")
    await store.initialize()
    await store.replace_games([SteamGame(appid=730, title="CS2")], NOW)
    await store.observe(730, "1", NOW)
    await store.observe(730, "2", NOW)
    await store.observe(730, "3", NOW)
    client = TestClient(TestServer(create_api(store, "internal-test-secret")))
    await client.start_server()
    auth = {"Authorization": "Bearer internal-test-secret"}
    try:
        for path in ["/health", "/v1/games", "/v1/events"]:
            assert (await client.get(path)).status == 401
            assert (await client.get(path, headers=auth)).status == 200
        response = await client.get("/v1/events?limit=1", headers=auth)
        body = await response.json()
        assert len(body["events"]) == 1 and body["has_more"]
        page = await (
            await client.get("/v1/events", params={"cursor": body["next_cursor"]}, headers=auth)
        ).json()
        assert page["events"][0]["buildid"] == "3"
        assert not page["has_more"]
        for params in [{"limit": "0"}, {"limit": "501"}, {"limit": "bad"}, {"cursor": "bad"}]:
            assert (await client.get("/v1/events", params=params, headers=auth)).status == 400
        response = await client.get(
            "/v1/events?cursor=00000000-0000-0000-0000-000000000000:0", headers=auth
        )
        assert response.status == 409
        assert (await response.json())["next_cursor"].endswith(":0")
    finally:
        await client.close()
        await store.close()


async def test_cycle_preserves_catalog_and_baseline_after_upstream_failure(tmp_path: Path) -> None:
    from drova_bot.steam_watcher.runner import Watcher

    class Catalog:
        fail = False

        async def get_products_full(self):  # type: ignore[no-untyped-def]
            if self.fail:
                raise RuntimeError("sensitive upstream error")
            return [
                CatalogProductResponse(
                    productId="a",
                    title="CS2",
                    requiredAccount="Steam",
                    inShopUrl="https://store.steampowered.com/app/730",
                ).to_domain()
            ]

    class Steam:
        fail = False
        build = "1"

        async def refresh(self) -> None:
            if self.fail:
                raise SteamMetadataError("refresh_failed")

        async def buildid(self, appid: int) -> str:
            return self.build

    from typing import Any, cast

    store = WatcherStore(f"sqlite+aiosqlite:///{tmp_path / 'cycle.sqlite'}")
    await store.initialize()
    catalog, steam = Catalog(), Steam()
    watcher = Watcher(
        store, cast(Any, catalog), cast(Any, steam), clock=lambda: NOW, catalog_seconds=0
    )
    try:
        await watcher.cycle()
        assert (await store.games()).games[0].buildid == "1"
        catalog.fail = steam.fail = True
        await watcher.cycle()
        feed = await store.games()
        assert len(feed.games) == 1 and feed.games[0].buildid == "1"
        assert feed.games[0].error_code
        assert (await store.events()).events == []
        steam.fail = False
        steam.build = "2"
        await watcher.cycle()
        assert (await store.events()).events[0].buildid == "2"
    finally:
        await store.close()


async def test_runtime_connects_catalog_pty_database_and_api(tmp_path: Path) -> None:
    import asyncio
    import contextlib
    from typing import Any

    from aiohttp import web
    from aiohttp.test_utils import unused_port

    from drova_bot.steam_watcher.app import run
    from drova_bot.steam_watcher.config import WatcherSettings

    async def catalog_handler(request: web.Request) -> web.Response:
        return web.json_response(
            [
                {
                    "productId": "a",
                    "title": "CS2",
                    "requiredAccount": "Steam",
                    "inShopUrl": "https://store.steampowered.com/app/730",
                }
            ]
        )

    catalog_app = web.Application()
    catalog_app.router.add_get("/product-manager/product/listfull2", catalog_handler)
    catalog_server = TestServer(catalog_app)
    await catalog_server.start_server()
    script = tmp_path / "steamcmd"
    script.write_text("""#!/usr/bin/env python3
import sys
print("Steam>", end="", flush=True)
build = 0
for line in sys.stdin:
    if line.startswith("login"):
        print("Logged in OK")
    elif line.startswith("app_info_print"):
        build += 1
        print('"730" { "depots" { "branches" { "public" { "buildid" "' + str(build) + '" } } } }')
    print("Steam>", end="", flush=True)
""")
    script.chmod(0o755)
    port = unused_port()
    config: dict[str, Any] = {
        "STEAM_WATCHER_TOKEN": "test-secret",
        "STEAMCMD_PATH": str(script),
        "STEAM_DATABASE_URL": f"sqlite+aiosqlite:///{tmp_path / 'runtime.sqlite'}",
        "DROVA_BASE_URL": str(catalog_server.make_url("")).rstrip("/"),
        "STEAM_API_HOST": "127.0.0.1",
        "STEAM_API_PORT": port,
        "HTTP_PROXY": "",
        "HTTPS_PROXY": "",
        "STEAM_POLL_SECONDS": 1,
    }
    task = asyncio.create_task(run(WatcherSettings(**config)))
    import httpx

    try:
        async with httpx.AsyncClient(trust_env=False) as client:
            async with asyncio.timeout(10):
                while True:
                    if task.done():
                        await task
                    try:
                        response = await client.get(
                            f"http://127.0.0.1:{port}/v1/events",
                            headers={"Authorization": "Bearer test-secret"},
                        )
                        response.raise_for_status()
                        events = response.json()["events"]
                        if events:
                            assert events[0]["previous_buildid"] == "1"
                            assert events[0]["buildid"] == "2"
                            break
                    except httpx.TransportError:
                        pass
                    await asyncio.sleep(0.1)
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        await catalog_server.close()


async def test_transport_outage_aborts_remaining_apps_instead_of_reconnecting_each(
    tmp_path: Path,
) -> None:
    from typing import Any, cast

    from drova_bot.steam_watcher.runner import Watcher

    class Catalog:
        async def get_products_full(self):  # type: ignore[no-untyped-def]
            return [
                CatalogProductResponse(
                    productId=str(n),
                    title=f"Game {n}",
                    requiredAccount="Steam",
                    inShopUrl=f"https://store.steampowered.com/app/{n}",
                ).to_domain()
                for n in range(1, 4)
            ]

    class Steam:
        def __init__(self) -> None:
            self.calls: list[int] = []

        async def refresh(self) -> None:
            pass

        async def buildid(self, appid: int) -> str:
            self.calls.append(appid)
            if appid == 2:
                raise SteamMetadataError("steamcmd_transport")
            return "1"

    store = WatcherStore(f"sqlite+aiosqlite:///{tmp_path / 'outage.sqlite'}")
    await store.initialize()
    steam = Steam()
    try:
        watcher = Watcher(store, cast(Any, Catalog()), cast(Any, steam), clock=lambda: NOW)
        await watcher.cycle()
        assert steam.calls == [1, 2]
        games = (await store.games()).games
        assert games[0].buildid == "1"
        assert games[1].error_code and games[2].error_code
    finally:
        await store.close()
