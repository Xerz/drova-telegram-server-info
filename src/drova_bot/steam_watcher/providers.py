"""Public metadata only: no account auth, executable downloads or manifest parsing."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import zlib
from dataclasses import dataclass
from types import TracebackType
from typing import Any, Self
from urllib.parse import urlsplit

import httpx

from drova_bot.game_updates.models import UpdateObject

MAX_BYTES = 2 * 1024 * 1024
HOYO_BRANCHES = "https://sg-hyp-api.hoyoverse.com/hyp/hyp-connect/api/getGameBranches"
HOYO_BUILD = "https://sg-public-api.hoyoverse.com/downloader/sophon_chunk/api/getBuild"
WUWA_BASE = "https://prod-alicdn-gamestarter.kurogame.com/launcher/"
WUWA_KEY = "50004_obOHXFrFanqsaIEOmuKroCcbZkQRBC7c"
ENDFIELD = "https://launcher.gryphline.com/api/"
BSG = "https://launcher.escapefromtarkov.ru/launcher/GetLauncherDistrib"


class MetadataError(Exception):
    """Safe failure code; never include URLs, delivery parameters or response bodies."""


@dataclass(frozen=True)
class Observation:
    fingerprint: str
    version: str


def text(value: Any) -> str:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > 100
        or any(ord(c) < 32 for c in value)
    ):
        raise MetadataError("invalid_metadata")
    return value


def checksum(value: Any) -> str:
    normalized = text(value)
    if not re.fullmatch(r"[a-fA-F0-9]{16,64}", normalized):
        raise MetadataError("invalid_checksum")
    return normalized.lower()


def version_hash(version: Any, digest: Any) -> Observation:
    version = text(version)
    return Observation(version + ":" + checksum(digest), version)


class MetadataClient:
    def __init__(
        self,
        *,
        proxy: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        limiter: asyncio.Semaphore | None = None,
    ) -> None:
        self.http = httpx.AsyncClient(
            proxy=proxy,
            transport=transport,
            trust_env=False,
            timeout=20,
            follow_redirects=False,
            headers={"User-Agent": "DrovaUpdateWatcher/2", "Accept-Encoding": "identity"},
        )
        self.cache: dict[str, bytes] = {}
        self.semaphore = limiter if limiter is not None else asyncio.Semaphore(4)

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.http.aclose()

    def clear(self) -> None:
        self.cache.clear()

    async def get(self, url: str, params: dict[str, str] | None = None) -> bytes:
        key = str(httpx.URL(url, params=params))
        if key in self.cache:
            return self.cache[key]
        try:
            async with self.semaphore, asyncio.timeout(20):
                async with self.http.stream("GET", url, params=params) as response:
                    response.raise_for_status()
                    body = bytearray()
                    async for chunk in response.aiter_bytes(chunk_size=65536):
                        body.extend(chunk)
                        if len(body) > MAX_BYTES:
                            raise MetadataError("response_too_large")
            self.cache[key] = bytes(body)
            return bytes(body)
        except (httpx.HTTPError, TimeoutError) as exc:
            raise MetadataError("upstream_unavailable") from exc

    async def json(
        self, url: str, params: dict[str, str] | None = None, *, compressed: bool = False
    ) -> Any:
        body = await self.get(url, params)
        try:
            if compressed and not body.lstrip().startswith(b"{"):
                decoder = zlib.decompressobj()
                body = decoder.decompress(body, MAX_BYTES + 1)
                if len(body) > MAX_BYTES or not decoder.eof:
                    raise MetadataError("invalid_compression")
            return json.loads(body)
        except (ValueError, zlib.error) as exc:
            raise MetadataError("invalid_json") from exc


async def endfield_game(client: MetadataClient) -> Any:
    return await client.json(
        ENDFIELD + "game/get_latest",
        {
            "appcode": "YDUTE5gscDZ229CW",
            "launcher_appcode": "TiaytKBUIEdoEwRT",
            "channel": "6",
            "sub_channel": "6",
            "launcher_sub_channel": "6",
            "disk_type": "0",
            "patch_encrypt": "false",
        },
    )


async def observe(client: MetadataClient, obj: UpdateObject) -> Observation:
    try:
        if obj.provider in {"wargaming", "lesta", "nte"}:
            from drova_bot.steam_watcher.xml_adapters import nte, wargaming

            if obj.provider == "nte":
                if obj.external_id != "3000001" or obj.kind != "resources":
                    raise MetadataError("unsupported_app")
                return await nte(client)
            return await wargaming(client, obj.external_id)
        if obj.provider == "epic":
            from drova_bot.steam_watcher.epic import EpicClient

            if not isinstance(client, EpicClient) or obj.external_id != "Fortnite":
                raise MetadataError("epic_client_required")
            return await client.observation()
        if obj.provider == "hoyo":
            data = await client.json(HOYO_BRANCHES, {"launcher_id": "VYTpXlbWo8"})
            if data["retcode"] != 0:
                raise MetadataError("upstream_error")
            matches = [
                x for x in data["data"]["game_branches"] if x["game"]["id"] == obj.external_id
            ]
            if len(matches) != 1:
                raise MetadataError("branch_missing")
            branch = matches[0]["main"]
            data = await client.json(
                HOYO_BUILD, {k: text(branch[k]) for k in ("package_id", "branch", "password")}
            )
            if data["retcode"] != 0:
                raise MetadataError("upstream_error")
            return Observation(text(data["data"]["build_id"]), text(data["data"]["tag"]))
        if obj.provider == "wuwa":
            if obj.kind == "launcher":
                data = await client.json(WUWA_BASE + f"launcher/{WUWA_KEY}/G153/index.json")
                value = data["default"]["resource"]
                return version_hash(value["version"], value["md5"])
            data = await client.json(WUWA_BASE + f"game/G153/{WUWA_KEY}/index.json")
            value = data["default"]["config"]
            return version_hash(value["version"], value["indexFileMd5"])
        if obj.provider == "endfield":
            if obj.kind == "launcher":
                data = await client.json(
                    ENDFIELD + "launcher/get_latest",
                    {
                        "appcode": "TiaytKBUIEdoEwRT",
                        "channel": "6",
                        "sub_channel": "6",
                        "target_app": obj.external_id,
                    },
                )
                return version_hash(data["version"], data["md5"])
            data = await endfield_game(client)
            if obj.kind == "game":
                return version_hash(data["version"], data["pkg"]["game_files_md5"])
            version = text(data["version"])
            path = urlsplit(data["pkg"]["file_path"]).path.split("/")
            segments = [p for p in path if p.startswith(version + "_")]
            if len(segments) != 1:
                raise MetadataError("resource_path_invalid")
            resources = await client.json(
                ENDFIELD + "game/get_latest_resources",
                {
                    "appcode": "YDUTE5gscDZ229CW",
                    "game_version": ".".join(version.split(".")[:2]),
                    "version": version,
                    "rand_str": segments[0][len(version) + 1 :],
                    "platform": "Windows",
                },
            )
            res_version = text(resources["res_version"])
            pairs = sorted((text(r["name"]), text(r["version"])) for r in resources["resources"])
            digest = hashlib.sha256(json.dumps([res_version, pairs]).encode()).hexdigest()
            return Observation(digest, res_version)
        if obj.provider == "battlenet":
            raw = (
                await client.get(f"http://us.patch.battle.net:1119/{obj.external_id}/versions")
            ).decode()
            lines = [
                line.strip()
                for line in raw.splitlines()
                if line.strip() and not line.startswith("#")
            ]
            keys = [v.split("!")[0] for v in lines[0].split("|")]
            rows = [dict(zip(keys, line.split("|"), strict=True)) for line in lines[1:]]
            matches = [r for r in rows if r["Region"] == obj.channel]
            if len(matches) != 1 or not matches[0]["BuildId"].isdecimal():
                raise MetadataError("region_missing")
            row = matches[0]
            return Observation(
                row["BuildId"] + ":" + checksum(row["BuildConfig"]), text(row["VersionsName"])
            )
        if obj.provider == "bsg":
            data = await client.json(
                BSG, {"launcherVersion": "15.0.0.4607", "provider": "bsg"}, compressed=True
            )
            if data["err"] != 0:
                raise MetadataError("upstream_error")
            return version_hash(data["data"]["Version"], data["data"]["hash"])
        raise MetadataError("unsupported_provider")
    except (KeyError, TypeError, ValueError, IndexError, AttributeError) as exc:
        raise MetadataError("invalid_metadata") from exc
