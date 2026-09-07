"""Public Steam checks are separate from Drova live credentials and disabled by default."""

import os

import pytest

from drova_bot.steam_watcher.steamcmd import SteamCmd

pytestmark = [
    pytest.mark.steam_live,
    pytest.mark.skipif(os.getenv("STEAM_LIVE") != "1", reason="Set STEAM_LIVE=1 explicitly"),
]


async def test_public_metadata_can_be_read_repeatedly() -> None:
    steam = SteamCmd([os.getenv("STEAMCMD_PATH", "/opt/steamcmd/steamcmd.sh")])
    try:
        for _ in range(2):
            await steam.refresh()
            for appid in [730, 570]:
                build = await steam.buildid(appid)
                assert build.isdecimal() and int(build) > 0
    finally:
        await steam.close()
