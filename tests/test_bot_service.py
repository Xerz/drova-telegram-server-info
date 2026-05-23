from __future__ import annotations

from collections.abc import AsyncGenerator
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from drova_bot.application.protocols import TokenPersister
from drova_bot.application.services import BotService
from drova_bot.domain.models import (
    Account,
    CatalogProduct,
    Endpoint,
    LaunchParameters,
    OpenedPrepaidDeal,
    PrepaidSettlement,
    PrepaidStats,
    Promocode,
    ServerProductEdit,
    ServerSource,
    ServerUsageStatistics,
    Session,
    SessionPage,
    Station,
    StationProduct,
)
from drova_bot.drova.errors import DrovaUnauthorized, DrovaUnavailable
from drova_bot.exports import ExportKind
from drova_bot.storage import (
    ChatProfileRepository,
    ExportJobRow,
    TokenEncryptor,
    create_database_engine,
    create_schema,
    make_session_factory,
)
from drova_bot.storage.repositories import ProductCacheRepository, StationCacheRepository
from drova_bot.storage.uow import StorageUnitOfWorkFactory
from drova_bot.telegram.callbacks import CallbackSpec, parse_callback_data
from drova_bot.telegram.renderers import EndpointGeo, SessionGeoResolver


class FakeDrovaClient:
    def __init__(
        self,
        *,
        token: str = "token",
        account: Account | None = None,
        stations: list[Station] | None = None,
        products: list[CatalogProduct] | None = None,
        sessions: list[Session] | None = None,
        promocodes: list[Promocode] | None = None,
        prepaid_stats: PrepaidStats | None = None,
        prepaid_settlements: list[PrepaidSettlement] | None = None,
        opened_deals: list[OpenedPrepaidDeal] | None = None,
        usage_statistics: ServerUsageStatistics | None = None,
        server_sources: dict[str, ServerSource] | None = None,
        station_products: dict[str, list[StationProduct]] | None = None,
        product_edits: dict[tuple[str, str], ServerProductEdit] | None = None,
        endpoints: dict[str, list[Endpoint]] | None = None,
        unauthorized: bool = False,
        session_failures: set[str] | None = None,
        product_toggle_failures: set[str] | None = None,
    ) -> None:
        self._proxy_token = token
        self.account = account or Account(uuid="user-1", name="Owner")
        self.stations = stations or []
        self.products = products or []
        self.sessions_data = sessions or []
        self.promocodes = promocodes or []
        self.prepaid_stats = prepaid_stats or PrepaidStats(
            merchant_id=self.account.uuid,
            allowed_to_sell_minutes=0,
            sold_minutes=0,
            used_minutes=0,
            balance=None,
        )
        self.prepaid_settlements = prepaid_settlements or []
        self.opened_deals = opened_deals or []
        self.usage_statistics = usage_statistics
        self.server_sources = server_sources or {}
        self.station_products = station_products or {}
        self.product_edits = product_edits or {}
        self.endpoints = endpoints or {}
        self.unauthorized = unauthorized
        self.session_failures = session_failures or set()
        self.product_toggle_failures = product_toggle_failures or set()
        self.closed = False
        self.published_calls: list[tuple[str, bool]] = []
        self.product_enabled_calls: list[tuple[str, str, bool]] = []
        self.desktop_calls: list[tuple[str, bool]] = []
        self.disable_updates_calls: list[tuple[str, bool]] = []
        self.source_update_calls: list[tuple[str, str, str]] = []
        self.issued_promocode_minutes: list[int] = []
        self.session_calls: list[tuple[str | None, str | None, int | None]] = []

    @property
    def proxy_token(self) -> str:
        return self._proxy_token

    async def aclose(self) -> None:
        self.closed = True

    async def get_account(self) -> Account:
        if self.unauthorized:
            raise DrovaUnauthorized("invalid")
        return self.account

    async def get_products_full(self) -> list[CatalogProduct]:
        return self.products

    async def get_servers(self, user_id: str) -> list[Station]:
        return self.stations

    async def get_sessions(
        self,
        merchant_id: str | None = None,
        server_id: str | None = None,
        limit: int | None = None,
    ) -> SessionPage:
        self.session_calls.append((merchant_id, server_id, limit))
        if server_id in self.session_failures:
            raise DrovaUnavailable("session failure")
        sessions = [
            session
            for session in self.sessions_data
            if server_id is None or session.server_id == server_id
        ]
        if limit is not None:
            sessions = sessions[:limit]
        return SessionPage(sessions=sessions)

    async def get_server_products(self, user_id: str, server_id: str) -> list[StationProduct]:
        return self.station_products.get(server_id, [])

    async def get_server_product_edit(
        self,
        server_id: str,
        product_id: str,
    ) -> ServerProductEdit:
        edit = self.product_edits.get((server_id, product_id))
        if edit is not None:
            return edit
        product = next(
            (
                item
                for item in self.station_products.get(server_id, [])
                if item.product_id == product_id
            ),
            None,
        )
        if product is None:
            raise DrovaUnavailable("product not found")
        return ServerProductEdit(
            product_id=product.product_id,
            title=product.title,
            enabled=product.enabled,
            published=product.published,
            available=product.available,
            verified=None,
            default_launch=LaunchParameters(),
            current_launch=LaunchParameters(),
        )

    async def set_server_product_enabled(
        self,
        server_id: str,
        product_id: str,
        enabled: bool,
    ) -> None:
        self.product_enabled_calls.append((server_id, product_id, enabled))
        if server_id in self.product_toggle_failures:
            raise DrovaUnavailable("product toggle failure")
        self.station_products[server_id] = [
            replace(product, enabled=enabled) if product.product_id == product_id else product
            for product in self.station_products.get(server_id, [])
        ]
        edit = self.product_edits.get((server_id, product_id))
        if edit is not None:
            self.product_edits[(server_id, product_id)] = replace(edit, enabled=enabled)

    async def get_server_endpoints(
        self,
        server_id: str,
        limit: int | None = None,
    ) -> list[Endpoint]:
        result = self.endpoints.get(server_id, [])
        return result[:limit] if limit is not None else result

    async def set_server_published(self, server_id: str, published: bool) -> None:
        self.published_calls.append((server_id, published))
        self.stations = [
            replace(station, published=published) if station.uuid == server_id else station
            for station in self.stations
        ]

    async def issue_promocode(self, minutes: int) -> list[Promocode]:
        self.issued_promocode_minutes.append(minutes)
        return self.promocodes

    async def get_unused_promocodes(self) -> list[Promocode]:
        return self.promocodes

    async def get_prepaid_stats(self, merchant_id: str) -> PrepaidStats:
        assert merchant_id == self.account.uuid
        return self.prepaid_stats

    async def get_prepaid_settlements(self, merchant_id: str) -> list[PrepaidSettlement]:
        assert merchant_id == self.account.uuid
        return self.prepaid_settlements

    async def get_opened_prepaid_deals(self) -> list[OpenedPrepaidDeal]:
        return self.opened_deals

    async def get_server_usage_statistics(self) -> ServerUsageStatistics:
        if self.usage_statistics is None:
            raise DrovaUnavailable("usage statistics unavailable")
        return self.usage_statistics

    async def get_server_source(self, server_id: str, merchant_id: str) -> ServerSource:
        source = self.server_sources.get(server_id)
        if source is None:
            raise DrovaUnavailable("server source unavailable")
        assert source.user_id == merchant_id
        return source

    async def set_server_allow_desktop(self, server_id: str, allow_desktop: bool) -> None:
        self.desktop_calls.append((server_id, allow_desktop))
        source = self.server_sources.get(server_id)
        if source is not None:
            self.server_sources[server_id] = replace(source, allow_desktop=allow_desktop)

    async def set_server_disable_updates(self, server_id: str, disable_updates: bool) -> None:
        self.disable_updates_calls.append((server_id, disable_updates))
        source = self.server_sources.get(server_id)
        if source is not None:
            self.server_sources[server_id] = replace(source, disable_updates=disable_updates)

    async def update_server_source(
        self,
        server_id: str,
        *,
        name: str,
        description: str,
    ) -> None:
        self.source_update_calls.append((server_id, name, description))
        source = self.server_sources.get(server_id)
        if source is not None:
            self.server_sources[server_id] = replace(
                source,
                name=name,
                description=description,
            )


class FakeDrovaClientFactory:
    def __init__(self, *clients: FakeDrovaClient) -> None:
        self.clients = list(clients)
        self.created_tokens: list[str] = []
        self.token_persisters: list[TokenPersister | None] = []

    def create(
        self,
        proxy_token: str,
        *,
        token_persister: TokenPersister | None = None,
    ) -> FakeDrovaClient:
        self.created_tokens.append(proxy_token)
        self.token_persisters.append(token_persister)
        if not self.clients:
            raise AssertionError("no fake clients left")
        return self.clients.pop(0)


@pytest.fixture
async def service_engine(tmp_path: Path) -> AsyncGenerator[AsyncEngine]:
    engine = create_database_engine(f"sqlite+aiosqlite:///{tmp_path / 'service.sqlite3'}")
    await create_schema(engine)
    try:
        yield engine
    finally:
        await engine.dispose()


def make_service(
    engine: AsyncEngine,
    factory: FakeDrovaClientFactory,
    *,
    export_row_limit: int = 50_000,
    session_geo_resolver: SessionGeoResolver | None = None,
) -> BotService:
    session_factory = make_session_factory(engine)
    encryptor = TokenEncryptor(TokenEncryptor.generate_key())
    return BotService(
        uow_factory=StorageUnitOfWorkFactory(session_factory, encryptor),
        client_factory=factory,
        clock=lambda: datetime(2026, 5, 18, 12, 0, tzinfo=UTC),
        export_row_limit=export_row_limit,
        session_geo_resolver=session_geo_resolver,
    )


@pytest.mark.asyncio
async def test_token_valid_saves_profile_and_caches(
    service_engine: AsyncEngine,
    ui_stations: list[Station],
) -> None:
    factory = FakeDrovaClientFactory(
        FakeDrovaClient(
            stations=ui_stations,
            products=[CatalogProduct("product-a", "Cyber Rally")],
        )
    )
    service = make_service(service_engine, factory)

    message = await service.connect_token(10001, "secret-token")

    assert "Бот подключен." in message.text
    session_factory = make_session_factory(service_engine)
    async with session_factory() as session:
        profiles = ChatProfileRepository(session, TokenEncryptor(TokenEncryptor.generate_key()))
        profile = await profiles.get(10001)
        assert profile is not None
        assert profile.drova_user_id == "user-1"
        assert profile.encrypted_proxy_token is not None
        assert b"secret-token" not in profile.encrypted_proxy_token
        station_names = await StationCacheRepository(session).station_names(10001)
        product_titles = await ProductCacheRepository(session).title_map()

    assert station_names["station-online"] == "Alpha Station"
    assert product_titles == {"product-a": "Cyber Rally"}


@pytest.mark.asyncio
async def test_token_invalid_stores_nothing(service_engine: AsyncEngine) -> None:
    service = make_service(
        service_engine,
        FakeDrovaClientFactory(FakeDrovaClient(unauthorized=True)),
    )

    message = await service.connect_token(10001, "bad-token")

    assert "Токен недействителен" in message.text
    session_factory = make_session_factory(service_engine)
    async with session_factory() as session:
        assert await ChatProfileRepository(session).get(10001) is None


@pytest.mark.asyncio
async def test_limit_and_logout(service_engine: AsyncEngine) -> None:
    service = make_service(service_engine, FakeDrovaClientFactory())

    assert (await service.set_limit(10001, "100")).text == "Лимит сессий: 100"
    assert "Лимит должен" in (await service.set_limit(10001, "101")).text
    await service.select_all_stations(10001)
    assert (await service.logout(10001)).text == "Токен и настройки чата удалены."

    session_factory = make_session_factory(service_engine)
    async with session_factory() as session:
        profile = await ChatProfileRepository(session).get(10001)
    assert profile is not None
    assert profile.encrypted_proxy_token is None
    assert profile.selected_station_id is None


@pytest.mark.asyncio
async def test_sessions_uses_all_or_selected_station(
    service_engine: AsyncEngine,
    ui_stations: list[Station],
    ui_sessions: list[Session],
) -> None:
    service = make_service(
        service_engine,
        FakeDrovaClientFactory(
            FakeDrovaClient(
                stations=ui_stations,
                products=[CatalogProduct("product-b", "Space Farm")],
            ),
            FakeDrovaClient(stations=ui_stations, sessions=ui_sessions),
            FakeDrovaClient(stations=ui_stations, sessions=ui_sessions),
        ),
    )
    await service.connect_token(10001, "token")

    all_message = await service.sessions(10001)
    await service.select_station(10001, "station-online")
    selected_message = await service.sessions(10001, short_mode=True)

    assert "Последние 5 сессий · все станции" in all_message.text
    assert "Space Farm" in all_message.text
    assert "Последние 5 сессий · Alpha Station" in selected_message.text
    assert "Desktop Mode" not in selected_message.text


@pytest.mark.asyncio
async def test_sessions_station_switcher_persists_selection_and_preserves_short_mode(
    service_engine: AsyncEngine,
    ui_stations: list[Station],
    ui_sessions: list[Session],
) -> None:
    selected_client = FakeDrovaClient(stations=ui_stations, sessions=ui_sessions)
    all_client = FakeDrovaClient(stations=ui_stations, sessions=ui_sessions)
    service = make_service(
        service_engine,
        FakeDrovaClientFactory(
            FakeDrovaClient(
                stations=ui_stations,
                products=[
                    CatalogProduct("product-a", "Cyber Rally"),
                    CatalogProduct("product-b", "Space Farm"),
                    CatalogProduct("product-c", "Desktop Mode"),
                ],
            ),
            FakeDrovaClient(stations=ui_stations),
            selected_client,
            all_client,
        ),
    )
    await service.connect_token(10001, "token")

    picker = await service.handle_callback(
        10001,
        parse_callback_data(
            CallbackSpec(action="sessions_station_picker", short_mode=True).pack()
        ),
    )
    selected = await service.handle_callback(
        10001,
        parse_callback_data(
            CallbackSpec(
                action="sessions_station_select",
                station_id="station-online",
                short_mode=True,
            ).pack()
        ),
    )
    all_stations = await service.handle_callback(
        10001,
        parse_callback_data(CallbackSpec(action="sessions_station_all", short_mode=True).pack()),
    )

    assert "Выберите станцию для сессий" in picker.text
    assert "Последние 5 сессий · Alpha Station" in selected.text
    assert "Cyber Rally" in selected.text
    assert "Desktop Mode" not in selected.text
    assert selected_client.session_calls == [(None, "station-online", 5)]
    assert "Последние 5 сессий · все станции" in all_stations.text
    assert all_client.session_calls == [("user-1", None, 5)]
    async with make_session_factory(service_engine)() as session:
        profile = await ChatProfileRepository(session).get(10001)
    assert profile is not None
    assert profile.selected_station_id is None


@pytest.mark.asyncio
async def test_account_billing_uses_saved_profile_and_drova_data(
    service_engine: AsyncEngine,
    ui_stations: list[Station],
) -> None:
    service = make_service(
        service_engine,
        FakeDrovaClientFactory(
            FakeDrovaClient(stations=ui_stations),
            FakeDrovaClient(
                prepaid_stats=PrepaidStats(
                    merchant_id="user-1",
                    allowed_to_sell_minutes=120,
                    sold_minutes=300,
                    used_minutes=240,
                    balance=None,
                ),
                prepaid_settlements=[
                    PrepaidSettlement(
                        uuid="settlement-1",
                        client_id=None,
                        created_on_ms=1779125315305,
                        has_order=True,
                        playtime_msecs=3_600_000,
                    )
                ],
                opened_deals=[
                    OpenedPrepaidDeal(
                        created_on_ms=1777593600000,
                        deal_id="deal-1",
                        payout_amount=None,
                        gross_amount=None,
                        terminal_index=0,
                    )
                ],
            ),
        ),
    )
    await service.connect_token(10001, "token")

    message = await service.account_billing(10001)

    assert "Доступно к продаже: 120 мин" in message.text
    assert "Баланс минут: скрыто" in message.text
    assert "60 мин · заказ" in message.text
    assert "сумма скрыто · к выплате скрыто" in message.text


@pytest.mark.asyncio
async def test_usage_statistics_uses_backend_stats_and_cached_titles(
    service_engine: AsyncEngine,
    ui_stations: list[Station],
    ui_usage_statistics: ServerUsageStatistics,
) -> None:
    service = make_service(
        service_engine,
        FakeDrovaClientFactory(
            FakeDrovaClient(
                stations=ui_stations,
                products=[
                    CatalogProduct("product-a", "Cyber Rally"),
                    CatalogProduct("product-b", "Space Farm"),
                ],
            ),
            FakeDrovaClient(
                stations=ui_stations,
                usage_statistics=ui_usage_statistics,
            ),
        ),
    )
    await service.connect_token(10001, "token")

    message = await service.usage_statistics(10001)

    assert "Статистика использования" in message.text
    assert "Сегодня: 2 сессий · 2 ч 10 мин" in message.text
    assert "1. Alpha Station · 8 сессий · 12 ч 0 мин" in message.text
    assert "1. Cyber Rally · 6 сессий · 10 ч 0 мин" in message.text


@pytest.mark.asyncio
async def test_server_control_confirmation_and_confirm_use_selected_station(
    service_engine: AsyncEngine,
    ui_stations: list[Station],
    ui_server_source: ServerSource,
) -> None:
    control_client = FakeDrovaClient(
        stations=ui_stations,
        server_sources={"station-online": ui_server_source},
    )
    service = make_service(
        service_engine,
        FakeDrovaClientFactory(
            FakeDrovaClient(stations=ui_stations),
            control_client,
            control_client,
        ),
    )
    await service.connect_token(10001, "token")
    await service.select_station(10001, "station-online")

    confirmation = await service.server_control_confirmation(10001, "desktop_on")
    result = await service.server_control_confirm(10001, "desktop_on", "off")

    assert "<code>/desktop_on_confirm off</code>" in confirmation.text
    assert "station-online" not in confirmation.text
    assert "Полный доступ включен: Alpha Station" in result.text
    assert control_client.desktop_calls == [("station-online", True)]


@pytest.mark.asyncio
async def test_server_control_confirm_rejects_stale_state_without_write(
    service_engine: AsyncEngine,
    ui_stations: list[Station],
    ui_server_source: ServerSource,
) -> None:
    control_client = FakeDrovaClient(
        stations=ui_stations,
        server_sources={"station-online": replace(ui_server_source, disable_updates=False)},
    )
    service = make_service(
        service_engine,
        FakeDrovaClientFactory(
            FakeDrovaClient(stations=ui_stations),
            control_client,
        ),
    )
    await service.connect_token(10001, "token")
    await service.select_station(10001, "station-online")

    message = await service.server_control_confirm(10001, "updates_off", "off")

    assert message.text == "Состояние уже изменилось. Обновите команду управления."
    assert control_client.disable_updates_calls == []


@pytest.mark.asyncio
async def test_server_source_uses_selected_station_and_escapes_description(
    service_engine: AsyncEngine,
    ui_stations: list[Station],
    ui_server_source: ServerSource,
) -> None:
    source_client = FakeDrovaClient(
        stations=ui_stations,
        server_sources={
            "station-online": replace(
                ui_server_source,
                description="<b>raw & station source</b>",
            )
        },
    )
    service = make_service(
        service_engine,
        FakeDrovaClientFactory(
            FakeDrovaClient(stations=ui_stations),
            source_client,
        ),
    )
    await service.connect_token(10001, "token")
    await service.select_station(10001, "station-online")

    message = await service.server_source(10001)

    assert "Исходник описания станции Alpha Station" in message.text
    assert "&lt;b&gt;raw &amp; station source&lt;/b&gt;" in message.text
    assert "<b>raw & station source</b>" not in message.text


@pytest.mark.asyncio
async def test_server_description_preview_and_apply_use_source_revision(
    service_engine: AsyncEngine,
    ui_stations: list[Station],
    ui_server_source: ServerSource,
) -> None:
    source_client = FakeDrovaClient(
        stations=ui_stations,
        server_sources={"station-online": ui_server_source},
    )
    service = make_service(
        service_engine,
        FakeDrovaClientFactory(
            FakeDrovaClient(stations=ui_stations),
            source_client,
            source_client,
        ),
    )
    await service.connect_token(10001, "token")
    await service.select_station(10001, "station-online")

    preview = await service.server_description_preview(10001, "New station source")
    revision = preview.text.split("/server_description_apply ", maxsplit=1)[1].split()[0]
    result = await service.server_description_apply(10001, f"{revision} New station source")

    assert "Новое описание для Alpha Station" in preview.text
    assert "station-online" not in preview.text
    assert "Описание обновлено: Alpha Station" in result.text
    assert source_client.source_update_calls == [
        ("station-online", "Alpha Station", "New station source")
    ]


@pytest.mark.asyncio
async def test_server_description_apply_rejects_stale_revision(
    service_engine: AsyncEngine,
    ui_stations: list[Station],
    ui_server_source: ServerSource,
) -> None:
    source_client = FakeDrovaClient(
        stations=ui_stations,
        server_sources={"station-online": ui_server_source},
    )
    service = make_service(
        service_engine,
        FakeDrovaClientFactory(
            FakeDrovaClient(stations=ui_stations),
            source_client,
        ),
    )
    await service.connect_token(10001, "token")
    await service.select_station(10001, "station-online")

    message = await service.server_description_apply(10001, "badrev New station source")

    assert message.text == "Описание станции уже изменилось. Сначала выполните /server_source."
    assert source_client.source_update_calls == []


@pytest.mark.asyncio
async def test_station_manage_menu_selects_station_and_toggles_controls(
    service_engine: AsyncEngine,
    ui_stations: list[Station],
    ui_sessions: list[Session],
    ui_server_source: ServerSource,
) -> None:
    manage_client = FakeDrovaClient(
        stations=ui_stations,
        sessions=ui_sessions,
        server_sources={"station-online": ui_server_source},
    )
    service = make_service(
        service_engine,
        FakeDrovaClientFactory(
            FakeDrovaClient(
                stations=ui_stations,
                products=[CatalogProduct("product-a", "Cyber Rally")],
            ),
            manage_client,
            manage_client,
            manage_client,
            manage_client,
        ),
    )
    await service.connect_token(10001, "token")

    picker = await service.station_manage_picker(10001)
    panel = await service.handle_callback(
        10001,
        parse_callback_data(
            CallbackSpec(action="station_manage_select", station_id="station-online").pack()
        ),
    )
    desktop = await service.handle_callback(
        10001,
        parse_callback_data(
            CallbackSpec(
                action="station_control_toggle",
                station_id="station-online",
                control="desktop",
                expected_state=False,
            ).pack()
        ),
    )
    updates = await service.handle_callback(
        10001,
        parse_callback_data(
            CallbackSpec(
                action="station_control_toggle",
                station_id="station-online",
                control="updates",
                expected_state=False,
            ).pack()
        ),
    )

    assert "Управление станциями" in picker.text
    assert "Управление станцией" not in panel.text
    assert "<b>Alpha Station</b>" in panel.text
    assert "<b>Cyber Rally</b>" in panel.text
    assert "Последняя сессия:" not in panel.text
    assert desktop.toast == "Полный доступ включен."
    assert updates.toast == "Обновления включены."
    assert manage_client.session_calls == [
        (None, "station-online", 1),
        (None, "station-online", 1),
        (None, "station-online", 1),
    ]
    assert manage_client.desktop_calls == [("station-online", True)]
    assert manage_client.disable_updates_calls == [("station-online", False)]


@pytest.mark.asyncio
async def test_station_manage_publish_confirmation_success_and_stale(
    service_engine: AsyncEngine,
    ui_stations: list[Station],
    ui_server_source: ServerSource,
) -> None:
    publish_client = FakeDrovaClient(
        stations=ui_stations,
        server_sources={"station-online": ui_server_source},
    )
    stale_client = FakeDrovaClient(
        stations=[
            replace(station, published=False) if station.uuid == "station-online" else station
            for station in ui_stations
        ],
        server_sources={"station-online": replace(ui_server_source, published=False)},
    )
    service = make_service(
        service_engine,
        FakeDrovaClientFactory(
            FakeDrovaClient(stations=ui_stations),
            publish_client,
            publish_client,
            stale_client,
        ),
    )
    await service.connect_token(10001, "token")

    confirmation = await service.handle_callback(
        10001,
        parse_callback_data(
            CallbackSpec(
                action="station_publish_prompt",
                station_id="station-online",
                expected_published=True,
            ).pack()
        ),
    )
    success = await service.handle_callback(
        10001,
        parse_callback_data(
            CallbackSpec(
                action="station_publish_confirm",
                station_id="station-online",
                expected_published=True,
            ).pack()
        ),
    )
    stale = await service.handle_callback(
        10001,
        parse_callback_data(
            CallbackSpec(
                action="station_publish_prompt",
                station_id="station-online",
                expected_published=True,
            ).pack()
        ),
    )

    assert 'Изменить публикацию станции "Alpha Station" на "скрыта"?' in confirmation.text
    assert publish_client.published_calls == [("station-online", False)]
    assert "Публикация:" not in success.text
    assert success.keyboard is not None
    assert "🚫 Скрыта" in [button.text for row in success.keyboard.rows for button in row]
    assert success.toast == "Станция скрыта."
    assert stale.text == "Состояние станции изменилось. Обновите панель публикации."


@pytest.mark.asyncio
async def test_station_manage_description_draft_flow(
    service_engine: AsyncEngine,
    ui_stations: list[Station],
    ui_server_source: ServerSource,
) -> None:
    source_client = FakeDrovaClient(
        stations=ui_stations,
        server_sources={"station-online": ui_server_source},
    )
    service = make_service(
        service_engine,
        FakeDrovaClientFactory(
            FakeDrovaClient(stations=ui_stations),
            source_client,
            source_client,
        ),
    )
    await service.connect_token(10001, "token")

    request = await service.begin_station_description_update(10001, "station-online")
    draft = await service.consume_station_description_text(10001, "<b>New & source</b>")
    assert draft is not None
    assert draft.keyboard is not None
    draft_id = parse_callback_data(draft.keyboard.rows[0][0].callback_data).draft_id
    applied = await service.apply_station_description_draft(10001, draft_id)

    assert "Пришлите новое HTML-описание" in request.text
    assert "Текущее описание:" in request.text
    assert "&lt;description:redacted&gt;" in request.text
    assert '<pre><code class="language-html">' in draft.text
    assert "&lt;b&gt;New &amp; source&lt;/b&gt;" in draft.text
    assert applied.toast == "Описание обновлено."
    assert "Управление станцией" not in applied.text
    assert "<b>Alpha Station</b>" in applied.text
    assert source_client.source_update_calls == [
        ("station-online", "Alpha Station", "<b>New & source</b>")
    ]


@pytest.mark.asyncio
async def test_account_menu_wraps_account_results(
    service_engine: AsyncEngine,
    ui_stations: list[Station],
    ui_usage_statistics: ServerUsageStatistics,
) -> None:
    account_client = FakeDrovaClient(
        stations=ui_stations,
        products=[CatalogProduct("product-a", "Cyber Rally")],
        usage_statistics=ui_usage_statistics,
        promocodes=[_promocode("27400125", 60_000)],
        prepaid_stats=PrepaidStats(
            merchant_id="user-1",
            allowed_to_sell_minutes=10,
            sold_minutes=5,
            used_minutes=2,
            balance=1.5,
        ),
    )
    service = make_service(
        service_engine,
        FakeDrovaClientFactory(
            FakeDrovaClient(
                stations=ui_stations,
                products=[CatalogProduct("product-a", "Cyber Rally")],
            ),
            account_client,
            account_client,
            account_client,
            account_client,
        ),
    )
    await service.connect_token(10001, "token")

    menu = await service.account_menu(10001)
    balance = await service.handle_callback(
        10001,
        parse_callback_data(CallbackSpec(action="account_balance").pack()),
    )
    usage = await service.handle_callback(
        10001,
        parse_callback_data(CallbackSpec(action="account_usage").pack()),
    )
    promocodes = await service.handle_callback(
        10001,
        parse_callback_data(CallbackSpec(action="account_promocodes").pack()),
    )

    assert menu.keyboard is not None
    assert "Баланс минут: 1.50" in balance.text
    assert "Статистика использования" in usage.text
    assert "<code>27400125</code>" in promocodes.text
    assert "Меню аккаунта" in balance.text
    assert balance.keyboard is not None
    assert usage.keyboard is not None
    assert promocodes.keyboard is not None


@pytest.mark.asyncio
async def test_sessions_page_refetches_and_keeps_short_mode(
    service_engine: AsyncEngine,
    ui_stations: list[Station],
    ui_sessions: list[Session],
) -> None:
    many_sessions = [
        replace(
            ui_sessions[0],
            uuid=f"session-page-{index}",
            product_id=f"product-page-{index}",
            created_on_ms=ui_sessions[0].created_on_ms - index * 60_000,
        )
        for index in range(7)
    ]
    first_page_client = FakeDrovaClient(stations=ui_stations, sessions=many_sessions)
    second_page_client = FakeDrovaClient(stations=ui_stations, sessions=many_sessions)
    service = make_service(
        service_engine,
        FakeDrovaClientFactory(
            FakeDrovaClient(
                stations=ui_stations,
                products=[
                    CatalogProduct(f"product-page-{index}", f"Game {index}")
                    for index in range(7)
                ],
            ),
            first_page_client,
            second_page_client,
        ),
    )
    await service.connect_token(10001, "token")
    await service.set_limit(10001, "10")

    page_two = await service.sessions(10001, page=1)
    refreshed_page_two = await service.handle_callback(
        10001,
        parse_callback_data(CallbackSpec(action="sessions_short_page", page=1).pack()),
    )

    assert first_page_client.session_calls == [("user-1", None, 10)]
    assert second_page_client.session_calls == [("user-1", None, 10)]
    assert "стр. 2" in page_two.text
    assert "стр. 2" in refreshed_page_two.text
    assert refreshed_page_two.keyboard is not None
    assert "Показать все" in [
        button.text for row in refreshed_page_two.keyboard.rows for button in row
    ]


@pytest.mark.asyncio
async def test_current_renders_partial_station_failure(
    service_engine: AsyncEngine,
    ui_stations: list[Station],
    ui_sessions: list[Session],
) -> None:
    service = make_service(
        service_engine,
        FakeDrovaClientFactory(
            FakeDrovaClient(
                stations=ui_stations,
                products=[CatalogProduct("product-a", "Cyber Rally")],
            ),
            FakeDrovaClient(
                stations=ui_stations,
                sessions=ui_sessions,
                session_failures={"station-hidden"},
            ),
        ),
    )
    await service.connect_token(10001, "token")

    message = await service.current(10001)

    assert "🌐 Alpha Station · <b>Cyber Rally</b>" in message.text
    assert "🔒 Beta Test Station · скрыта · UNVERIFIED · ошибка загрузки" in message.text


@pytest.mark.asyncio
async def test_promocode_issue_and_unused_list_use_saved_token(
    service_engine: AsyncEngine,
    ui_stations: list[Station],
) -> None:
    promocodes = [_promocode("27400125", 3_600_000)]
    issue_client = FakeDrovaClient(promocodes=promocodes)
    service = make_service(
        service_engine,
        FakeDrovaClientFactory(
            FakeDrovaClient(stations=ui_stations),
            issue_client,
            FakeDrovaClient(promocodes=promocodes),
        ),
    )
    await service.connect_token(10001, "token")

    issued = await service.issue_promocode(10001, "60")
    unused = await service.unused_promocodes(10001)

    assert issue_client.issued_promocode_minutes == [60]
    assert "<code>27400125</code> · 60 мин" in issued.text
    assert "Неактивированные промокоды:" in unused.text
    assert "<code>27400125</code> · 60 мин" in unused.text


@pytest.mark.asyncio
async def test_promocode_issue_rejects_invalid_minutes_without_client(
    service_engine: AsyncEngine,
) -> None:
    service = make_service(service_engine, FakeDrovaClientFactory())

    message = await service.issue_promocode(10001, "1.5")

    assert "целым числом больше 0" in message.text


@pytest.mark.asyncio
async def test_sessions_and_current_use_injected_geo_without_raw_ip_in_current(
    service_engine: AsyncEngine,
    ui_stations: list[Station],
    ui_sessions: list[Session],
) -> None:
    def resolver(session: Session) -> EndpointGeo | None:
        if session.creator_ip == "203.0.113.20":
            return EndpointGeo(city="Example City")
        return None

    service = make_service(
        service_engine,
        FakeDrovaClientFactory(
            FakeDrovaClient(
                stations=ui_stations,
                products=[
                    CatalogProduct("product-a", "Cyber Rally"),
                    CatalogProduct("product-b", "Space Farm"),
                ],
            ),
            FakeDrovaClient(stations=ui_stations, sessions=ui_sessions),
            FakeDrovaClient(stations=ui_stations, sessions=ui_sessions),
        ),
        session_geo_resolver=resolver,
    )
    await service.connect_token(10001, "token")

    sessions = await service.sessions(10001)
    current = await service.current(10001)

    assert "IP: <code>203.0.113.20</code> · Example City" in sessions.text
    assert (
        "Cyber Rally</b> · 💳 prepaid ✅ finished · 16:00 · 10 мин · Example City"
        in current.text
    )
    assert "203.0.113.20" not in current.text


@pytest.mark.asyncio
async def test_current_refresh_panel_callback_uses_station_management_button(
    service_engine: AsyncEngine,
    ui_stations: list[Station],
    ui_sessions: list[Session],
) -> None:
    service = make_service(
        service_engine,
        FakeDrovaClientFactory(
            FakeDrovaClient(
                stations=ui_stations,
                products=[CatalogProduct("product-a", "Cyber Rally")],
            ),
            FakeDrovaClient(stations=ui_stations, sessions=ui_sessions),
            FakeDrovaClient(stations=ui_stations),
        ),
    )
    await service.connect_token(10001, "token")

    message = await service.handle_callback(
        10001,
        parse_callback_data(CallbackSpec(action="current_refresh_panel").pack()),
    )
    legacy_publish_panel = await service.handle_callback(
        10001,
        parse_callback_data(CallbackSpec(action="publish_panel").pack()),
    )

    assert message.keyboard is not None
    assert message.keyboard.rows[1][0].text == "Управление станциями"
    assert "Управление станциями" in legacy_publish_panel.text
    assert legacy_publish_panel.keyboard is not None
    assert legacy_publish_panel.keyboard.rows[-1][0].text == "К текущему состоянию"


@pytest.mark.asyncio
async def test_disabled_and_stations_use_station_fixtures(
    service_engine: AsyncEngine,
    ui_stations: list[Station],
    ui_products_by_station: dict[str, list[StationProduct]],
    ui_endpoints_by_station: dict[str, list[Endpoint]],
) -> None:
    service = make_service(
        service_engine,
        FakeDrovaClientFactory(
            FakeDrovaClient(stations=ui_stations),
            FakeDrovaClient(stations=ui_stations, station_products=ui_products_by_station),
            FakeDrovaClient(stations=ui_stations, endpoints=ui_endpoints_by_station),
        ),
    )
    await service.connect_token(10001, "token")

    disabled = await service.disabled(10001)
    stations = await service.stations(10001)

    assert "Space Farm: отключен" in disabled.text
    assert "203.0.113.11:48000" in stations.text


@pytest.mark.asyncio
async def test_game_commands_use_selected_station_without_callback_uuid_pairs(
    service_engine: AsyncEngine,
    ui_stations: list[Station],
    ui_products_by_station: dict[str, list[StationProduct]],
) -> None:
    edit = ServerProductEdit(
        product_id="product-a",
        title="Cyber Rally",
        enabled=True,
        published=True,
        available=True,
        verified=2,
        default_launch=LaunchParameters(game_path="C:\\Steam\\Steam.exe", args="-language russian"),
        current_launch=LaunchParameters(),
    )
    game_client = FakeDrovaClient(
        stations=ui_stations,
        station_products=ui_products_by_station,
        product_edits={("station-online", "product-a"): edit},
    )
    service = make_service(
        service_engine,
        FakeDrovaClientFactory(
            FakeDrovaClient(stations=ui_stations),
            game_client,
            game_client,
            game_client,
            game_client,
            game_client,
            game_client,
            game_client,
        ),
    )
    await service.connect_token(10001, "token")
    await service.select_station(10001, "station-online")

    games = await service.station_games(10001)
    page = await service.handle_callback(
        10001,
        parse_callback_data(CallbackSpec(action="game_page", page=0).pack()),
    )
    detail = await service.handle_callback(
        10001,
        parse_callback_data(
            CallbackSpec(action="game_select", product_id="product-a", page=0).pack()
        ),
    )
    hidden = await service.handle_callback(
        10001,
        parse_callback_data(CallbackSpec(action="game_hide", product_id="product-a").pack()),
    )
    opened = await service.handle_callback(
        10001,
        parse_callback_data(CallbackSpec(action="game_show", product_id="product-a").pack()),
    )
    hide_all_confirmation = await service.handle_callback(
        10001,
        parse_callback_data(CallbackSpec(action="game_hide_all", product_id="product-b").pack()),
    )
    hidden_all = await service.handle_callback(
        10001,
        parse_callback_data(
            CallbackSpec(action="game_hide_all_confirm", product_id="product-b").pack()
        ),
    )

    assert "Игры станции Alpha Station" in games.text
    assert "product-a" not in games.text
    assert games.keyboard is not None
    assert games.keyboard.rows[0][0].text == "✅ Cyber Rally"
    assert games.keyboard.rows[-1][0].text == "К меню станции"
    assert (
        parse_callback_data(games.keyboard.rows[-1][0].callback_data).action
        == "station_panel"
    )
    assert "Игры станции Alpha Station" in page.text
    assert "Путь: <code>C:\\Steam\\Steam.exe</code>" in detail.text
    assert "Статус: отключена · опубликована · доступна" in hidden.text
    assert hidden.keyboard is not None
    assert hidden.keyboard.rows[0][0].text == "Открыть на станции"
    assert hidden.toast == "Игра скрыта."
    assert "Статус: включена · опубликована · доступна" in opened.text
    assert opened.keyboard is not None
    assert opened.keyboard.rows[0][0].text == "Скрыть на станции"
    assert opened.toast == "Игра открыта."
    assert "Скрыть игру на всех станциях?" in hide_all_confirmation.text
    assert hide_all_confirmation.keyboard is not None
    assert "Обновлено станций: 3" in hidden_all.text
    assert game_client.product_enabled_calls == [
        ("station-online", "product-a", False),
        ("station-online", "product-a", True),
        ("station-online", "product-b", False),
        ("station-hidden", "product-b", False),
        ("station-busy", "product-b", False),
    ]


@pytest.mark.asyncio
async def test_game_hide_all_reports_partial_failures(
    service_engine: AsyncEngine,
    ui_stations: list[Station],
) -> None:
    toggle_client = FakeDrovaClient(
        stations=ui_stations,
        product_toggle_failures={"station-hidden"},
    )
    service = make_service(
        service_engine,
        FakeDrovaClientFactory(
            FakeDrovaClient(stations=ui_stations),
            toggle_client,
        ),
    )
    await service.connect_token(10001, "token")

    message = await service.hide_game_all(10001, "product-b")

    assert toggle_client.product_enabled_calls == [
        ("station-online", "product-b", False),
        ("station-hidden", "product-b", False),
        ("station-busy", "product-b", False),
    ]
    assert "Игра скрыта: <code>product-b</code>" in message.text
    assert "Обновлено станций: 2" in message.text
    assert "Ошибки: Beta Test Station" in message.text


@pytest.mark.asyncio
async def test_publish_confirm_success_cancel_and_stale(
    service_engine: AsyncEngine,
    ui_stations: list[Station],
    ui_sessions: list[Session],
) -> None:
    publish_client = FakeDrovaClient(
        stations=ui_stations,
        sessions=ui_sessions,
        products=[CatalogProduct("product-a", "Cyber Rally")],
    )
    stale_client = FakeDrovaClient(
        stations=[
            replace(station, published=False) if station.uuid == "station-online" else station
            for station in ui_stations
        ],
    )
    service = make_service(
        service_engine,
        FakeDrovaClientFactory(
            FakeDrovaClient(
                stations=ui_stations,
                products=[CatalogProduct("product-a", "Cyber Rally")],
            ),
            FakeDrovaClient(stations=ui_stations),
            publish_client,
            stale_client,
        ),
    )
    await service.connect_token(10001, "token")

    confirmation = await service.publish_confirmation(10001, "station-online")
    success = await service.confirm_publish(10001, "station-online", True)
    stale = await service.confirm_publish(10001, "station-online", True)
    cancel = await service.cancel_publish(10001)

    assert 'Изменить публикацию станции "Alpha Station" на "скрыта"?' in confirmation.text
    assert publish_client.published_calls == [("station-online", False)]
    assert "Alpha Station · скрыта" in success.text
    assert "Состояние станции изменилось" in stale.text
    assert cancel.text == "Отменено."


@pytest.mark.asyncio
async def test_callback_dispatch_selects_all_stations(service_engine: AsyncEngine) -> None:
    service = make_service(service_engine, FakeDrovaClientFactory())
    callback = parse_callback_data(CallbackSpec(action="station_all").pack())

    message = await service.handle_callback(10001, callback)

    assert message.text == "Выбраны все станции."


@pytest.mark.asyncio
async def test_export_not_connected_returns_safe_message(service_engine: AsyncEngine) -> None:
    service = make_service(service_engine, FakeDrovaClientFactory())

    result = await service.export(10001, ExportKind.SESSIONS)

    assert result.files == []
    assert "Сначала подключите" in result.message


@pytest.mark.asyncio
async def test_export_job_lifecycle_marks_success_and_failure(
    service_engine: AsyncEngine,
    ui_stations: list[Station],
    ui_sessions: list[Session],
    ui_catalog: dict[str, str],
) -> None:
    service = make_service(
        service_engine,
        FakeDrovaClientFactory(
            FakeDrovaClient(stations=ui_stations, products=_catalog_products(ui_catalog)),
            FakeDrovaClient(stations=ui_stations, sessions=ui_sessions),
            FakeDrovaClient(stations=ui_stations, sessions=ui_sessions),
        ),
        export_row_limit=1,
    )
    await service.connect_token(10001, "token")

    success_job = await service.create_export_job(10001, ExportKind.PRODUCTS)
    failure_job = await service.create_export_job(10001, ExportKind.SESSIONS)
    success = await service.run_export_job(
        job_id=success_job.id,
        telegram_chat_id=10001,
        kind=ExportKind.PRODUCTS,
    )
    failure = await service.run_export_job(
        job_id=failure_job.id,
        telegram_chat_id=10001,
        kind=ExportKind.SESSIONS,
    )

    session_factory = make_session_factory(service_engine)
    async with session_factory() as session:
        success_row = await session.get(ExportJobRow, success_job.id)
        failure_row = await session.get(ExportJobRow, failure_job.id)

    assert success.files
    assert failure.files == []
    assert success_row is not None
    assert success_row.status == "done"
    assert success_row.finished_at is not None
    assert failure_row is not None
    assert failure_row.status == "failed"
    assert failure_row.error_code == "export_too_large"


@pytest.mark.asyncio
async def test_export_sessions_xlsx_uses_saved_profile_and_fixtures(
    service_engine: AsyncEngine,
    ui_stations: list[Station],
    ui_sessions: list[Session],
    ui_catalog: dict[str, str],
) -> None:
    service = make_service(
        service_engine,
        FakeDrovaClientFactory(
            FakeDrovaClient(stations=ui_stations, products=_catalog_products(ui_catalog)),
            FakeDrovaClient(stations=ui_stations, sessions=ui_sessions),
        ),
    )
    await service.connect_token(10001, "token")

    result = await service.export(10001, ExportKind.SESSIONS)

    assert result.message == "Файл готов."
    assert [file.filename for file in result.files] == ["drova-sessions-20260518-120000.xlsx"]
    assert result.files[0].content_type.endswith("spreadsheetml.sheet")


@pytest.mark.asyncio
async def test_export_sessions_csv_returns_one_file_per_station(
    service_engine: AsyncEngine,
    ui_stations: list[Station],
    ui_sessions: list[Session],
    ui_catalog: dict[str, str],
) -> None:
    service = make_service(
        service_engine,
        FakeDrovaClientFactory(
            FakeDrovaClient(stations=ui_stations, products=_catalog_products(ui_catalog)),
            FakeDrovaClient(stations=ui_stations, sessions=ui_sessions),
        ),
    )
    await service.connect_token(10001, "token")

    result = await service.export(10001, ExportKind.SESSIONS_CSV)

    assert result.message == "Файлы готовы: 3."
    assert [file.filename for file in result.files] == [
        "drova-sessions-alpha-station-20260518-120000.csv",
        "drova-sessions-beta-test-station-20260518-120000.csv",
        "drova-sessions-gamma-trial-20260518-120000.csv",
    ]


@pytest.mark.asyncio
async def test_export_products_and_product_time(
    service_engine: AsyncEngine,
    ui_stations: list[Station],
    ui_sessions: list[Session],
    ui_catalog: dict[str, str],
    ui_products_by_station: dict[str, list[StationProduct]],
) -> None:
    service = make_service(
        service_engine,
        FakeDrovaClientFactory(
            FakeDrovaClient(stations=ui_stations, products=_catalog_products(ui_catalog)),
            FakeDrovaClient(stations=ui_stations, station_products=ui_products_by_station),
            FakeDrovaClient(stations=ui_stations, sessions=ui_sessions),
        ),
    )
    await service.connect_token(10001, "token")

    products = await service.export(10001, ExportKind.PRODUCTS)
    product_time = await service.export(10001, ExportKind.PRODUCT_TIME)

    assert products.files[0].filename == "drova-products-20260518-120000.xlsx"
    assert product_time.files[0].filename == "drova-product-time-20260518-120000.xlsx"


@pytest.mark.asyncio
async def test_export_row_limit_returns_safe_failure(
    service_engine: AsyncEngine,
    ui_stations: list[Station],
    ui_sessions: list[Session],
    ui_catalog: dict[str, str],
) -> None:
    service = make_service(
        service_engine,
        FakeDrovaClientFactory(
            FakeDrovaClient(stations=ui_stations, products=_catalog_products(ui_catalog)),
            FakeDrovaClient(stations=ui_stations, sessions=ui_sessions),
        ),
        export_row_limit=1,
    )
    await service.connect_token(10001, "token")

    result = await service.export(10001, ExportKind.SESSIONS)

    assert result.files == []
    assert "Выгрузка слишком большая" in result.message


def _catalog_products(catalog: dict[str, str]) -> list[CatalogProduct]:
    return [CatalogProduct(product_id, title) for product_id, title in catalog.items()]


def _promocode(code: str, playtime_msecs: int) -> Promocode:
    return Promocode(
        id=14035,
        promocode=code,
        created_on_ms=1779132366809,
        expired_on_ms=1781810766809,
        expired=False,
        merchant_id="merchant-1",
        playtime_msecs=playtime_msecs,
    )
