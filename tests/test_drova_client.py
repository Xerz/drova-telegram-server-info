from __future__ import annotations

import httpx
import pytest
import respx

from drova_bot.drova.client import DrovaClient
from drova_bot.drova.errors import DrovaUnavailable

from .conftest import load_api_response


@pytest.mark.asyncio
async def test_get_servers_sends_auth_header_and_query_params() -> None:
    with respx.mock(assert_all_called=True) as router:
        route = router.get("https://services.drova.io/server-manager/servers").mock(
            return_value=httpx.Response(200, json=load_api_response("servers.json"))
        )
        async with DrovaClient(proxy_token="old-token") as client:
            stations = await client.get_servers("user-1")

    assert stations[0].uuid.startswith("<uuid:")
    request = route.calls[0].request
    assert request.headers["X-Auth-Token"] == "old-token"
    assert request.url.params["user_id"] == "user-1"


@pytest.mark.asyncio
async def test_get_sessions_parses_session_page() -> None:
    with respx.mock(assert_all_called=True) as router:
        route = router.get("https://services.drova.io/session-manager/sessions").mock(
            return_value=httpx.Response(200, json=load_api_response("sessions_all_limit_5.json"))
        )
        async with DrovaClient(proxy_token="token") as client:
            page = await client.get_sessions(merchant_id="user-1", limit=5)

    assert len(page.sessions) == 5
    assert page.sessions[0].created_on_ms > 0
    request = route.calls[0].request
    assert request.url.params["merchant_id"] == "user-1"
    assert request.url.params["limit"] == "5"


@pytest.mark.asyncio
async def test_token_renewal_persists_before_retry() -> None:
    persisted: list[str] = []

    async def persist_token(token: str) -> None:
        persisted.append(token)

    with respx.mock(assert_all_called=True) as router:
        account_route = router.get("https://services.drova.io/accounting/myaccount").mock(
            side_effect=[
                httpx.Response(401, json={"error": "expired"}),
                httpx.Response(200, json=load_api_response("account.json")),
            ]
        )
        router.post("https://services.drova.io/token-verifier/renewProxyToken").mock(
            return_value=httpx.Response(200, json={"proxyToken": "new-token"})
        )
        async with DrovaClient(proxy_token="old-token", token_persister=persist_token) as client:
            account = await client.get_account()

    assert account.uuid == "<uuid:1>"
    assert persisted == ["new-token"]
    assert account_route.calls[0].request.headers["X-Auth-Token"] == "old-token"
    assert account_route.calls[1].request.headers["X-Auth-Token"] == "new-token"


@pytest.mark.asyncio
async def test_read_requests_retry_timeout_once() -> None:
    with respx.mock(assert_all_called=True) as router:
        route = router.get("https://services.drova.io/product-manager/product/listfull2").mock(
            side_effect=[
                httpx.ReadTimeout("timeout"),
                httpx.Response(200, json=load_api_response("products_full.json")),
            ]
        )
        async with DrovaClient(proxy_token="token") as client:
            products = await client.get_products_full()

    assert products
    assert len(route.calls) == 2


@pytest.mark.asyncio
async def test_publish_write_does_not_retry_timeout() -> None:
    with respx.mock(assert_all_called=True) as router:
        route = router.post(
            "https://services.drova.io/server-manager/servers/station-1/set_published/false"
        ).mock(side_effect=httpx.ReadTimeout("timeout"))
        async with DrovaClient(proxy_token="token") as client:
            with pytest.raises(DrovaUnavailable):
                await client.set_server_published("station-1", False)

    assert len(route.calls) == 1


@pytest.mark.asyncio
async def test_publish_write_accepts_empty_success_body() -> None:
    with respx.mock(assert_all_called=True) as router:
        route = router.post(
            "https://services.drova.io/server-manager/servers/station-1/set_published/true"
        ).mock(return_value=httpx.Response(200, content=b""))
        async with DrovaClient(proxy_token="token") as client:
            await client.set_server_published("station-1", True)

    assert len(route.calls) == 1
