"""Pure Telegram message renderers."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from math import asin, cos, radians, sin, sqrt

import structlog

from drova_bot.domain.formatters import (
    filter_sessions,
    format_date,
    format_session_duration,
    format_time,
    format_time_short,
    group_endpoints,
    html_escape,
    masked_client_id,
    parse_endpoint_ip,
    product_problem_flags,
    product_title,
    session_duration_seconds,
    sort_stations,
    station_display_name,
)
from drova_bot.domain.models import ChatProfile, Endpoint, Session, Station, StationProduct
from drova_bot.telegram.callbacks import CallbackSpec
from drova_bot.telegram.keyboards import ButtonSpec, KeyboardSpec

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class RenderedMessage:
    text: str
    keyboard: KeyboardSpec | None = None
    parse_mode: str = "HTML"


@dataclass(frozen=True, slots=True)
class EndpointGeo:
    city: str | None = None
    provider: str | None = None
    latitude: float | None = None
    longitude: float | None = None


EndpointGeoResolver = Callable[[Endpoint], EndpointGeo | None]


def render_start_not_connected() -> RenderedMessage:
    return RenderedMessage(
        "Бот Drova для владельца станций.\n\n"
        "Чтобы подключиться, отправьте:\n"
        "/token &lt;proxy_token&gt;\n\n"
        "Токен дает доступ к вашему кабинету. "
        "Используйте только своего бота или доверенный инстанс."
    )


def render_start_connected(
    *,
    station_count: int,
    selected_station_name: str | None,
    session_limit: int,
) -> RenderedMessage:
    selection = selected_station_name or "все станции"
    return RenderedMessage(
        "Бот подключен.\n"
        f"Станций: {station_count}\n"
        f"Выбор: {html_escape(selection)}\n"
        f"Лимит сессий: {session_limit}"
    )


def render_help() -> RenderedMessage:
    commands = [
        "/start - статус подключения",
        "/token &lt;token&gt; - подключить Drova proxy token",
        "/logout - удалить токен и настройки чата",
        "/station - выбрать станцию",
        "/station_all - выбрать все станции",
        "/limit &lt;N&gt; - лимит сессий 1..100",
        "/sessions - последние сессии",
        "/sessions_short - последние сессии дольше 5 минут",
        "/current - состояние станций",
        "/disabled - проблемные продукты",
        "/stations - станции и endpoints",
        "/export_sessions - один XLSX со всеми сессиями",
        "/export_sessions_csv - CSV-файлы по каждой станции",
        "/export_products - XLSX-матрица состояния продуктов по станциям",
        "/export_product_time - XLSX по времени использования продуктов",
        "Совместимость: /station all, /sessions short, /export ..., /dump...",
    ]
    return RenderedMessage("Команды:\n" + "\n".join(commands))


def render_error(code: str) -> RenderedMessage:
    messages = {
        "unknown_command": "Команда не найдена. Используйте /help.",
        "unknown_text": "Я понимаю только команды. Используйте /help.",
        "not_connected": "Сначала подключите Drova token командой /token &lt;proxy_token&gt;.",
        "invalid_limit": "Лимит должен быть числом от 1 до 100.",
        "drova_unavailable": "Drova временно недоступен. Попробуйте позже.",
        "drova_unauthorized": "Токен недействителен. Подключите новый через /token.",
        "stale_publish": "Состояние станции изменилось. Обновите панель публикации.",
        "station_not_found": "Станция не найдена. Обновите список станций.",
    }
    return RenderedMessage(messages.get(code, "Не удалось выполнить команду."))


def render_station_picker(
    stations: Sequence[Station],
    *,
    page: int = 0,
    page_size: int = 8,
) -> RenderedMessage:
    ordered = sort_stations(stations)
    page_count = max(1, (len(ordered) + page_size - 1) // page_size)
    current_page = min(max(page, 0), page_count - 1)
    start = current_page * page_size
    visible = ordered[start : start + page_size]

    rows: list[list[ButtonSpec]] = [
        [ButtonSpec("Все станции", CallbackSpec(action="station_all").pack())]
    ]
    for station in visible:
        rows.append(
            [
                ButtonSpec(
                    station_display_name(station),
                    CallbackSpec(action="station_select", station_id=station.uuid).pack(),
                )
            ]
        )
    if page_count > 1:
        nav: list[ButtonSpec] = []
        if current_page > 0:
            nav.append(
                ButtonSpec(
                    "Назад",
                    CallbackSpec(action="station_page", page=current_page - 1).pack(),
                )
            )
        if current_page + 1 < page_count:
            nav.append(
                ButtonSpec(
                    "Вперед",
                    CallbackSpec(action="station_page", page=current_page + 1).pack(),
                )
            )
        rows.append(nav)

    return RenderedMessage("Выберите станцию:", KeyboardSpec(rows))


def render_sessions(
    profile: ChatProfile,
    sessions: Sequence[Session],
    stations: Sequence[Station],
    product_catalog: Mapping[str, str],
    *,
    now: datetime,
    short_mode: bool = False,
) -> RenderedMessage:
    station_by_id = {station.uuid: station for station in stations}
    selected = station_by_id.get(profile.selected_station_id or "")
    selected_label = selected.name if selected is not None else "все станции"
    header = f"Последние {profile.session_limit} сессий · {selected_label}"
    filtered = filter_sessions(sessions, short_mode=short_mode, now=now)
    if not filtered:
        return RenderedMessage(f"{html_escape(header)}\n\nСессии не найдены.")

    lines = [html_escape(header), ""]
    index = 1
    current_date: str | None = None
    for session in filtered[: profile.session_limit]:
        session_date = format_date(session.created_on_ms, profile.timezone)
        if session_date != current_date:
            current_date = session_date
            if lines[-1] != "":
                lines.append("")
            lines.append(session_date)
        title = product_title(session.product_id, catalog=product_catalog)
        station = station_by_id.get(session.server_id)
        station_name = station.name if station is not None else None
        finish_label = (
            "🟢 now"
            if session.finished_on_ms is None
            else format_time(session.finished_on_ms, profile.timezone)
        )
        duration = format_session_duration(session_duration_seconds(session, now))
        meta = " ".join(
            part
            for part in [
                _billing_label(session.billing_type),
                _status_label(session.status),
            ]
            if part
        )
        lines.extend(
            [
                f"<b>{index}. {html_escape(title)}</b>",
                html_escape(station_name or "станция неизвестна"),
                f"<code>{html_escape(masked_client_id(session.client_id))}</code>",
                html_escape(meta),
                (
                    f"{format_time(session.created_on_ms, profile.timezone)}-"
                    f"{finish_label} ({duration})"
                ),
            ]
        )
        if session.score_text:
            lines.append(f"Отзыв: {html_escape(session.score_text)}")
        index += 1
        lines.append("")

    keyboard = KeyboardSpec(
        rows=[
            [ButtonSpec("Обновить", CallbackSpec(action="sessions_refresh").pack())],
            [
                ButtonSpec(
                    "Показать все" if short_mode else "Скрыть короткие",
                    CallbackSpec(action="sessions_all" if short_mode else "sessions_short").pack(),
                )
            ],
        ]
    )
    return RenderedMessage("\n".join(lines).rstrip(), keyboard)


def _billing_label(billing_type: str | None) -> str:
    billing = (billing_type or "").lower()
    if not billing:
        return ""
    emoji_by_billing = {
        "trial": "🧪",
        "prepaid": "💳",
        "subscription": "🔁",
    }
    return f"{emoji_by_billing.get(billing, '💰')} {billing}"


def _status_label(status: str | None) -> str:
    value = (status or "").lower()
    if not value:
        return ""
    emoji_by_status = {
        "active": "🟢",
        "finished": "✅",
        "aborted": "⛔",
    }
    return f"{emoji_by_status.get(value, 'ℹ️')} {value}"


def render_current(
    profile: ChatProfile,
    stations: Sequence[Station],
    latest_sessions_by_station: Mapping[str, Session | None],
    product_catalog: Mapping[str, str],
    *,
    now: datetime,
    publish_panel_open: bool = False,
    failed_station_ids: set[str] | None = None,
) -> RenderedMessage:
    lines: list[str] = []
    failures = failed_station_ids or set()
    ordered = sort_stations(stations)
    for index, station in enumerate(ordered, start=1):
        session = latest_sessions_by_station.get(station.uuid)
        station_label = station_display_name(station)
        if station.uuid in failures:
            lines.append(f"{index}. {html_escape(station_label)} · ошибка загрузки")
            continue
        if session is None:
            lines.append(f"{index}. {html_escape(station_label)} · нет сессий")
            continue
        title = product_title(session.product_id, catalog=product_catalog)
        duration = format_session_duration(session_duration_seconds(session, now))
        meta = " ".join(
            part
            for part in [
                _billing_label(session.billing_type),
                _current_status_label(session),
            ]
            if part
        )
        meta_suffix = f" · {html_escape(meta)}" if meta else ""
        lines.append(
            f"{index}. {html_escape(station_label)} · <b>{html_escape(title)}</b>"
            f"{meta_suffix} · {format_time_short(session.created_on_ms, profile.timezone)}"
            f" · {duration}"
        )

    rows: list[list[ButtonSpec]] = [
        [ButtonSpec("Обновить", CallbackSpec(action="current_refresh").pack())],
        [ButtonSpec("Публикация", CallbackSpec(action="publish_panel").pack())],
    ]
    if publish_panel_open:
        rows.append(
            [
                ButtonSpec(
                    str(index),
                    CallbackSpec(
                        action="publish_select",
                        station_id=station.uuid,
                        expected_published=station.published,
                    ).pack(),
                )
                for index, station in enumerate(ordered, start=1)
            ]
        )
        rows.append([ButtonSpec("Скрыть панель", CallbackSpec(action="publish_hide").pack())])
    return RenderedMessage("\n".join(lines), KeyboardSpec(rows))


def _current_status_label(session: Session) -> str:
    if not session.status and session.finished_on_ms is None:
        return "🟢 active"
    return _status_label(session.status)


def render_publish_confirmation(station: Station, *, new_state: bool) -> RenderedMessage:
    state_text = "опубликована" if new_state else "скрыта"
    text = (
        f'Изменить публикацию станции "{html_escape(station.name)}" '
        f'на "{state_text}"?'
    )
    return RenderedMessage(
        text,
        KeyboardSpec(
            rows=[
                [
                    ButtonSpec(
                        "Подтвердить",
                        CallbackSpec(
                            action="publish_confirm",
                            station_id=station.uuid,
                            expected_published=station.published,
                        ).pack(),
                    )
                ],
                [ButtonSpec("Отмена", CallbackSpec(action="publish_cancel").pack())],
            ]
        ),
    )


def render_disabled(
    stations: Sequence[Station],
    products_by_station: Mapping[str, Sequence[StationProduct]],
) -> RenderedMessage:
    station_by_id = {station.uuid: station for station in stations}
    lines: list[str] = []
    for station in sort_stations(stations):
        products = [
            product
            for product in products_by_station.get(station.uuid, [])
            if product_problem_flags(product)
        ]
        if not products:
            continue
        if lines:
            lines.append("")
        lines.append(html_escape(station_by_id[station.uuid].name))
        for product in sorted(products, key=lambda item: item.title.casefold()):
            flags = ", ".join(product_problem_flags(product))
            lines.append(f"{html_escape(product.title)}: {html_escape(flags)}")

    if not lines:
        return RenderedMessage("Проблемных продуктов нет.")
    return RenderedMessage("\n".join(lines))


def render_stations(
    stations: Sequence[Station],
    endpoints_by_station: Mapping[str, Sequence[Endpoint]],
    *,
    geo_resolver: EndpointGeoResolver | None = None,
) -> RenderedMessage:
    blocks: list[str] = []
    for station in sort_stations(stations):
        lines = [html_escape(station_display_name(station))]
        if station.city_name:
            lines.append(html_escape(station.city_name))
        external, internal = group_endpoints(endpoints_by_station.get(station.uuid, []))
        if not external and not internal:
            lines.append("Endpoints не найдены.")
        if external:
            lines.append("Внешние:")
            lines.extend(_render_endpoint(endpoint, station, geo_resolver) for endpoint in external)
        if internal:
            lines.append("Внутренние:")
            lines.extend(_render_endpoint(endpoint, station, geo_resolver) for endpoint in internal)
        blocks.append("\n".join(lines))
    return RenderedMessage("\n\n".join(blocks))


def latest_sessions_by_station(sessions: Sequence[Session]) -> dict[str, Session]:
    grouped: dict[str, list[Session]] = defaultdict(list)
    for session in sessions:
        grouped[session.server_id].append(session)
    return {
        station_id: max(items, key=lambda item: item.created_on_ms)
        for station_id, items in grouped.items()
    }


def utc_now() -> datetime:
    return datetime.now(tz=UTC)


def _render_endpoint(
    endpoint: Endpoint,
    station: Station,
    geo_resolver: EndpointGeoResolver | None,
) -> str:
    ip_label = html_escape(endpoint.ip)
    if parse_endpoint_ip(endpoint) is None:
        logger.warning("invalid_endpoint_ip", endpoint_id=endpoint.uuid)
        ip_label = "IP неизвестен"
    parts = [f"{ip_label}:{endpoint.base_port}"]
    geo = _safe_endpoint_geo(endpoint, geo_resolver)
    if geo is not None:
        geo_parts = [value for value in (geo.city, geo.provider) if value]
        distance = _distance_km(station, geo)
        if distance is not None:
            geo_parts.append(f"{distance:.0f} км")
        if geo_parts:
            parts.append(", ".join(html_escape(part) for part in geo_parts))
    return " · ".join(parts)


def _safe_endpoint_geo(
    endpoint: Endpoint,
    geo_resolver: EndpointGeoResolver | None,
) -> EndpointGeo | None:
    if geo_resolver is None or parse_endpoint_ip(endpoint) is None:
        return None
    try:
        return geo_resolver(endpoint)
    except Exception as exc:
        logger.warning(
            "endpoint_geo_lookup_failed",
            endpoint_id=endpoint.uuid,
            error_code=type(exc).__name__,
        )
        return None


def _distance_km(station: Station, geo: EndpointGeo) -> float | None:
    if (
        station.latitude is None
        or station.longitude is None
        or geo.latitude is None
        or geo.longitude is None
    ):
        return None
    station_lat = radians(station.latitude)
    station_lon = radians(station.longitude)
    client_lat = radians(geo.latitude)
    client_lon = radians(geo.longitude)
    lat_delta = client_lat - station_lat
    lon_delta = client_lon - station_lon
    value = sin(lat_delta / 2) ** 2 + cos(station_lat) * cos(client_lat) * sin(lon_delta / 2) ** 2
    return 2 * 6371.0 * asin(sqrt(value))
