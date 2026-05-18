from __future__ import annotations

from datetime import datetime

from drova_bot.domain.formatters import (
    endpoint_is_internal,
    filter_sessions,
    format_duration,
    format_export_duration,
    group_endpoints,
    normalize_session_limit,
    parse_endpoint_ip,
    product_problem_flags,
    sort_stations,
    station_display_name,
)
from drova_bot.domain.models import Endpoint, Session, Station, StationProduct


def test_duration_formatting() -> None:
    assert format_duration(59) == "0 мин 59 сек"
    assert format_duration(600) == "10 мин 0 сек"
    assert format_duration(3_900) == "1 ч 5 мин"
    assert format_duration(90_000) == "1 д 1 ч 0 мин"
    assert format_export_duration(90_061) == "25:01:01"


def test_short_mode_keeps_only_sessions_strictly_longer_than_five_minutes(
    ui_sessions: list[Session],
    ui_now: datetime,
) -> None:
    filtered = filter_sessions(ui_sessions, short_mode=True, now=ui_now)
    assert [session.uuid for session in filtered] == ["session-3", "session-2"]


def test_product_problem_flags() -> None:
    assert product_problem_flags(
        StationProduct("product", "Game", enabled=False, published=False, available=False)
    ) == ["отключен", "не опубликован", "недоступен"]
    assert product_problem_flags(
        StationProduct("product", "Game", enabled=True, published=True, available=True)
    ) == []


def test_endpoint_grouping_uses_explicit_flag_then_rfc1918() -> None:
    endpoints = [
        Endpoint("external", "station", "203.0.113.11", 48000, True),
        Endpoint("internal-explicit", "station", "198.51.100.7", 48000, False),
        Endpoint("internal-rfc1918", "station", "192.168.1.10", 48000, None),
        Endpoint("external-doc-range", "station", "198.51.100.8", 48000, None),
    ]
    external, internal = group_endpoints(endpoints)
    assert [endpoint.uuid for endpoint in external] == ["external", "external-doc-range"]
    assert [endpoint.uuid for endpoint in internal] == ["internal-explicit", "internal-rfc1918"]
    assert endpoint_is_internal(Endpoint("rfc1918-10", "station", "10.1.2.3", 48000)) is True
    assert endpoint_is_internal(Endpoint("rfc1918-172", "station", "172.16.0.1", 48000)) is True
    assert parse_endpoint_ip(Endpoint("bad", "station", "not-an-ip", 48000)) is None


def test_station_sorting_and_display_badges(ui_stations: list[Station]) -> None:
    assert [station.name for station in sort_stations(ui_stations)] == [
        "Alpha Station",
        "Beta Test Station",
        "Gamma Trial",
    ]
    assert station_display_name(ui_stations[1]) == "Beta Test Station · скрыта · UNVERIFIED"
    assert station_display_name(ui_stations[2]) == "Gamma Trial · Trial"


def test_normalize_session_limit() -> None:
    assert normalize_session_limit(1) == 1
    assert normalize_session_limit("100") == 100
    assert normalize_session_limit(0) == 5
    assert normalize_session_limit("bad") == 5
