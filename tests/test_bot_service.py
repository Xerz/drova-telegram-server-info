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
    Promocode,
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
        station_products: dict[str, list[StationProduct]] | None = None,
        endpoints: dict[str, list[Endpoint]] | None = None,
        unauthorized: bool = False,
        session_failures: set[str] | None = None,
    ) -> None:
        self._proxy_token = token
        self.account = account or Account(uuid="user-1", name="Owner")
        self.stations = stations or []
        self.products = products or []
        self.sessions_data = sessions or []
        self.promocodes = promocodes or []
        self.station_products = station_products or {}
        self.endpoints = endpoints or {}
        self.unauthorized = unauthorized
        self.session_failures = session_failures or set()
        self.closed = False
        self.published_calls: list[tuple[str, bool]] = []
        self.issued_promocode_minutes: list[int] = []

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
async def test_current_refresh_panel_callback_keeps_publish_panel_open(
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
        ),
    )
    await service.connect_token(10001, "token")

    message = await service.handle_callback(
        10001,
        parse_callback_data(CallbackSpec(action="current_refresh_panel").pack()),
    )

    assert message.keyboard is not None
    assert message.keyboard.rows[1][0].text == "1"
    assert message.keyboard.rows[2][0].text == "Скрыть панель публикации"


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
