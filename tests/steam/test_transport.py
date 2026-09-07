from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import respx

from drova_bot.game_updates.client import WatcherClient, WatcherUnavailable
from drova_bot.steam_watcher.steamcmd import SteamCmd, SteamMetadataError
from drova_bot.steam_watcher.storage import CursorConflict

STREAM = "00000000-0000-0000-0000-000000000001"


@respx.mock
async def test_internal_client_paths_auth_and_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HTTP_PROXY", "http://invalid-proxy:9999")
    monkeypatch.setenv("HTTPS_PROXY", "http://invalid-proxy:9999")
    games = respx.get("http://watcher:8080/v1/games").mock(
        return_value=httpx.Response(
            200, json={"games": [], "catalog_updated_at": None, "checked_at": None}
        )
    )
    events = respx.get(
        "http://watcher:8080/v1/events", params={"cursor": f"{STREAM}:0", "limit": "500"}
    ).mock(
        return_value=httpx.Response(
            200, json={"events": [], "next_cursor": f"{STREAM}:0", "has_more": False}
        )
    )
    client = WatcherClient("http://watcher:8080", "secret")
    try:
        assert (await client.games()).games == []
        assert (await client.events(f"{STREAM}:0")).events == []
        assert games.calls[0].request.headers["Authorization"] == "Bearer secret"
        assert events.called
        games.mock(return_value=httpx.Response(200, json={"bad": "payload"}))
        with pytest.raises(WatcherUnavailable):
            await client.games()
        events.mock(
            return_value=httpx.Response(
                409, json={"error": "stream_reset", "next_cursor": f"{STREAM}:0"}
            )
        )
        with pytest.raises(CursorConflict):
            await client.events(f"{STREAM}:0")
        games.mock(return_value=httpx.Response(401))
        with pytest.raises(WatcherUnavailable):
            await client.games()
    finally:
        await client.close()


async def test_real_pty_cold_cache_partial_output_and_restart(tmp_path: Path) -> None:
    script = tmp_path / "fake_steam.py"
    script.write_text("""import sys
print("Steam>", end="", flush=True)
reads = 0
for line in sys.stdin:
    if line.startswith("login"):
        print("Logged in OK")
    elif line.startswith("app_info_print"):
        reads += 1
        if reads == 1:
            print("No app info for AppID 730 found, requesting...")
        else:
            print('"730" { "depots" { "branches" { "public" { "buildid" "123" } } } }')
    print("Steam>", end="", flush=True)
""")
    steam = SteamCmd([sys.executable, "-u", str(script)], timeout=2, startup_timeout=2)
    try:
        await steam.refresh()
        assert await steam.buildid(730) == "123"
        await steam.close()
        assert await steam.buildid(730) == "123"
    finally:
        await steam.close()


async def test_hung_steamcmd_is_terminated_and_can_restart(tmp_path: Path) -> None:
    script = tmp_path / "hang.py"
    script.write_text("import time\ntime.sleep(60)\n")
    steam = SteamCmd([sys.executable, "-u", str(script)], timeout=0.1, startup_timeout=0.1)
    before = datetime.now(UTC)
    with pytest.raises(SteamMetadataError):
        await steam.refresh()
    assert (datetime.now(UTC) - before).total_seconds() < 5
    assert steam._process is None and steam._fd is None
    await steam.close()


async def test_missing_public_branch_keeps_the_healthy_session(tmp_path: Path) -> None:
    script = tmp_path / "missing.py"
    script.write_text("""import sys
print("Steam>", end="", flush=True)
for line in sys.stdin:
    if line.startswith("login"):
        print("Logged in OK")
    elif line.startswith("app_info_print"):
        print('"730" { "common" { "name" "No public build" } }')
    print("Steam>", end="", flush=True)
""")
    steam = SteamCmd([sys.executable, "-u", str(script)], timeout=2, startup_timeout=2)
    try:
        await steam.refresh()
        original = steam._process
        with pytest.raises(SteamMetadataError):
            await steam.buildid(730)
        assert steam._process is original
    finally:
        await steam.close()
