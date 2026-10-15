"""Experimental public distribution/resource metadata; no downloaded packages."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import xml.etree.ElementTree as ET

from drova_bot.steam_watcher.providers import MAX_BYTES, MetadataClient, MetadataError, Observation

# Fixed origins/identities only. Never follow application redirects from XML.
WG_TARGETS = {
    "WOT.EU.PRODUCTION": (
        "https://wgus-woteu.wargaming.net",
        "sd",
        "EN",
        ("client", "locale", "sdcontent"),
    ),
    "WGC.EU.PRODUCTION": ("https://wguswgc-eu.wargaming.net", "wgc", "EN", ("win32",)),
    "MK.RU.PRODUCTION": (
        "https://lstus-ru.lesta.ru",
        "high",
        "RU",
        ("client", "locale", "sdcontent", "hotfix"),
    ),
}
NTE_PRIMARY = "https://ntecdn2.perfectworld.com/clientRes/publish_PC/Version/Windows/config.xml"
NTE_SECONDARY = NTE_PRIMARY.replace("ntecdn2.", "ntecdn1.")


def xml(body: bytes) -> ET.Element:
    if len(body) > MAX_BYTES:
        raise MetadataError("response_too_large")
    try:
        source = body.decode("utf-8-sig")
        if "<!DOCTYPE" in source.upper() or "<!ENTITY" in source.upper() or "\x00" in source:
            raise MetadataError("unsafe_xml")
        return ET.fromstring(source)
    except (UnicodeError, ET.ParseError):
        raise MetadataError("invalid_xml") from None


def value(root: ET.Element, path: str, *, optional: bool = False) -> str:
    nodes = root.findall(path)
    if not nodes and optional:
        return ""
    if len(nodes) != 1:
        raise MetadataError("ambiguous_xml_field")
    text = (nodes[0].text or "").strip()
    if (not text and not optional) or len(text) > 100 or any(ord(c) < 32 for c in text):
        raise MetadataError("invalid_xml_field")
    return text


def metadata(body: bytes, guid: str) -> tuple[str, str]:
    root = xml(body)
    if root.tag != "protocol" or root.get("name") != "app_metadata":
        raise MetadataError("invalid_metadata")
    sections = root.findall("predefined_section") + root.findall("protocol")
    if len(sections) != 1 or value(sections[0], "app_id") != guid:
        raise MetadataError("wrong_app_identity")
    for field in ("launch_forbidden", "stop_supporting"):
        flag = value(root, "generated_section/" + field, optional=True)
        if flag not in ("", "False", "false"):
            raise MetadataError("publication_unconfirmed")
    return value(root, "version"), value(sections[0], "chain_id")


def install_observation(root: ET.Element, parts: tuple[str, ...]) -> Observation:
    chains = root.findall("patches_chain")
    if any(c.get("type") not in {"install", "preload"} for c in chains):
        raise MetadataError("unknown_patch_chain")
    installs = [c for c in chains if c.get("type") == "install"]
    if len(installs) != 1:
        raise MetadataError("install_chain_missing")
    paths: dict[str, dict[str, tuple[str, str]]] = {p: {} for p in parts}
    for patch in installs[0]:
        if patch.tag != "patch":
            raise MetadataError("unknown_patch")
        part = value(patch, "part")
        before = value(patch, "version_from", optional=True) or "0"
        after, checksum = value(patch, "version_to"), value(patch, "torrent/hash").lower()
        if (
            part not in paths
            or before in paths[part]
            or before == after
            or not re.fullmatch(r"[0-9]+(?:\.[0-9]+)*", after)
            or not re.fullmatch("[a-f0-9]{64}", checksum)
        ):
            raise MetadataError("invalid_patch")
        paths[part][before] = (after, checksum)
    terminal = []
    versions = {}
    for part in sorted(parts):
        remaining = paths[part].copy()
        current, checksum = "0", ""
        visited = set()
        while current in remaining:
            visited.add(current)
            current, checksum = remaining.pop(current)
        if remaining or not checksum or current in visited:
            raise MetadataError("incomplete_patch_chain")
        versions[part] = current
        terminal.append((part, current, checksum))
    fingerprint = hashlib.sha256(json.dumps(terminal, separators=(",", ":")).encode()).hexdigest()
    display = value(root, "version_name", optional=True) or versions[parts[0]]
    return Observation(fingerprint, display)


async def wargaming(client: MetadataClient, guid: str) -> Observation:
    if guid not in WG_TARGETS:
        raise MetadataError("unsupported_app")
    base, kind, lang, parts = WG_TARGETS[guid]
    for attempt in range(2):
        version, chain = metadata(
            await client.get(
                base + "/api/v1/metadata/",
                {
                    "chain_id": "unknown",
                    "protocol_version": "7.5",
                    "guid": guid,
                },
            ),
            guid,
        )
        params = {
            "game_id": guid,
            "protocol_version": "1.11",
            "metadata_protocol_version": "7.5",
            "installation_id": "metadata-research",
            "client_type": kind,
            "lang": lang,
            "metadata_version": version,
            "chain_id": chain,
            **{part + "_current_version": "0" for part in parts},
        }
        root = xml(await client.get(base + "/api/v1/patches_chain/", params))
        if (
            root.tag != "protocol"
            or root.get("name") != "patches_chain"
            or root.find("changed_game_info") is not None
        ):
            raise MetadataError("invalid_patch_response")
        refresh = value(root, "meta_need_update").lower()
        if refresh == "true" and attempt == 0:
            client.clear()
            continue
        if refresh != "false":
            raise MetadataError("metadata_refresh_failed")
        return install_observation(root, parts)
    raise MetadataError("metadata_refresh_failed")


async def nte(client: MetadataClient) -> Observation:
    try:
        body = await client.get(NTE_PRIMARY)
    except MetadataError as exc:
        if str(exc) != "upstream_unavailable":
            raise
        body = await client.get(NTE_SECONDARY)
    root = xml(body)
    if root.tag != "config" or value(root, "Tag") != "baseTag":
        raise MetadataError("wrong_nte_channel")
    configs = root.findall("ResConfig")
    try:
        if len(configs) != 1:
            raise ValueError
        config = json.loads(base64.b64decode(configs[0].text or "", validate=True))
        if config["appId"] != "3000001":
            raise ValueError
    except (ValueError, KeyError, TypeError):
        raise MetadataError("wrong_nte_channel") from None
    version = value(root, "ResVersion")
    checksum = value(root, "Extra/listHash").lower()
    if (
        not re.fullmatch(r"[0-9]+(?:\.[0-9]+)+", version)
        or not any(int(v) for v in version.split("."))
        or not re.fullmatch("[a-f0-9]{32}", checksum)
    ):
        raise MetadataError("invalid_nte_resources")
    return Observation(version + ":" + checksum, version)
