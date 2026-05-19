"""Async Drova API client."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, cast

import httpx
from pydantic import ValidationError

from drova_bot.domain.models import (
    Account,
    CatalogProduct,
    Endpoint,
    Promocode,
    SessionPage,
    Station,
    StationProduct,
)
from drova_bot.drova.errors import DrovaPermissionDenied, DrovaUnauthorized, DrovaUnavailable
from drova_bot.drova.models import (
    AccountResponse,
    CatalogProductResponse,
    EndpointResponse,
    PromocodeResponse,
    SessionPageResponse,
    StationProductResponse,
    StationResponse,
)

TokenPersister = Callable[[str], Awaitable[None]]
QueryValue = str | int | float | bool | None
type JsonPayload = dict[str, object] | list[object]


class DrovaClient:
    """Typed client for the Drova service contract in `specs/v2/drova-api.md`."""

    def __init__(
        self,
        *,
        proxy_token: str,
        base_url: str = "https://services.drova.io",
        token_persister: TokenPersister | None = None,
        http_client: httpx.AsyncClient | None = None,
        proxy: str | None = None,
        timeout: float = 10.0,
        read_attempts: int = 2,
    ) -> None:
        self._proxy_token = proxy_token
        self._base_url = base_url.rstrip("/")
        self._token_persister = token_persister
        self._owns_client = http_client is None
        self._client = http_client or httpx.AsyncClient(
            base_url=self._base_url,
            timeout=httpx.Timeout(timeout),
            proxy=proxy,
        )
        self._read_attempts = max(1, read_attempts)

    @property
    def proxy_token(self) -> str:
        return self._proxy_token

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def __aenter__(self) -> DrovaClient:
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.aclose()

    async def get_account(self) -> Account:
        payload = await self._request("GET", "/accounting/myaccount", auth=True)
        try:
            return AccountResponse.model_validate(payload).to_domain()
        except ValidationError as exc:
            raise DrovaUnavailable("account response has unexpected shape") from exc

    async def renew_token(self, proxy_token: str) -> str:
        payload = await self._request(
            "POST",
            "/token-verifier/renewProxyToken",
            auth=False,
            json_body={"proxy_token": proxy_token},
            allow_renewal=False,
        )
        if not isinstance(payload, Mapping):
            raise DrovaUnauthorized("token renewal did not return proxyToken")
        token = payload.get("proxyToken")
        if not isinstance(token, str):
            raise DrovaUnauthorized("token renewal did not return proxyToken")
        return token

    async def get_products_full(self) -> list[CatalogProduct]:
        payload = await self._request("GET", "/product-manager/product/listfull2", auth=False)
        if not isinstance(payload, list):
            raise DrovaUnavailable("products response is not a list")
        try:
            return [CatalogProductResponse.model_validate(item).to_domain() for item in payload]
        except ValidationError as exc:
            raise DrovaUnavailable("products response has unexpected shape") from exc

    async def get_servers(self, user_id: str) -> list[Station]:
        payload = await self._request("GET", "/server-manager/servers", params={"user_id": user_id})
        if not isinstance(payload, list):
            raise DrovaUnavailable("servers response is not a list")
        try:
            return [StationResponse.model_validate(item).to_domain() for item in payload]
        except ValidationError as exc:
            raise DrovaUnavailable("servers response has unexpected shape") from exc

    async def get_sessions(
        self,
        merchant_id: str | None = None,
        server_id: str | None = None,
        limit: int | None = None,
    ) -> SessionPage:
        params: dict[str, QueryValue] = {}
        if merchant_id is not None:
            params["merchant_id"] = merchant_id
        if server_id is not None:
            params["server_id"] = server_id
        if limit is not None:
            params["limit"] = limit
        payload = await self._request("GET", "/session-manager/sessions", params=params)
        try:
            return SessionPageResponse.parse_payload(payload).to_domain()
        except ValidationError as exc:
            raise DrovaUnavailable("sessions response has unexpected shape") from exc

    async def get_server_products(self, user_id: str, server_id: str) -> list[StationProduct]:
        payload = await self._request(
            "GET",
            f"/server-manager/serverproduct/list4edit2/{server_id}",
            params={"user_id": user_id},
        )
        if not isinstance(payload, list):
            raise DrovaUnavailable("server products response is not a list")
        try:
            return [StationProductResponse.model_validate(item).to_domain() for item in payload]
        except ValidationError as exc:
            raise DrovaUnavailable("server products response has unexpected shape") from exc

    async def get_server_endpoints(
        self,
        server_id: str,
        limit: int | None = None,
    ) -> list[Endpoint]:
        params: dict[str, QueryValue] = {"server_id": server_id}
        if limit is not None:
            params["limit"] = limit
        payload = await self._request(
            "GET",
            f"/server-manager/serverendpoint/list/{server_id}",
            params=params,
        )
        if not isinstance(payload, list):
            raise DrovaUnavailable("server endpoints response is not a list")
        try:
            return [EndpointResponse.model_validate(item).to_domain() for item in payload]
        except ValidationError as exc:
            raise DrovaUnavailable("server endpoints response has unexpected shape") from exc

    async def set_server_published(self, server_id: str, published: bool) -> None:
        value = str(published).lower()
        await self._request(
            "POST",
            f"/server-manager/servers/{server_id}/set_published/{value}",
            retry_read=False,
        )

    async def issue_promocode(self, minutes: int) -> list[Promocode]:
        playtime_msecs = minutes * 60 * 1000
        payload = await self._request(
            "GET",
            f"/accounting/prepaid/issue_promocodes/1/{playtime_msecs}",
            retry_read=False,
        )
        return _parse_promocodes(payload)

    async def get_unused_promocodes(self) -> list[Promocode]:
        payload = await self._request(
            "GET",
            "/accounting/prepaid/list_unused_promocodes/false",
        )
        return _parse_promocodes(payload)

    async def get_prepaid_stats(self, merchant_id: str) -> JsonPayload:
        payload = await self._request(
            "GET",
            f"/accounting/prepaid/prepaid_stats4merchant/{merchant_id}",
        )
        return _parse_json_payload(payload, "prepaid stats")

    async def get_prepaid_settlements(self, merchant_id: str) -> JsonPayload:
        payload = await self._request(
            "GET",
            f"/accounting/prepaid/list4merchant/{merchant_id}",
        )
        return _parse_json_payload(payload, "prepaid settlements")

    async def get_opened_prepaid_deals(self) -> JsonPayload:
        payload = await self._request(
            "GET",
            "/accounting/tinkoff/prepaid/getOpenedDeals",
        )
        return _parse_json_payload(payload, "opened prepaid deals")

    async def get_server_usage_statistics(self) -> JsonPayload:
        payload = await self._request(
            "GET",
            "/accounting/statistics/myserverusageprepared",
        )
        return _parse_json_payload(payload, "server usage statistics")

    async def get_server_product_edit(self, server_id: str, product_id: str) -> JsonPayload:
        payload = await self._request(
            "GET",
            f"/server-manager/serverproduct/list4edit2/{server_id}/{product_id}",
        )
        return _parse_json_payload(payload, "server product edit")

    async def set_server_product_enabled(
        self,
        server_id: str,
        product_id: str,
        enabled: bool,
    ) -> None:
        value = str(enabled).lower()
        await self._request(
            "POST",
            f"/server-manager/serverproduct/set_enabled/{server_id}/{product_id}/{value}",
            json_body={},
            retry_read=False,
        )

    async def set_server_allow_desktop(self, server_id: str, allow_desktop: bool) -> None:
        value = str(allow_desktop).lower()
        await self._request(
            "POST",
            f"/server-manager/servers/{server_id}/set_allow_desktop/{value}",
            json_body={},
            retry_read=False,
        )

    async def set_server_disable_updates(self, server_id: str, disable_updates: bool) -> None:
        value = str(disable_updates).lower()
        await self._request(
            "POST",
            f"/server-manager/servers/{server_id}/set_disable_updates/{value}",
            json_body={},
            retry_read=False,
        )

    async def get_server_source(self, server_id: str, merchant_id: str) -> JsonPayload:
        payload = await self._request(
            "GET",
            f"/server-manager/servers/{server_id}",
            params={"user_id": merchant_id},
        )
        return _parse_json_payload(payload, "server source")

    async def update_server_source(
        self,
        server_id: str,
        *,
        name: str,
        description: str,
    ) -> None:
        await self._request(
            "PUT",
            f"/server-manager/servers/{server_id}",
            json_body={"description": description, "name": name},
            retry_read=False,
        )

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, QueryValue] | None = None,
        json_body: Mapping[str, object] | None = None,
        auth: bool = True,
        allow_renewal: bool = True,
        retry_read: bool = True,
    ) -> Any:
        headers = {"X-Auth-Token": self._proxy_token} if auth else None
        try:
            response = await self._send_with_retry(
                method,
                path,
                params=params,
                json_body=json_body,
                headers=headers,
                retry_read=retry_read,
            )
        except httpx.HTTPError as exc:
            raise DrovaUnavailable("Drova request failed") from exc

        if response.status_code == 401 and auth and allow_renewal:
            new_token = await self.renew_token(self._proxy_token)
            if self._token_persister is not None:
                await self._token_persister(new_token)
            self._proxy_token = new_token
            response = await self._send_with_retry(
                method,
                path,
                params=params,
                json_body=json_body,
                headers={"X-Auth-Token": self._proxy_token},
                retry_read=retry_read,
            )

        if response.status_code == 401:
            raise DrovaUnauthorized("Drova token is invalid")
        if response.status_code == 403:
            raise DrovaPermissionDenied("Drova permission denied")
        if response.status_code >= 500:
            raise DrovaUnavailable("Drova returned a server error")
        if response.status_code >= 400:
            raise DrovaUnavailable("Drova returned an unexpected client error")

        if not response.content:
            return None
        try:
            return response.json()
        except ValueError as exc:
            raise DrovaUnavailable("Drova returned malformed JSON") from exc

    async def _send_with_retry(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, QueryValue] | None,
        json_body: Mapping[str, object] | None,
        headers: Mapping[str, str] | None,
        retry_read: bool,
    ) -> httpx.Response:
        attempts = self._read_attempts if method == "GET" and retry_read else 1
        last_exc: httpx.HTTPError | None = None
        for attempt in range(attempts):
            try:
                return await self._client.request(
                    method,
                    path,
                    params=params,
                    json=json_body,
                    headers=headers,
                )
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_exc = exc
                if attempt + 1 >= attempts:
                    break
                await asyncio.sleep(0)
        if last_exc is not None:
            raise last_exc
        raise DrovaUnavailable("Drova request did not complete")


def _parse_promocodes(payload: object) -> list[Promocode]:
    if not isinstance(payload, list):
        raise DrovaUnavailable("promocodes response is not a list")
    try:
        return [PromocodeResponse.model_validate(item).to_domain() for item in payload]
    except ValidationError as exc:
        raise DrovaUnavailable("promocodes response has unexpected shape") from exc


def _parse_json_payload(payload: object, label: str) -> JsonPayload:
    if isinstance(payload, dict):
        return cast(dict[str, object], payload)
    if isinstance(payload, list):
        return cast(list[object], payload)
    raise DrovaUnavailable(f"{label} response is not a JSON object or list")
