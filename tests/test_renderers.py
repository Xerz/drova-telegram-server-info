from __future__ import annotations

from datetime import datetime

from drova_bot.domain.models import ChatProfile, Endpoint, Session, Station, StationProduct
from drova_bot.telegram.renderers import (
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
    assert "/token &lt;proxy_token&gt;" in render_start_not_connected().text
    assert "Станций: 3" in render_start_connected(
        station_count=3,
        selected_station_name=None,
        session_limit=5,
    ).text
    assert "/sessions short" in render_help().text
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
    assert "1. Space Farm" in message.text
    assert "Gamma Trial" in message.text
    assert "client ...abcdef" in message.text
    assert "trial active" in message.text
    assert "16:40:00-now (20 мин 0 сек)" in message.text
    assert "Отзыв: ok" in message.text
    assert "3. Desktop Mode" in message.text
    assert message.keyboard is not None


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
    assert "1. Alpha Station · Cyber Rally · 16:00 · 10 мин" in message.text
    assert "2. Beta Test Station · скрыта · UNVERIFIED · нет сессий" in message.text
    assert "3. Gamma Trial · Trial · Space Farm · active · 16:40 · 20 мин" in message.text
    assert message.keyboard is not None
    assert message.keyboard.rows[2][0].text == "1"


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
