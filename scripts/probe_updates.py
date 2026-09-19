"""Opt-in, two-pass public metadata probe; no database, credentials or game downloads."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from typing import Any

from drova_bot.drova.client import DrovaClient
from drova_bot.steam_watcher.providers import MetadataClient, MetadataError, observe
from drova_bot.steam_watcher.registry import catalog_objects

HTTP_PROVIDERS = {"hoyo", "wuwa", "endfield", "battlenet", "bsg"}


async def probe(enabled: set[str]) -> dict:
    proxy = os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY") or None
    async with DrovaClient(
        proxy_token="",
        base_url=os.getenv("DROVA_BASE_URL", "https://services.drova.io"),
        proxy=proxy,
    ) as catalog:
        products = await catalog.get_products_full()
    if not products:
        raise ValueError("empty_catalog")
    objects, unmapped = catalog_objects(products, enabled)

    limiter = asyncio.Semaphore(4)

    async def provider(name: str) -> tuple[str, dict]:
        targets = [o for o in objects if o.provider == name and o.coverage != "launcher_only"]
        results: dict[str, dict[str, Any]] = {
            o.id: {"successful_reads": 0, "versions": []} for o in targets
        }
        durations = []
        async with MetadataClient(proxy=proxy, limiter=limiter) as client:
            for _ in range(2):
                client.clear()
                started = time.monotonic()
                for obj in targets:
                    try:
                        observation = await observe(client, obj)
                        results[obj.id]["successful_reads"] += 1
                        results[obj.id]["versions"].append(observation.version)
                    except MetadataError:
                        results[obj.id]["error_code"] = "metadata_unavailable"
                durations.append(round(time.monotonic() - started, 2))
        return name, {
            "objects": results,
            "unmapped": unmapped[name],
            "cycle_seconds": durations,
            "covered": sum(r["successful_reads"] == 2 for r in results.values()),
            "total": len(targets),
        }

    return dict(await asyncio.gather(*(provider(name) for name in sorted(enabled))))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Explicitly allow public network reads")
    parser.add_argument("--providers", default=",".join(sorted(HTTP_PROVIDERS)))
    args = parser.parse_args()
    if not args.live:
        parser.error("Use --live to opt in; Steam uses scripts/probe_steam.py")
    enabled = {v.strip() for v in args.providers.split(",")}
    if not enabled or not enabled <= HTTP_PROVIDERS:
        parser.error("Unknown HTTP provider")
    try:
        result = asyncio.run(probe(enabled))
    except Exception:
        print(json.dumps({"error_code": "probe_unavailable"}))
        raise SystemExit(1) from None
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(
        0 if all(r["total"] and r["covered"] == r["total"] for r in result.values()) else 1
    )


if __name__ == "__main__":
    main()
