"""Pure formatting and domain helper functions."""

from __future__ import annotations

import ipaddress
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from html import escape
from ipaddress import IPv4Address, ip_address, ip_network
from zoneinfo import ZoneInfo

from drova_bot.domain.models import (
    DEFAULT_SESSION_LIMIT,
    MAX_SESSION_LIMIT,
    MIN_SESSION_LIMIT,
    ONLINE_STATES,
    CatalogProduct,
    Endpoint,
    Session,
    Station,
    StationProduct,
)

RFC1918_NETWORKS = (
    ip_network("10.0.0.0/8"),
    ip_network("172.16.0.0/12"),
    ip_network("192.168.0.0/16"),
)


def normalize_session_limit(value: int | str | None) -> int:
    """Return a valid session limit, falling back to the product default."""
    try:
        parsed = int(value) if value is not None else DEFAULT_SESSION_LIMIT
    except (TypeError, ValueError):
        return DEFAULT_SESSION_LIMIT
    if MIN_SESSION_LIMIT <= parsed <= MAX_SESSION_LIMIT:
        return parsed
    return DEFAULT_SESSION_LIMIT


def html_escape(value: object) -> str:
    return escape(str(value), quote=False)


def datetime_from_ms(timestamp_ms: int, timezone: str) -> datetime:
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC).astimezone(ZoneInfo(timezone))


def format_date(timestamp_ms: int, timezone: str) -> str:
    return datetime_from_ms(timestamp_ms, timezone).strftime("%Y-%m-%d")


def format_time(timestamp_ms: int, timezone: str) -> str:
    return datetime_from_ms(timestamp_ms, timezone).strftime("%H:%M:%S")


def format_time_short(timestamp_ms: int, timezone: str) -> str:
    return datetime_from_ms(timestamp_ms, timezone).strftime("%H:%M")


def session_duration_seconds(session: Session, now: datetime) -> int:
    finish_ms = session.finished_on_ms
    if finish_ms is None:
        finish_ms = int(now.astimezone(UTC).timestamp() * 1000)
    return max(0, int((finish_ms - session.created_on_ms) / 1000))


def format_duration(seconds: int) -> str:
    seconds = max(0, seconds)
    minutes, remaining_seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    if days:
        return f"{days} д {hours} ч {minutes} мин"
    if hours:
        return f"{hours} ч {minutes} мин"
    return f"{minutes} мин {remaining_seconds} сек"


def format_duration_compact(seconds: int) -> str:
    seconds = max(0, seconds)
    minutes, _ = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    if days:
        return f"{days} д {hours} ч"
    if hours:
        return f"{hours} ч {minutes} мин"
    return f"{minutes} мин"


def format_export_duration(seconds: int) -> str:
    seconds = max(0, seconds)
    hours, remainder = divmod(seconds, 3600)
    minutes, remaining_seconds = divmod(remainder, 60)
    return f"{hours:02}:{minutes:02}:{remaining_seconds:02}"


def is_short_session(session: Session, now: datetime) -> bool:
    return session_duration_seconds(session, now) <= 5 * 60


def filter_sessions(
    sessions: Iterable[Session],
    *,
    short_mode: bool,
    now: datetime,
) -> list[Session]:
    ordered = sorted(sessions, key=lambda item: item.created_on_ms, reverse=True)
    if not short_mode:
        return ordered
    return [session for session in ordered if not is_short_session(session, now)]


def sort_stations(stations: Iterable[Station]) -> list[Station]:
    return sorted(stations, key=lambda station: station.name.casefold())


def station_badges(station: Station) -> list[str]:
    badges: list[str] = []
    if not station.published:
        badges.append("скрыта")
    if station.state not in ONLINE_STATES:
        badges.append(station.state)
    if any("trial" in group.casefold() for group in station.groups_list):
        badges.append("Trial")
    return badges


def station_display_name(station: Station) -> str:
    badges = station_badges(station)
    if not badges:
        return station.name
    return f"{station.name} · {' · '.join(badges)}"


def product_problem_flags(product: StationProduct) -> list[str]:
    flags: list[str] = []
    if not product.enabled:
        flags.append("отключен")
    if not product.published:
        flags.append("не опубликован")
    if not product.available:
        flags.append("недоступен")
    return flags


def product_title(
    product_id: str,
    *,
    station_product: StationProduct | None = None,
    catalog: Mapping[str, str] | Mapping[str, CatalogProduct] | None = None,
) -> str:
    if station_product is not None and station_product.title:
        return station_product.title
    if catalog is not None and product_id in catalog:
        value = catalog[product_id]
        if isinstance(value, CatalogProduct):
            return value.title
        return value
    return "Неизвестная игра"


def masked_client_id(client_id: str | None) -> str:
    if not client_id:
        return "client неизвестен"
    suffix = client_id[-6:] if len(client_id) > 6 else client_id
    return f"client ...{suffix}"


def endpoint_is_internal(endpoint: Endpoint) -> bool:
    if endpoint.externally_routable is not None:
        return not endpoint.externally_routable
    address = parse_endpoint_ip(endpoint)
    if not isinstance(address, IPv4Address):
        return False
    return any(address in network for network in RFC1918_NETWORKS)


def parse_endpoint_ip(endpoint: Endpoint) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ip_address(endpoint.ip)
    except ValueError:
        return None


def group_endpoints(endpoints: Iterable[Endpoint]) -> tuple[list[Endpoint], list[Endpoint]]:
    external: list[Endpoint] = []
    internal: list[Endpoint] = []
    for endpoint in endpoints:
        if endpoint_is_internal(endpoint):
            internal.append(endpoint)
        else:
            external.append(endpoint)
    return external, internal
