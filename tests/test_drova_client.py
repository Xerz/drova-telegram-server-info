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


@pytest.mark.asyncio
async def test_issue_promocode_uses_minutes_msecs_path_and_auth_header() -> None:
    with respx.mock(assert_all_called=True) as router:
        route = router.get(
            "https://services.drova.io/accounting/prepaid/issue_promocodes/1/3600000"
        ).mock(return_value=httpx.Response(200, json=load_api_response("promocodes_issue_60.json")))
        async with DrovaClient(proxy_token="token") as client:
            promocodes = await client.issue_promocode(60)

    assert promocodes[0].promocode == "27400125"
    assert promocodes[0].playtime_msecs == 3_600_000
    assert route.calls[0].request.headers["X-Auth-Token"] == "token"


@pytest.mark.asyncio
async def test_issue_promocode_get_write_does_not_retry_timeout() -> None:
    with respx.mock(assert_all_called=True) as router:
        route = router.get(
            "https://services.drova.io/accounting/prepaid/issue_promocodes/1/60000"
        ).mock(side_effect=httpx.ReadTimeout("timeout"))
        async with DrovaClient(proxy_token="token") as client:
            with pytest.raises(DrovaUnavailable):
                await client.issue_promocode(1)

    assert len(route.calls) == 1


@pytest.mark.asyncio
async def test_get_unused_promocodes_parses_list() -> None:
    with respx.mock(assert_all_called=True) as router:
        route = router.get(
            "https://services.drova.io/accounting/prepaid/list_unused_promocodes/false"
        ).mock(return_value=httpx.Response(200, json=load_api_response("promocodes_unused.json")))
        async with DrovaClient(proxy_token="token") as client:
            promocodes = await client.get_unused_promocodes()

    assert [promocode.promocode for promocode in promocodes] == [
        "22945015",
        "40596660",
        "27400125",
    ]
    assert route.calls[0].request.headers["X-Auth-Token"] == "token"


@pytest.mark.asyncio
async def test_next_account_read_endpoints_parse_typed_payloads_and_auth_headers() -> None:
    with respx.mock(assert_all_called=True) as router:
        stats_route = router.get(
            "https://services.drova.io/accounting/prepaid/prepaid_stats4merchant/user-1"
        ).mock(
            return_value=httpx.Response(
                200,
                json=load_api_response("account_prepaid_stats.json"),
            )
        )
        settlements_route = router.get(
            "https://services.drova.io/accounting/prepaid/list4merchant/user-1"
        ).mock(
            return_value=httpx.Response(
                200,
                json=load_api_response("account_prepaid_settlements.json"),
            )
        )
        deals_route = router.get(
            "https://services.drova.io/accounting/tinkoff/prepaid/getOpenedDeals"
        ).mock(
            return_value=httpx.Response(
                200,
                json=load_api_response("account_tinkoff_opened_deals.json"),
            )
        )
        usage_route = router.get(
            "https://services.drova.io/accounting/statistics/myserverusageprepared"
        ).mock(return_value=httpx.Response(200, json={"rows": []}))
        async with DrovaClient(proxy_token="token") as client:
            stats = await client.get_prepaid_stats("user-1")
            settlements = await client.get_prepaid_settlements("user-1")
            deals = await client.get_opened_prepaid_deals()
            assert await client.get_server_usage_statistics() == {"rows": []}

    assert stats.allowed_to_sell_minutes > 0
    assert stats.balance is None
    assert settlements[0].playtime_msecs > 0
    assert settlements[0].created_on_ms > 0
    assert deals[0].payout_amount is None
    assert deals[0].gross_amount is None
    for route in [stats_route, settlements_route, deals_route, usage_route]:
        assert route.calls[0].request.headers["X-Auth-Token"] == "token"


@pytest.mark.asyncio
async def test_next_station_product_and_server_control_endpoints() -> None:
    with respx.mock(assert_all_called=True) as router:
        product_edit_route = router.get(
            "https://services.drova.io/server-manager/serverproduct/list4edit2/station-1/product-1"
        ).mock(return_value=httpx.Response(200, json={"launch_params": []}))
        enabled_route = router.post(
            "https://services.drova.io/server-manager/serverproduct/set_enabled/"
            "station-1/product-1/false"
        ).mock(return_value=httpx.Response(200, content=b""))
        desktop_route = router.post(
            "https://services.drova.io/server-manager/servers/station-1/set_allow_desktop/true"
        ).mock(return_value=httpx.Response(200, content=b""))
        updates_route = router.post(
            "https://services.drova.io/server-manager/servers/station-1/set_disable_updates/true"
        ).mock(return_value=httpx.Response(200, content=b""))
        source_route = router.get(
            "https://services.drova.io/server-manager/servers/station-1"
        ).mock(return_value=httpx.Response(200, json=load_api_response("test_station_source.json")))
        update_route = router.put("https://services.drova.io/server-manager/servers/station-1").mock(
            return_value=httpx.Response(200, content=b"")
        )
        async with DrovaClient(proxy_token="token") as client:
            assert await client.get_server_product_edit("station-1", "product-1") == {
                "launch_params": []
            }
            await client.set_server_product_enabled("station-1", "product-1", False)
            await client.set_server_allow_desktop("station-1", True)
            await client.set_server_disable_updates("station-1", True)
            source = await client.get_server_source("station-1", "user-1")
            await client.update_server_source(
                "station-1",
                name="Station",
                description="source",
            )

    assert product_edit_route.calls[0].request.headers["X-Auth-Token"] == "token"
    assert source.allow_desktop is False
    assert source.disable_updates is True
    assert source.product_ids
    assert enabled_route.calls[0].request.content == b"{}"
    assert desktop_route.calls[0].request.content == b"{}"
    assert updates_route.calls[0].request.content == b"{}"
    assert source_route.calls[0].request.url.params["user_id"] == "user-1"
    assert update_route.calls[0].request.read() == b'{"description":"source","name":"Station"}'


@pytest.mark.asyncio
async def test_next_write_endpoints_do_not_retry_timeout() -> None:
    with respx.mock(assert_all_called=True) as router:
        route = router.post(
            "https://services.drova.io/server-manager/serverproduct/set_enabled/"
            "station-1/product-1/true"
        ).mock(side_effect=httpx.ReadTimeout("timeout"))
        async with DrovaClient(proxy_token="token") as client:
            with pytest.raises(DrovaUnavailable):
                await client.set_server_product_enabled("station-1", "product-1", True)

    assert len(route.calls) == 1
