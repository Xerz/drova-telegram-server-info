from __future__ import annotations

from datetime import datetime

from drova_bot.domain.models import ChatProfile, Endpoint, Session, Station, StationProduct
from drova_bot.telegram.renderers import (
    EndpointGeo,
    latest_sessions_by_station,
    render_current,
    render_disabled,
    render_error,
    render_help,
    render_sessions,
    render_start_connected,
    render_start_not_connected,
    render_station_picker,
    render_stations,
)


def test_start_and_help_messages_are_russian_and_safe() -> None:
    help_text = render_help().text
    assert "/token &lt;proxy_token&gt;" in render_start_not_connected().text
    assert "Станций: 3" in render_start_connected(
        station_count=3,
        selected_station_name=None,
        session_limit=5,
    ).text
    assert "/station_all - выбрать все станции" in help_text
    assert "/sessions_short - последние сессии дольше 5 минут" in help_text
    assert "/export_sessions - один XLSX со всеми сессиями" in help_text
    assert "/export_sessions_csv - CSV-файлы по каждой станции" in help_text
    assert "/export_products - XLSX-матрица состояния продуктов по станциям" in help_text
    assert "/export_product_time - XLSX по времени использования продуктов" in help_text
    assert "/sessions short -" not in help_text
    assert "/export sessions -" not in help_text
    assert render_error("unknown_command").text == "Команда не найдена. Используйте /help."


def test_station_picker_uses_one_station_per_row(ui_stations: list[Station]) -> None:
    message = render_station_picker(ui_stations)
    assert message.keyboard is not None
    assert message.keyboard.rows[0][0].text == "Все станции"
    assert [row[0].text for row in message.keyboard.rows[1:]] == [
        "Alpha Station",
        "Beta Test Station · скрыта · UNVERIFIED",
        "Gamma Trial · Trial",
    ]


def test_sessions_renderer_matches_fixture_intent(
    ui_profile: ChatProfile,
    ui_sessions: list[Session],
    ui_stations: list[Station],
    ui_catalog: dict[str, str],
    ui_now: datetime,
) -> None:
    message = render_sessions(
        ui_profile,
        ui_sessions,
        ui_stations,
        ui_catalog,
        now=ui_now,
    )
    assert "Последние 5 сессий · все станции" in message.text
    assert "2026-05-18" in message.text
    assert "<b>1. Space Farm</b>" in message.text
    assert "Gamma Trial" in message.text
    assert "<code>client ...abcdef</code>" in message.text
    assert "🧪 trial 🟢 active" in message.text
    assert "💳 prepaid ✅ finished" in message.text
    assert "🔁 subscription ✅ finished" in message.text
    assert "16:40-🟢 now (20 мин)" in message.text
    assert "16:00-16:10 (10 мин)" in message.text
    assert "16:40:00" not in message.text
    assert "16:00:00" not in message.text
    assert "Отзыв: ok" in message.text
    assert "<b>3. Desktop Mode</b>" in message.text
    assert message.keyboard is not None


def test_sessions_renderer_adds_ip_and_city_line(
    ui_profile: ChatProfile,
    ui_sessions: list[Session],
    ui_stations: list[Station],
    ui_catalog: dict[str, str],
    ui_now: datetime,
) -> None:
    def resolver(session: Session) -> EndpointGeo | None:
        if session.uuid == "session-3":
            return EndpointGeo(city="Testburg")
        return None

    message = render_sessions(
        ui_profile,
        ui_sessions,
        ui_stations,
        ui_catalog,
        now=ui_now,
        geo_resolver=resolver,
    )

    assert "IP: <code>198.51.100.30</code> · Testburg" in message.text
    assert "IP: <code>203.0.113.20</code>" in message.text


def test_sessions_renderer_formats_unknown_meta_and_duration_edges(
    ui_profile: ChatProfile,
    ui_stations: list[Station],
) -> None:
    now = datetime.fromisoformat("2026-05-18T12:00:00+00:00")
    sessions = [
        Session(
            uuid="session-seconds",
            server_id="station-online",
            merchant_id="user-1",
            product_id="unknown-product",
            client_id="client-short",
            creator_ip=None,
            created_on_ms=1779105555000,
            finished_on_ms=1779105600000,
            billing_type="promo",
            status="ABORTED",
        ),
        Session(
            uuid="session-hour",
            server_id="station-online",
            merchant_id="user-1",
            product_id="unknown-product",
            client_id="client-hour",
            creator_ip=None,
            created_on_ms=1779100000000,
            finished_on_ms=1779103900000,
            billing_type=None,
            status="QUEUED",
        ),
    ]

    message = render_sessions(ui_profile, sessions, ui_stations, {}, now=now)

    assert "💰 promo ⛔ aborted" in message.text
    assert "ℹ️ queued" in message.text
    assert "(45 сек)" in message.text
    assert "(1 ч 5 мин)" in message.text


def test_sessions_short_mode_hides_short_session(
    ui_profile: ChatProfile,
    ui_sessions: list[Session],
    ui_stations: list[Station],
    ui_catalog: dict[str, str],
    ui_now: datetime,
) -> None:
    message = render_sessions(
        ui_profile,
        ui_sessions,
        ui_stations,
        ui_catalog,
        now=ui_now,
        short_mode=True,
    )
    assert "Desktop Mode" not in message.text
    assert "Показать все" in message.keyboard.rows[1][0].text if message.keyboard else False


def test_current_renderer_matches_fixture_intent(
    ui_profile: ChatProfile,
    ui_sessions: list[Session],
    ui_stations: list[Station],
    ui_catalog: dict[str, str],
    ui_now: datetime,
) -> None:
    message = render_current(
        ui_profile,
        ui_stations,
        latest_sessions_by_station(ui_sessions),
        ui_catalog,
        now=ui_now,
        publish_panel_open=True,
    )
    assert (
        "1. 🌐 Alpha Station · <b>Cyber Rally</b> · 💳 prepaid ✅ finished · 16:00 · 10 мин"
        in message.text
    )
    assert "2. 🔒 Beta Test Station · скрыта · UNVERIFIED · нет сессий" in message.text
    assert (
        "3. 🌐 Gamma Trial · Trial · <b>Space Farm</b> · 🧪 trial 🟢 active · 16:40 · 20 мин"
        in message.text
    )
    assert message.keyboard is not None
    assert message.keyboard.rows[0][0].callback_data.startswith("co")
    assert message.keyboard.rows[1][0].text == "1"
    assert message.keyboard.rows[2][0].text == "Скрыть панель публикации"
    assert "Показать панель публикации" not in [
        button.text for row in message.keyboard.rows for button in row
    ]


def test_current_renderer_adds_city_without_raw_ip(
    ui_profile: ChatProfile,
    ui_sessions: list[Session],
    ui_stations: list[Station],
    ui_catalog: dict[str, str],
    ui_now: datetime,
) -> None:
    def resolver(session: Session) -> EndpointGeo | None:
        if session.uuid == "session-2":
            return EndpointGeo(city="Example City")
        return None

    message = render_current(
        ui_profile,
        ui_stations,
        latest_sessions_by_station(ui_sessions),
        ui_catalog,
        now=ui_now,
        geo_resolver=resolver,
    )

    assert (
        "Cyber Rally</b> · 💳 prepaid ✅ finished · 16:00 · 10 мин · Example City"
        in message.text
    )
    assert "203.0.113.20" not in message.text


def test_current_renderer_hidden_panel_shows_publish_panel_button(
    ui_profile: ChatProfile,
    ui_sessions: list[Session],
    ui_stations: list[Station],
    ui_catalog: dict[str, str],
    ui_now: datetime,
) -> None:
    message = render_current(
        ui_profile,
        ui_stations,
        latest_sessions_by_station(ui_sessions),
        ui_catalog,
        now=ui_now,
    )

    assert message.keyboard is not None
    assert message.keyboard.rows[0][0].callback_data.startswith("cr")
    assert message.keyboard.rows[1][0].text == "Показать панель публикации"


def test_disabled_renderer_matches_fixture_intent(
    ui_stations: list[Station],
    ui_products_by_station: dict[str, list[StationProduct]],
) -> None:
    message = render_disabled(ui_stations, ui_products_by_station)
    assert "Alpha Station\nSpace Farm: отключен" in message.text
    assert "Beta Test Station\nDesktop Mode: не опубликован" in message.text
    assert "Gamma Trial\nSpace Farm: недоступен" in message.text


def test_stations_renderer_matches_fixture_intent(
    ui_stations: list[Station],
    ui_endpoints_by_station: dict[str, list[Endpoint]],
) -> None:
    message = render_stations(ui_stations, ui_endpoints_by_station)
    assert "Alpha Station\nCity A\nВнешние:\n203.0.113.11:48000" in message.text
    assert "Внутренние:\n192.168.1.10:48000" in message.text
    assert "Beta Test Station · скрыта · UNVERIFIED\nEndpoints не найдены." in message.text
    assert "Gamma Trial · Trial\nCity G\nВнешние:\n198.51.100.45:48100" in message.text


def test_stations_renderer_handles_invalid_ip_and_best_effort_geo() -> None:
    station = Station(
        uuid="station-geo",
        name="Geo Station",
        state="LISTEN",
        published=True,
        latitude=56.838,
        longitude=60.605,
    )
    endpoints = {
        "station-geo": [
            Endpoint("good", "station-geo", "8.8.8.8", 48000, True),
            Endpoint("bad", "station-geo", "not-an-ip", 48001, True),
        ],
    }

    def resolver(endpoint: Endpoint) -> EndpointGeo:
        assert endpoint.uuid == "good"
        return EndpointGeo(
            city="Mountain View",
            provider="Google",
            latitude=37.386,
            longitude=-122.084,
        )

    message = render_stations([station], endpoints, geo_resolver=resolver)

    assert "8.8.8.8:48000 · Mountain View, Google," in message.text
    assert "км" in message.text
    assert "IP неизвестен:48001" in message.text


def test_stations_renderer_ignores_geo_lookup_failure() -> None:
    station = Station(uuid="station-geo", name="Geo Station", state="LISTEN", published=True)
    endpoints = {"station-geo": [Endpoint("good", "station-geo", "8.8.8.8", 48000, True)]}

    def resolver(endpoint: Endpoint) -> EndpointGeo:
        raise RuntimeError("geo unavailable")

    message = render_stations([station], endpoints, geo_resolver=resolver)

    assert message.text == "Geo Station\nВнешние:\n8.8.8.8:48000"
