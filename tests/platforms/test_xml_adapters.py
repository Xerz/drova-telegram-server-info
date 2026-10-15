import base64
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import httpx
import pytest

from drova_bot.steam_watcher.providers import MetadataClient, MetadataError
from drova_bot.steam_watcher.xml_adapters import NTE_PRIMARY, NTE_SECONDARY, nte, wargaming

FIX = Path("specs/v2/fixtures/platforms")
TARGETS = [
    ("wot", "WOT.EU.PRODUCTION", "2.4.1.5488"),
    ("wgc", "WGC.EU.PRODUCTION", "26.05.01.3645"),
    ("mk", "MK.RU.PRODUCTION", "26.10.0.0.8867689"),
]


@pytest.mark.parametrize("name,guid,version", TARGETS)
async def test_wg_contract_repeat_hash_rollback(name: str, guid: str, version: str) -> None:
    original = (FIX / f"{name}-chain.xml").read_bytes()
    chain = ET.fromstring(original)
    node = chain.find("patches_chain/patch/torrent/hash")
    assert node is not None
    node.text = "a" * 64
    responses = iter([original, original, ET.tostring(chain), original])
    calls: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req)
        assert "authorization" not in req.headers
        if req.url.path == "/api/v1/metadata/":
            assert req.url.params["guid"] == guid
            assert req.url.params["protocol_version"] == "7.5"
            return httpx.Response(200, content=(FIX / f"{name}-meta.xml").read_bytes())
        assert req.url.path == "/api/v1/patches_chain/"
        assert req.url.params["game_id"] == guid
        assert req.url.params["protocol_version"] == "1.11"
        assert req.url.params["metadata_protocol_version"] == "7.5"
        assert req.url.params["client_type"] == {"wot": "sd", "wgc": "wgc", "mk": "high"}[name]
        assert req.url.params["lang"] == ("RU" if name == "mk" else "EN")
        assert (
            req.url.params["win32_current_version" if name == "wgc" else "client_current_version"]
            == "0"
        )
        return httpx.Response(200, content=next(responses))

    async with MetadataClient(transport=httpx.MockTransport(handler)) as client:
        observations = []
        for _ in range(4):
            client.clear()
            observations.append(await wargaming(client, guid))
    assert len(calls) == 8
    assert observations[0] == observations[1] == observations[3]
    assert observations[2].version == observations[0].version == version
    assert observations[2].fingerprint != observations[0].fingerprint


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "hash",
        "duplicate",
        "gap",
        "unknown",
        "only_preload",
        "wrong_identity",
        "redirect",
    ],
)
async def test_invalid_chain_keeps_last_good_state(mutation: str) -> None:
    meta = (FIX / "wot-meta.xml").read_bytes()
    root = ET.fromstring((FIX / "wot-chain.xml").read_bytes())
    chain = root.find("patches_chain")
    assert chain is not None
    patch = chain[0]
    if mutation == "missing":
        chain.remove(patch)
    elif mutation == "duplicate":
        chain.append(ET.fromstring(ET.tostring(patch)))
    elif mutation == "unknown":
        chain.set("type", "unrecognized")
    elif mutation == "only_preload":
        chain.set("type", "preload")
    elif mutation == "wrong_identity":
        meta = meta.replace(b"WOT.EU", b"WOT.ASIA")
    elif mutation == "redirect":
        ET.SubElement(root, "changed_game_info")
    else:
        node = patch.find("torrent/hash" if mutation == "hash" else "version_from")
        assert node is not None
        node.text = "bad"
    bad = ET.tostring(root)

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=meta if "metadata" in req.url.path else bad)

    async with MetadataClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(MetadataError):
            await wargaming(client, "WOT.EU.PRODUCTION")


async def test_preload_urls_ignored_and_metadata_refresh_bounded() -> None:
    original = (FIX / "wot-chain.xml").read_bytes()
    root = ET.fromstring(original)
    ET.SubElement(root, "patches_chain", type="preload")
    ET.SubElement(root, "web_seeds").text = "https://example.invalid/rotating"
    responses = iter(
        [
            original,
            ET.tostring(root),
            b'<protocol name="patches_chain"><meta_need_update>True</meta_need_update></protocol>',
            original,
        ]
    )
    metas = 0

    def handler(req: httpx.Request) -> httpx.Response:
        nonlocal metas
        if "metadata" in req.url.path:
            metas += 1
            return httpx.Response(200, content=(FIX / "wot-meta.xml").read_bytes())
        return httpx.Response(200, content=next(responses))

    async with MetadataClient(transport=httpx.MockTransport(handler)) as client:
        a = await wargaming(client, "WOT.EU.PRODUCTION")
        client.clear()
        assert await wargaming(client, "WOT.EU.PRODUCTION") == a
        client.clear()
        assert await wargaming(client, "WOT.EU.PRODUCTION") == a
    assert metas == 4


@pytest.mark.parametrize(
    "body",
    [
        b'<!DOCTYPE config [<!ENTITY x "boom">]><config>&x;</config>',
        b"<config>",
        b"x" * 2097153,
        "<!DOCTYPE config><config/>".encode("utf-16"),
    ],
)
async def test_xml_rejects_dtd_malformed_and_oversize(body: bytes) -> None:
    async with MetadataClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=body))
    ) as client:
        with pytest.raises(MetadataError):
            await nte(client)


async def test_nte_hash_change_rollback_preload_and_url_changes() -> None:
    original = (FIX / "nte.xml").read_bytes()
    root = ET.fromstring(original)
    ET.SubElement(root, "Devices").text = "synthetic-device"
    update = root.find("UpdateResVersion")
    assert update is not None
    update.text = "99.0"
    ignored = ET.tostring(root)
    checksum = root.find("Extra/listHash")
    assert checksum is not None
    checksum.text = "b" * 32
    replies = iter([original, ignored, ET.tostring(root), original])
    async with MetadataClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=next(replies)))
    ) as client:
        observations = []
        for _ in range(4):
            client.clear()
            observations.append(await nte(client))
    assert observations[0] == observations[1] == observations[3]
    assert observations[2].version == observations[0].version == "1.3.10"
    assert observations[2].fingerprint != observations[0].fingerprint


@pytest.mark.parametrize(
    "failure,mirror", [("transport", "true"), ("schema", "false"), ("cn", "false")]
)
async def test_nte_mirror_only_for_transport(failure: str, mirror: str) -> None:
    urls = []

    def handler(req: httpx.Request) -> httpx.Response:
        urls.append(str(req.url))
        if str(req.url) == NTE_PRIMARY:
            if failure == "transport":
                raise httpx.ConnectError("offline")
            if failure == "schema":
                return httpx.Response(200, content=b"<config/>")
            root = ET.fromstring((FIX / "nte.xml").read_bytes())
            node = root.find("ResConfig")
            assert node is not None
            node.text = base64.b64encode(json.dumps({"appId": "1289"}).encode()).decode()
            return httpx.Response(200, content=ET.tostring(root))
        assert str(req.url) == NTE_SECONDARY
        return httpx.Response(200, content=(FIX / "nte.xml").read_bytes())

    async with MetadataClient(transport=httpx.MockTransport(handler)) as client:
        if mirror == "true":
            assert (await nte(client)).version == "1.3.10"
        else:
            with pytest.raises(MetadataError):
                await nte(client)
    assert len(urls) == (2 if mirror == "true" else 1)


@pytest.mark.parametrize("cycle", [False, True])
async def test_chained_install_requires_unambiguous_terminal(cycle: bool) -> None:
    root = ET.fromstring((FIX / "wgc-chain.xml").read_bytes())
    chain = root.find("patches_chain")
    assert chain is not None
    patch = chain[0]
    end = patch.find("version_to")
    assert end is not None
    end.text = "1"
    for before, after in [("1", "2"), ("2", "1" if cycle else "3")]:
        extra = ET.fromstring(ET.tostring(patch))
        start, end = extra.find("version_from"), extra.find("version_to")
        assert start is not None and end is not None
        start.text, end.text = before, after
        chain.append(extra)

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=(FIX / "wgc-meta.xml").read_bytes()
            if "metadata" in req.url.path
            else ET.tostring(root),
        )

    async with MetadataClient(transport=httpx.MockTransport(handler)) as client:
        if cycle:
            with pytest.raises(MetadataError):
                await wargaming(client, "WGC.EU.PRODUCTION")
        else:
            assert (await wargaming(client, "WGC.EU.PRODUCTION")).fingerprint


async def test_repeated_metadata_refresh_is_bounded() -> None:
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(str(req.url))
        return httpx.Response(
            200,
            content=(FIX / "wgc-meta.xml").read_bytes()
            if "metadata" in req.url.path
            else (
                b'<protocol name="patches_chain">'
                b"<meta_need_update>True</meta_need_update></protocol>"
            ),
        )

    async with MetadataClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(MetadataError):
            await wargaming(client, "WGC.EU.PRODUCTION")
    assert len(calls) == 4
