"""Protocols used by application services."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Protocol

from drova_bot.domain.models import (
    Account,
    CatalogProduct,
    Endpoint,
    SessionPage,
    Station,
    StationProduct,
)

TokenPersister = Callable[[str], Awaitable[None]]


class DrovaClientProtocol(Protocol):
    @property
    def proxy_token(self) -> str: ...

    async def aclose(self) -> None: ...

    async def get_account(self) -> Account: ...

    async def get_products_full(self) -> list[CatalogProduct]: ...

    async def get_servers(self, user_id: str) -> list[Station]: ...

    async def get_sessions(
        self,
        merchant_id: str | None = None,
        server_id: str | None = None,
        limit: int | None = None,
    ) -> SessionPage: ...

    async def get_server_products(self, user_id: str, server_id: str) -> list[StationProduct]: ...

    async def get_server_endpoints(
        self,
        server_id: str,
        limit: int | None = None,
    ) -> list[Endpoint]: ...

    async def set_server_published(self, server_id: str, published: bool) -> None: ...


class DrovaClientFactory(Protocol):
    def create(
        self,
        proxy_token: str,
        *,
        token_persister: TokenPersister | None = None,
    ) -> DrovaClientProtocol: ...

