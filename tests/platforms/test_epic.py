import copy
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

import httpx
import pytest

from drova_bot.steam_watcher.epic import EPIC_ASSET, EPIC_TOKEN, EpicClient
from drova_bot.steam_watcher.providers import MetadataError

FIX = json.loads(Path("specs/v2/fixtures/platforms/epic.json").read_text())


def client(handler: Callable[[httpx.Request], httpx.Response], **kwargs: Any) -> EpicClient:
    return EpicClient(
        client_id="test-id",
        client_secret="test-secret",
        transport=httpx.MockTransport(handler),
        **kwargs,
    )


async def test_auth_request_cache_and_expiry() -> None:
    now = [0.0]
    auth_calls = []
    asset_calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        if str(req.url) == EPIC_TOKEN:
            auth_calls.append(req)
            assert req.method == "POST"
            assert req.headers["authorization"].startswith("Basic ")
            assert parse_qs(req.content.decode()) == {
                "grant_type": ["client_credentials"],
                "token_type": ["eg1"],
            }
            return httpx.Response(200, json={"access_token": "token", "expires_in": 3600})
        assert str(req.url) == EPIC_ASSET
        assert req.headers["authorization"] == "Bearer token"
        asset_calls.append(req)
        return httpx.Response(200, json=FIX)

    async with client(handler, clock=lambda: now[0]) as api:
        first = await api.observation()
        now[0] = 100
        api.clear()
        assert await api.observation() == first
        now[0] = 3541
        await api.observation()
    assert len(auth_calls) == 2 and len(asset_calls) == 3


@pytest.mark.parametrize("status,refreshes", [(401, 2), (403, 1), (429, 1), (500, 1)])
async def test_bounded_auth_retry_and_no_secret_in_error(status: int, refreshes: int) -> None:
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(str(req.url))
        if str(req.url) == EPIC_TOKEN:
            return httpx.Response(200, json={"access_token": "private-token", "expires_in": 3600})
        return httpx.Response(status, text="secret-body")

    async with client(handler) as api:
        with pytest.raises(MetadataError) as error:
            await api.observation()
    assert calls.count(EPIC_TOKEN) == refreshes
    assert calls.count(EPIC_ASSET) == refreshes
    assert "secret" not in str(error.value) and "token" not in str(error.value)


async def test_401_refresh_success() -> None:
    assets = 0

    def handler(req: httpx.Request) -> httpx.Response:
        nonlocal assets
        if str(req.url) == EPIC_TOKEN:
            return httpx.Response(200, json={"access_token": "token", "expires_in": 3600})
        assets += 1
        return httpx.Response(401) if assets == 1 else httpx.Response(200, json=FIX)

    async with client(handler) as api:
        assert (await api.observation()).version == FIX["elements"][0]["buildVersion"]
    assert assets == 2


@pytest.mark.parametrize(
    "mutation",
    ["preload", "missing_preload", "string_preload", "label", "app", "duplicate", "hash", "empty"],
)
async def test_unpublished_or_ambiguous_is_not_observation(mutation: str) -> None:
    data = copy.deepcopy(FIX)
    element = data["elements"][0]
    if mutation == "preload":
        element["isPreloaded"] = True
    elif mutation == "missing_preload":
        del element["isPreloaded"]
    elif mutation == "string_preload":
        element["isPreloaded"] = "false"
    elif mutation == "label":
        element["labelName"] = "Test-Windows"
    elif mutation == "app":
        element["appName"] = "EpicGamesLauncherContent"
    elif mutation == "duplicate":
        data["elements"].append(element.copy())
    elif mutation == "hash":
        element["hash"] = "not-a-hash"
    else:
        data = {}

    def handler(req: httpx.Request) -> httpx.Response:
        if str(req.url) == EPIC_TOKEN:
            return httpx.Response(200, json={"access_token": "token", "expires_in": 3600})
        return httpx.Response(200, json=data)

    async with client(handler) as api:
        with pytest.raises(MetadataError):
            await api.observation()


async def test_hash_only_change_rollback_url_rotation_and_recovery() -> None:
    changed = copy.deepcopy(FIX)
    changed["elements"][0]["hash"] = "b" * 40
    rotated = copy.deepcopy(FIX)
    rotated["elements"][0]["manifests"] = [{"uri": "https://example.invalid/rotated"}]
    replies = iter([FIX, changed, FIX, rotated, {}, FIX])

    def handler(req: httpx.Request) -> httpx.Response:
        if str(req.url) == EPIC_TOKEN:
            return httpx.Response(200, json={"access_token": "token", "expires_in": 3600})
        return httpx.Response(200, json=next(replies))

    async with client(handler) as api:
        observations = [await api.observation() for _ in range(4)]
        with pytest.raises(MetadataError):
            await api.observation()
        assert await api.observation() == observations[0]
    assert observations[0] == observations[2] == observations[3]
    assert observations[1].version == observations[0].version
    assert observations[1].fingerprint != observations[0].fingerprint


async def test_missing_credentials_never_requests() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        pytest.fail("must not request without credentials")

    async with EpicClient(transport=httpx.MockTransport(handler)) as api:
        with pytest.raises(MetadataError, match="credentials_missing"):
            await api.observation()


@pytest.mark.parametrize(
    "payload",
    [{}, {"access_token": "x", "expires_in": -1}, {"access_token": "x", "expires_in": True}],
)
async def test_invalid_oauth_response(payload: dict[str, Any]) -> None:
    async with client(lambda _: httpx.Response(200, json=payload)) as api:
        with pytest.raises(MetadataError):
            await api.observation()


@pytest.mark.parametrize("oauth", [True, False])
async def test_bounded_responses_and_network_recovery(oauth: bool) -> None:
    attempts = 0

    def handler(req: httpx.Request) -> httpx.Response:
        nonlocal attempts
        target = str(req.url) == EPIC_TOKEN
        if target == oauth:
            attempts += 1
            if attempts == 1:
                return httpx.Response(200, content=b"x" * 2097153)
            if attempts == 2:
                raise httpx.ReadTimeout("never expose request details", request=req)
        if target:
            return httpx.Response(200, json={"access_token": "token", "expires_in": 3600})
        return httpx.Response(200, json=FIX)

    async with client(handler) as api:
        for _ in range(2):
            with pytest.raises(MetadataError):
                await api.observation()
        assert (await api.observation()).version == FIX["elements"][0]["buildVersion"]
