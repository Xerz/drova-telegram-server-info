"""Internal watcher HTTP client; explicitly bypass deployment proxies."""

from __future__ import annotations

from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from drova_bot.game_updates.models import EventPage, GameFeed
from drova_bot.steam_watcher.storage import CursorConflict

ModelT = TypeVar("ModelT", bound=BaseModel)


class WatcherUnavailable(Exception):
    """Safe transport/contract error without request headers or body."""


class WatcherClient:
    def __init__(self, base_url: str, token: str) -> None:
        self.http = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            trust_env=False,
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )

    async def _get(
        self, path: str, model: type[ModelT], params: dict[str, str | int] | None = None
    ) -> ModelT:
        try:
            response = await self.http.get(path, params=params)
            if response.status_code == 409:
                body = response.json()
                cursor = body.get("next_cursor")
                if not isinstance(cursor, str) or not cursor.endswith(":0"):
                    raise ValueError("invalid_reset")
                raise CursorConflict(cursor)
            response.raise_for_status()
            return model.model_validate(response.json())
        except (httpx.HTTPError, ValidationError, ValueError, AttributeError) as exc:
            raise WatcherUnavailable("watcher_unavailable") from exc

    async def games(self) -> GameFeed:
        return await self._get("/v1/games", GameFeed)

    async def events(self, cursor: str | None = None) -> EventPage:
        params: dict[str, str | int] = {"limit": 500}
        if cursor is not None:
            params["cursor"] = cursor
        return await self._get("/v1/events", EventPage, params)

    async def close(self) -> None:
        await self.http.aclose()
