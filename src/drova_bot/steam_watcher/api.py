"""Private read-only watcher API. Never expose raw upstream failures."""

from __future__ import annotations

import hmac
from collections.abc import Awaitable, Callable

from aiohttp import web

from drova_bot.steam_watcher.storage import CursorConflict, WatcherStore


def create_api(store: WatcherStore, token: str) -> web.Application:
    if not token.strip():
        raise ValueError("STEAM_WATCHER_TOKEN is required")

    @web.middleware
    async def auth(
        request: web.Request, handler: Callable[[web.Request], Awaitable[web.StreamResponse]]
    ) -> web.StreamResponse:
        actual = request.headers.get("Authorization", "").encode()
        if not hmac.compare_digest(actual, f"Bearer {token}".encode()):
            return web.json_response({"error": "unauthorized"}, status=401)
        return await handler(request)

    async def games(request: web.Request) -> web.Response:
        feed = await store.games()
        if request.path.startswith("/v1/"):
            steam_status = feed.providers.get("steam")
            checked = steam_status.checked_at if steam_status else None
            fields = {"appid", "title", "buildid", "last_success_at", "error_code"}
            return web.json_response(
                {
                    "games": [
                        g.model_dump(mode="json", include=fields)
                        for g in feed.games
                        if g.provider == "steam"
                    ],
                    "catalog_updated_at": feed.catalog_updated_at.isoformat()
                    if feed.catalog_updated_at
                    else None,
                    "checked_at": checked.isoformat() if checked else None,
                }
            )
        return web.json_response(feed.model_dump(mode="json"))

    async def events(request: web.Request) -> web.Response:
        try:
            page = await store.events(
                request.query.get("cursor"), int(request.query.get("limit", "500"))
            )
            body = page.model_dump(mode="json")
            if request.path.startswith("/v1/"):
                fields = {
                    "stream_id",
                    "seq",
                    "appid",
                    "title",
                    "branch",
                    "previous_buildid",
                    "buildid",
                    "observed_at",
                }
                body["events"] = [
                    e.model_dump(mode="json", include=fields)
                    for e in page.events
                    if e.provider == "steam"
                ]
            return web.json_response(body)
        except CursorConflict as exc:
            return web.json_response(
                {"error": "stream_reset", "next_cursor": exc.next_cursor}, status=409
            )
        except ValueError:
            return web.json_response({"error": "invalid_cursor_or_limit"}, status=400)

    async def health(request: web.Request) -> web.Response:
        feed = await store.games()
        return web.json_response(
            {
                "status": "ok",
                "providers": {k: v.model_dump(mode="json") for k, v in feed.providers.items()},
                "games": len(feed.games),
                "covered": sum(g.buildid is not None and g.error_code is None for g in feed.games),
                "catalog_updated_at": feed.catalog_updated_at.isoformat()
                if feed.catalog_updated_at
                else None,
                "checked_at": feed.checked_at.isoformat() if feed.checked_at else None,
            }
        )

    app = web.Application(middlewares=[auth])
    app.router.add_get("/v1/games", games)
    app.router.add_get("/v1/events", events)
    app.router.add_get("/v2/games", games)
    app.router.add_get("/v2/events", events)
    app.router.add_get("/health", health)
    return app
