import json
import zlib
from pathlib import Path

import httpx
import pytest

from drova_bot.game_updates.models import UpdateObject
from drova_bot.steam_watcher.providers import MetadataClient, MetadataError, observe

FIX = json.loads(Path("specs/v2/fixtures/platforms/metadata.json").read_text())


def target(provider: str, external: str, kind: str = "game") -> UpdateObject:
    return UpdateObject.model_validate(
        dict(
            id=f"{provider}:{external.lower()}",
            provider=provider,
            external_id=external,
            title="Test",
            kind=kind,
            channel="global" if provider != "battlenet" else "eu",
        )
    )


@pytest.mark.parametrize(
    "provider,external,kind,fixture,version",
    [
        ("hoyo", "gopR6Cufr3", "game", "hoyo_build", "7.0.0"),
        ("wuwa", "game", "game", "wuwa_game", "3.6.1"),
        ("wuwa", "launcher", "launcher", "wuwa_launcher", "2.6.5.0"),
        ("endfield", "game", "game", "endfield_game", "1.5.3"),
        ("endfield", "Official", "launcher", "endfield_launcher", "1.6.0"),
        ("endfield", "resources", "resources", "endfield_resources", "resources-A"),
        ("battlenet", "wow", "game", "battlenet", "1.0"),
        ("bsg", "launcher", "launcher", "bsg", "15.0.0.4607"),
    ],
)
async def test_public_metadata_and_fingerprint(
    provider: str, external: str, kind: str, fixture: str, version: str
) -> None:
    calls = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert "authorization" not in request.headers
        if "getGameBranches" in request.url.path:
            return httpx.Response(200, json=FIX["hoyo_branches"])
        if (
            "get_latest" in request.url.path
            and kind == "resources"
            and not request.url.path.endswith("resources")
        ):
            return httpx.Response(200, json=FIX["endfield_game"])
        data = FIX[fixture]
        if provider == "bsg":
            return httpx.Response(200, content=zlib.compress(json.dumps(data).encode()))
        if isinstance(data, str):
            return httpx.Response(200, text=data)
        return httpx.Response(200, json=data)

    async with MetadataClient(transport=httpx.MockTransport(handle)) as client:
        one = await observe(client, target(provider, external, kind))
        client.clear()
        two = await observe(client, target(provider, external, kind))
    assert one == two and one.version == version and one.fingerprint
    if provider == "hoyo":
        assert calls[1].url.params["branch"] == "main"
        assert all("getGamePackages" not in r.url.path for r in calls)
    if provider == "battlenet":
        assert "42" in one.fingerprint
    if provider == "wuwa":
        assert all("gray" not in str(r.url) for r in calls)


@pytest.mark.parametrize(
    "status,body", [(200, b"{}"), (200, b"{"), (403, b"no"), (200, b"x" * 2097153)]
)
async def test_bad_metadata_is_not_a_build(status: int, body: bytes) -> None:
    async with MetadataClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(status, content=body))
    ) as client:
        with pytest.raises(MetadataError):
            await observe(client, target("wuwa", "game"))


@pytest.mark.parametrize(
    "fixture,provider,external,kind,section,hash_key",
    [
        ("wuwa_game", "wuwa", "game", "game", ("default", "config"), "indexFileMd5"),
        ("wuwa_launcher", "wuwa", "launcher", "launcher", ("default", "resource"), "md5"),
        ("endfield_game", "endfield", "game", "game", ("pkg",), "game_files_md5"),
        ("endfield_launcher", "endfield", "Official", "launcher", (), "md5"),
        ("bsg", "bsg", "launcher", "launcher", ("data",), "hash"),
    ],
)
async def test_same_version_changed_checksum_and_rollback(
    fixture: str, provider: str, external: str, kind: str, section: tuple[str, ...], hash_key: str
) -> None:
    import copy

    original = copy.deepcopy(FIX[fixture])
    changed = copy.deepcopy(original)
    part = changed
    for key in section:
        part = part[key]
    part[hash_key] = "1234567890abcdef1234567890abcdef"
    replies = iter([original, changed, original])
    async with MetadataClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=next(replies)))
    ) as client:
        observations = []
        for _ in range(3):
            client.clear()
            observations.append(await observe(client, target(provider, external, kind)))
    assert observations[0] == observations[2]
    assert observations[0].version == observations[1].version
    assert observations[0].fingerprint != observations[1].fingerprint


async def test_compressed_oversized_body_is_rejected() -> None:
    body = zlib.compress(b" " * 2097153)
    async with MetadataClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=body))
    ) as client:
        with pytest.raises(MetadataError):
            await observe(client, target("bsg", "launcher", "launcher"))


async def test_network_failure_recovers_without_caching_failure() -> None:
    count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal count
        count += 1
        if count == 1:
            raise httpx.ReadTimeout("simulated", request=request)
        return httpx.Response(200, json=FIX["wuwa_game"])

    async with MetadataClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(MetadataError):
            await observe(client, target("wuwa", "game"))
        assert (await observe(client, target("wuwa", "game"))).version == "3.6.1"
