"""Opt-in public metadata probe; no database, game downloads or private tokens."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time

from drova_bot.drova.client import DrovaClient
from drova_bot.game_updates.models import steam_games
from drova_bot.steam_watcher.steamcmd import SteamCmd, SteamMetadataError


async def probe(appids: list[int], *, full_catalog: bool, steamcmd_path: str) -> dict[str, object]:
    if full_catalog:
        async with DrovaClient(
            proxy_token="",
            base_url=os.getenv("DROVA_BASE_URL", "https://services.drova.io"),
            proxy=os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY") or None,
        ) as catalog:
            appids = [g.appid for g in steam_games(await catalog.get_products_full())]
    if not appids:
        raise ValueError("No Steam apps to probe")
    steam = SteamCmd([steamcmd_path])
    started = time.monotonic()
    available: list[int] = []
    unavailable: list[int] = []
    repeated = 0
    try:
        await steam.refresh()
        ordered = sorted(set(appids))
        for index, appid in enumerate(ordered):
            try:
                await steam.buildid(appid)
                available.append(appid)
            except SteamMetadataError as exc:
                if str(exc) in {"steamcmd_start", "steamcmd_transport"}:
                    unavailable.extend(ordered[index:])
                    break
                unavailable.append(appid)
        cycle_seconds = round(time.monotonic() - started, 2)
        await steam.refresh()
        for appid in available[:3]:
            try:
                await steam.buildid(appid)
                repeated += 1
            except SteamMetadataError:
                pass
        return {
            "requested": len(set(appids)),
            "covered": len(available),
            "unavailable_appids": unavailable,
            "repeated_reads": repeated,
            "cycle_seconds": cycle_seconds,
            "within_300_seconds": cycle_seconds <= 300,
        }
    finally:
        await steam.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--app-id", type=int, action="append", dest="appids")
    group.add_argument("--catalog", action="store_true")
    parser.add_argument(
        "--steamcmd-path", default=os.getenv("STEAMCMD_PATH", "/opt/steamcmd/steamcmd.sh")
    )
    args = parser.parse_args()
    if args.appids and any(not 0 < appid <= 4294967295 for appid in args.appids):
        parser.error("AppIDs must be positive 32-bit integers")
    try:
        result = asyncio.run(
            probe(args.appids or [], full_catalog=args.catalog, steamcmd_path=args.steamcmd_path)
        )
    except Exception:
        print(json.dumps({"error": "steam_probe_failed"}))
        raise SystemExit(1) from None
    print(json.dumps(result, ensure_ascii=False))
    if not result["covered"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
