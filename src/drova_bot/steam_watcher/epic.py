"""Fortnite metadata with operator-configured client OAuth; never fetch manifests."""

from __future__ import annotations

import asyncio
import json
import math
import re
import time
from collections.abc import Callable
from typing import Any

import httpx

from drova_bot.steam_watcher.providers import MAX_BYTES, MetadataClient, MetadataError, Observation

SAFE_EPIC_ERRORS = {
    "epic_credentials_missing",
    "epic_unauthorized",
    "epic_forbidden",
    "epic_rate_limited",
    "epic_upstream_unavailable",
    "epic_invalid_json",
    "epic_invalid_auth",
    "epic_invalid_metadata",
    "epic_target_missing",
    "epic_publication_unconfirmed",
    "response_too_large",
}

EPIC_TOKEN = "https://account-public-service-prod03.ol.epicgames.com/account/api/oauth/token"
EPIC_ASSET = (
    "https://launcher-public-service-prod06.ol.epicgames.com/launcher/api/public/assets/v2/"
    "platform/Windows/namespace/fn/catalogItem/4fe75bbc5a674f4f9b356b5c90567da5/"
    "app/Fortnite/label/Live"
)


class EpicHTTPError(MetadataError):
    def __init__(self, status: int) -> None:
        self.status = status
        super().__init__(
            {401: "epic_unauthorized", 403: "epic_forbidden", 429: "epic_rate_limited"}.get(
                status, "epic_upstream_unavailable"
            )
        )


class EpicClient(MetadataClient):
    def __init__(
        self,
        *,
        client_id: str = "",
        client_secret: str = "",
        clock: Callable[[], float] = time.monotonic,
        proxy: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        limiter: asyncio.Semaphore | None = None,
    ) -> None:
        super().__init__(proxy=proxy, transport=transport, limiter=limiter)
        self._client_id, self._client_secret = client_id, client_secret
        self._clock = clock
        self._token = ""
        self._expires = 0.0
        self._lock = asyncio.Lock()

    async def _request(self, *, oauth: bool = False) -> Any:
        try:
            async with self.semaphore, asyncio.timeout(20):
                async with self.http.stream(
                    "POST" if oauth else "GET",
                    EPIC_TOKEN if oauth else EPIC_ASSET,
                    auth=httpx.BasicAuth(self._client_id, self._client_secret) if oauth else None,
                    data={"grant_type": "client_credentials", "token_type": "eg1"}
                    if oauth
                    else None,
                    headers={} if oauth else {"Authorization": f"Bearer {self._token}"},
                ) as response:
                    if response.status_code != 200:
                        raise EpicHTTPError(response.status_code)
                    body = bytearray()
                    async for chunk in response.aiter_bytes(chunk_size=65536):
                        body.extend(chunk)
                        if len(body) > MAX_BYTES:
                            raise MetadataError("response_too_large")
            return json.loads(body)
        except (httpx.HTTPError, TimeoutError):
            raise MetadataError("epic_upstream_unavailable") from None
        except ValueError:
            raise MetadataError("epic_invalid_json") from None

    async def _authorize(self) -> None:
        if not self._client_id or not self._client_secret:
            raise MetadataError("epic_credentials_missing")
        if self._token and self._clock() < self._expires:
            return
        self._token = ""
        started = self._clock()
        data = await self._request(oauth=True)
        if not isinstance(data, dict):
            raise MetadataError("epic_invalid_auth")
        token, lifetime = data.get("access_token"), data.get("expires_in")
        if (
            not isinstance(token, str)
            or not token
            or len(token) > 16384
            or any(c.isspace() or ord(c) < 32 or ord(c) > 126 for c in token)
            or isinstance(lifetime, bool)
            or not isinstance(lifetime, (int, float))
            or not math.isfinite(lifetime)
            or lifetime <= 60
        ):
            raise MetadataError("epic_invalid_auth")
        self._token = token
        self._expires = started + lifetime - 60

    async def observation(self) -> Observation:
        # Serialize refresh and retry; provider loops already do not overlap.
        async with self._lock:
            await self._authorize()
            try:
                data = await self._request()
            except EpicHTTPError as exc:
                if exc.status != 401:
                    raise
                self._token = ""
                await self._authorize()
                data = await self._request()
        try:
            elements = data["elements"]
            if not isinstance(elements, list) or not all(isinstance(e, dict) for e in elements):
                raise MetadataError("epic_invalid_metadata")
            matches = [
                e
                for e in elements
                if e.get("appName") == "Fortnite" and e.get("labelName") == "Live-Windows"
            ]
            if len(matches) != 1:
                raise MetadataError("epic_target_missing")
            item = matches[0]
            if item.get("isPreloaded") is not False:
                raise MetadataError("epic_publication_unconfirmed")
            version, digest = item["buildVersion"], item["hash"]
            if (
                not isinstance(version, str)
                or not 0 < len(version) <= 100
                or any(ord(c) < 32 for c in version)
                or not isinstance(digest, str)
                or not re.fullmatch("[a-fA-F0-9]{40}", digest)
            ):
                raise MetadataError("epic_invalid_metadata")
            return Observation(version + ":" + digest.lower(), version)
        except (KeyError, TypeError, ValueError):
            raise MetadataError("epic_invalid_metadata") from None
