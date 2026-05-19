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
    format_duration_compact,
    format_session_duration,
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
from drova_bot.domain.models import (
    ChatProfile,
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
    Station,
    StationProduct,
    UsagePeriod,
    UsageStat,
)
from drova_bot.telegram.callbacks import CallbackSpec
from drova_bot.telegram.keyboards import ButtonSpec, KeyboardSpec

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class RenderedMessage:
    text: str
    keyboard: KeyboardSpec | None = None
    parse_mode: str = "HTML"
    toast: str | None = None


@dataclass(frozen=True, slots=True)
class EndpointGeo:
    city: str | None = None
    provider: str | None = None
    latitude: float | None = None
    longitude: float | None = None


EndpointGeoResolver = Callable[[Endpoint], EndpointGeo | None]
SessionGeoResolver = Callable[[Session], EndpointGeo | None]
SESSION_PAGE_SIZE = 5
GAME_PAGE_SIZE = 10


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
        "/account - баланс минут и выплаты",
        "/usage - статистика использования",
        "/disabled - проблемные продукты",
        "/stations - станции и endpoints",
        "/games - выбрать игру на выбранной станции",
        "/desktop_on - включить полный доступ на выбранной станции",
        "/desktop_off - выключить полный доступ на выбранной станции",
        "/updates_on - включить обновления на выбранной станции",
        "/updates_off - выключить обновления на выбранной станции",
        "/server_source - исходник описания выбранной станции",
        "/server_description &lt;text&gt; - обновить описание выбранной станции",
        "/promocode &lt;minutes&gt; - выпустить prepaid-промокод",
        "/promocodes - неактивированные prepaid-промокоды",
        "/export_sessions - один XLSX со всеми сессиями",
        "/export_sessions_csv - CSV-файлы по каждой станции",
        "/export_products - XLSX-матрица состояния продуктов по станциям",
        "/export_product_time - XLSX по времени использования продуктов",
        "Совместимость: /station all, /sessions short, /export ..., /dump..., /game...",
    ]
    return RenderedMessage("Команды:\n" + "\n".join(commands))


def render_error(code: str) -> RenderedMessage:
    messages = {
        "unknown_command": "Команда не найдена. Используйте /help.",
        "unknown_text": "Я понимаю только команды. Используйте /help.",
        "not_connected": "Сначала подключите Drova token командой /token &lt;proxy_token&gt;.",
        "invalid_limit": "Лимит должен быть числом от 1 до 100.",
        "invalid_promocode_minutes": "Укажите количество минут целым числом больше 0.",
        "invalid_product_id": "Выберите игру через /games.",
        "station_required": "Сначала выберите одну станцию через /station.",
        "invalid_server_control": "Команда управления не найдена.",
        "invalid_server_control_confirmation": (
            "Подтверждение устарело. Сначала отправьте команду управления заново."
        ),
        "invalid_server_description": (
            "Укажите новое описание. Например: /server_description &lt;text&gt;."
        ),
        "stale_server_control": "Состояние уже изменилось. Обновите команду управления.",
        "stale_server_source": "Описание станции уже изменилось. Сначала выполните /server_source.",
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


def render_promocode_issued(
    promocodes: Sequence[Promocode],
    *,
    requested_minutes: int,
    timezone: str,
) -> RenderedMessage:
    if not promocodes:
        return RenderedMessage("Промокод не выпущен. Попробуйте позже.")
    header = (
        f"Выпущен промокод на {requested_minutes} мин:"
        if len(promocodes) == 1
        else f"Выпущены промокоды на {requested_minutes} мин:"
    )
    lines = [header, *[_promocode_line(promocode, timezone) for promocode in promocodes]]
    return RenderedMessage("\n".join(lines))


def render_unused_promocodes(
    promocodes: Sequence[Promocode],
    *,
    timezone: str,
) -> RenderedMessage:
    if not promocodes:
        return RenderedMessage("Неактивированных промокодов нет.")
    lines = [
        "Неактивированные промокоды:",
        *[_promocode_line(promocode, timezone) for promocode in promocodes],
    ]
    return RenderedMessage("\n".join(lines))


def _promocode_line(promocode: Promocode, timezone: str) -> str:
    minutes = max(0, promocode.playtime_msecs // 60_000)
    expires_at = (
        f"{format_date(promocode.expired_on_ms, timezone)} "
        f"{format_time_short(promocode.expired_on_ms, timezone)}"
    )
    return f"<code>{html_escape(promocode.promocode)}</code> · {minutes} мин · до {expires_at}"


def render_account_billing(
    stats: PrepaidStats,
    *,
    settlements: Sequence[PrepaidSettlement],
    opened_deals: Sequence[OpenedPrepaidDeal],
    timezone: str,
) -> RenderedMessage:
    lines = [
        "Аккаунт",
        "",
        "Минуты",
        f"Доступно к продаже: {_format_integer(stats.allowed_to_sell_minutes)} мин",
        f"Продано: {_format_integer(stats.sold_minutes)} мин",
        f"Использовано: {_format_integer(stats.used_minutes)} мин",
        f"Баланс минут: {_format_money(stats.balance)}",
        "",
        "Открытые выплаты",
    ]
    if opened_deals:
        lines.extend(_opened_deal_line(deal, timezone) for deal in opened_deals[:5])
    else:
        lines.append("Нет открытых выплат.")

    lines.extend(["", "Последние операции с минутами"])
    if settlements:
        lines.extend(
            _prepaid_settlement_line(settlement, timezone)
            for settlement in settlements[:5]
        )
    else:
        lines.append("Операций нет.")

    return RenderedMessage("\n".join(lines))


def render_usage_statistics(
    statistics: ServerUsageStatistics,
    stations: Sequence[Station],
    product_catalog: Mapping[str, str],
    *,
    top_limit: int = 5,
) -> RenderedMessage:
    station_names = {station.uuid: station.name for station in stations}
    lines = [
        "Статистика использования",
        "",
        _usage_total_line("Сегодня", statistics.today.total),
        _usage_total_line("Неделя", statistics.week.total),
        _usage_total_line("Месяц", statistics.month.total),
        "",
        "Топ станций за месяц",
    ]
    lines.extend(
        _usage_ranked_lines(
            statistics.month,
            labels=station_names,
            top_limit=top_limit,
            unknown_label="станция",
            source="server",
        )
    )
    lines.extend(["", "Топ игр за месяц"])
    lines.extend(
        _usage_ranked_lines(
            statistics.month,
            labels=product_catalog,
            top_limit=top_limit,
            unknown_label="product",
            source="game",
        )
    )
    return RenderedMessage("\n".join(lines))


def render_server_control_confirmation(
    station: Station,
    source: ServerSource,
    *,
    action: str,
) -> RenderedMessage:
    label = _server_control_label(action)
    if label is None:
        return render_error("invalid_server_control")
    current_on = _server_control_current_on(source, action)
    target_on = _server_control_target_on(action)
    state = _server_control_state_word(action, current_on)
    if current_on == target_on:
        return RenderedMessage(
            f"{label} уже {state}: {html_escape(station.name)}\n"
            f"Текущее состояние: {state}"
        )
    expected_state = "on" if current_on else "off"
    target_state = _server_control_state_word(action, target_on)
    command = f"/{action}_confirm {expected_state}"
    return RenderedMessage(
        f"Станция {html_escape(station.name)}\n"
        f"{label} сейчас: {state}\n\n"
        f"Чтобы переключить на {target_state}, отправьте:\n"
        f"<code>{html_escape(command)}</code>"
    )


def render_server_control_result(
    station: Station,
    source: ServerSource,
    *,
    action: str,
) -> RenderedMessage:
    label = _server_control_label(action)
    if label is None:
        return render_error("invalid_server_control")
    current_on = _server_control_current_on(source, action)
    state = _server_control_state_word(action, current_on)
    return RenderedMessage(
        f"{label} {state}: {html_escape(station.name)}\n"
        f"Текущее состояние: {state}"
    )


def render_server_source(station: Station, source: ServerSource) -> RenderedMessage:
    description, truncated = _truncated_description(source.description)
    lines = [
        f"Исходник описания станции {html_escape(station.name)}",
        f"Название: <code>{html_escape(source.name)}</code>",
        "",
        "Описание:",
        f"<pre>{html_escape(description)}</pre>",
    ]
    if truncated:
        lines.append("Описание обрезано до безопасной длины сообщения.")
    return RenderedMessage("\n".join(lines))


def render_server_description_preview(
    station: Station,
    *,
    description: str,
    revision: str,
) -> RenderedMessage:
    preview, truncated = _truncated_description(description)
    command = f"/server_description_apply {revision} {description}"
    command_preview, command_truncated = _truncated_description(command, max_length=1200)
    lines = [
        f"Новое описание для {html_escape(station.name)}",
        f"Ревизия текущего описания: <code>{html_escape(revision)}</code>",
        "",
        "Предпросмотр:",
        f"<pre>{html_escape(preview)}</pre>",
        "",
        "Чтобы применить, отправьте:",
        f"<code>{html_escape(command_preview)}</code>",
    ]
    if truncated or command_truncated:
        lines.append("Длинное описание обрезано в предпросмотре; отправьте apply-команду вручную.")
    return RenderedMessage("\n".join(lines))


def render_server_description_result(station: Station, *, revision: str) -> RenderedMessage:
    return RenderedMessage(
        f"Описание обновлено: {html_escape(station.name)}\n"
        f"Новая ревизия: <code>{html_escape(revision)}</code>"
    )


def _truncated_description(description: str, max_length: int = 3000) -> tuple[str, bool]:
    if len(description) <= max_length:
        return description, False
    return description[:max_length], True


def _server_control_label(action: str) -> str | None:
    if action.startswith("desktop_"):
        return "Полный доступ"
    if action.startswith("updates_"):
        return "Обновления"
    return None


def _server_control_current_on(source: ServerSource, action: str) -> bool:
    if action.startswith("desktop_"):
        return source.allow_desktop
    return not source.disable_updates


def _server_control_target_on(action: str) -> bool:
    return action.endswith("_on")


def _server_control_state_word(action: str, enabled: bool) -> str:
    if action.startswith("updates_"):
        return "включены" if enabled else "выключены"
    return "включен" if enabled else "выключен"


def _usage_total_line(label: str, stat: UsageStat) -> str:
    return (
        f"{label}: {_format_integer(stat.session_count)} сессий · "
        f"{format_duration_compact(stat.total_msecs // 1000)}"
    )


def _usage_ranked_lines(
    period: UsagePeriod,
    *,
    labels: Mapping[str, str],
    top_limit: int,
    unknown_label: str,
    source: str,
) -> list[str]:
    data = period.per_server if source == "server" else period.per_game
    rows = sorted(
        data.items(),
        key=lambda item: (item[1].total_msecs, item[1].session_count, item[0]),
        reverse=True,
    )[:top_limit]
    if not rows:
        return ["Нет данных."]
    lines: list[str] = []
    for index, (item_id, stat) in enumerate(rows, start=1):
        label = labels.get(item_id)
        rendered_label = (
            html_escape(label)
            if label is not None
            else f"{unknown_label} <code>{html_escape(item_id)}</code>"
        )
        lines.append(
            f"{index}. {rendered_label} · {_format_integer(stat.session_count)} сессий · "
            f"{format_duration_compact(stat.total_msecs // 1000)}"
        )
    return lines


def render_station_games(
    station: Station,
    products: Sequence[StationProduct],
    *,
    page: int = 0,
    page_size: int = GAME_PAGE_SIZE,
) -> RenderedMessage:
    ordered = sorted(products, key=lambda item: item.title.casefold())
    safe_page_size = max(1, page_size)
    page_count = max(1, (len(ordered) + safe_page_size - 1) // safe_page_size)
    current_page = min(max(page, 0), page_count - 1)
    start = current_page * safe_page_size
    visible = ordered[start : start + safe_page_size]
    lines = [
        f"Игры станции {html_escape(station.name)} · стр. {current_page + 1}/{page_count}",
        "Выберите игру:",
    ]
    if not ordered:
        lines.append("Игры не найдены.")
        return RenderedMessage("\n".join(lines))

    rows: list[list[ButtonSpec]] = []
    for product in visible:
        flags = product_problem_flags(product)
        marker = "✅" if product.enabled and product.published and product.available else "🚫"
        suffix = f" · {', '.join(flags)}" if flags else ""
        rows.append(
            [
                ButtonSpec(
                    _truncate_button_text(f"{marker} {product.title}{suffix}"),
                    CallbackSpec(
                        action="game_select",
                        product_id=product.product_id,
                        page=current_page,
                    ).pack(),
                )
            ]
        )
    if page_count > 1:
        nav: list[ButtonSpec] = []
        if current_page > 0:
            nav.append(
                ButtonSpec(
                    "Назад",
                    CallbackSpec(action="game_page", page=current_page - 1).pack(),
                )
            )
        if current_page + 1 < page_count:
            nav.append(
                ButtonSpec(
                    "Вперед",
                    CallbackSpec(action="game_page", page=current_page + 1).pack(),
                )
            )
        rows.append(nav)
    return RenderedMessage("\n".join(lines), KeyboardSpec(rows))


def render_station_game_detail(
    station: Station,
    product: ServerProductEdit,
    *,
    page: int = 0,
) -> RenderedMessage:
    flags = []
    flags.append("включена" if product.enabled else "отключена")
    flags.append("опубликована" if product.published else "не опубликована")
    flags.append("доступна" if product.available else "недоступна")
    lines = [
        f"Игра на станции {html_escape(station.name)}",
        f"<b>{html_escape(product.title)}</b>",
        f"Технический ID: <code>{html_escape(product.product_id)}</code>",
        f"Статус: {html_escape(' · '.join(flags))}",
        "",
        "Параметры запуска по умолчанию",
        *_launch_lines(product.default_launch),
        "",
        "Переопределения",
    ]
    override_lines = _launch_lines(product.current_launch)
    if override_lines:
        lines.extend(override_lines)
    else:
        lines[-1] = "Переопределения: нет"
    primary_action = "game_hide" if product.enabled else "game_show"
    primary_text = "Скрыть на станции" if product.enabled else "Открыть на станции"
    keyboard = KeyboardSpec(
        [
            [
                ButtonSpec(
                    primary_text,
                    CallbackSpec(
                        action=primary_action,
                        product_id=product.product_id,
                        page=page,
                    ).pack(),
                )
            ],
            [
                ButtonSpec(
                    "Скрыть на всех станциях",
                    CallbackSpec(
                        action="game_hide_all_prompt",
                        product_id=product.product_id,
                        page=page,
                    ).pack(),
                )
            ],
            [
                ButtonSpec(
                    "К списку игр",
                    CallbackSpec(action="game_page", page=page).pack(),
                )
            ],
        ]
    )
    return RenderedMessage("\n".join(lines), keyboard)


def render_game_hide_all_confirmation(
    station: Station,
    product: ServerProductEdit,
    *,
    page: int = 0,
) -> RenderedMessage:
    keyboard = KeyboardSpec(
        [
            [
                ButtonSpec(
                    "Да, скрыть на всех",
                    CallbackSpec(
                        action="game_hide_all_confirm",
                        product_id=product.product_id,
                        page=page,
                    ).pack(),
                )
            ],
            [
                ButtonSpec(
                    "Отмена",
                    CallbackSpec(
                        action="game_select",
                        product_id=product.product_id,
                        page=page,
                    ).pack(),
                )
            ],
        ]
    )
    return RenderedMessage(
        "Скрыть игру на всех станциях?\n"
        f"<b>{html_escape(product.title)}</b>\n"
        f"Текущая станция: {html_escape(station.name)}\n\n"
        "Действие применится ко всем станциям аккаунта.",
        keyboard,
    )


def render_game_enabled_result(
    *,
    product_title: str | None,
    product_id: str,
    enabled: bool,
    updated_station_names: Sequence[str],
    failed_station_names: Sequence[str] = (),
) -> RenderedMessage:
    action = "открыта" if enabled else "скрыта"
    title = (
        f"<b>{html_escape(product_title)}</b>"
        if product_title
        else f"<code>{html_escape(product_id)}</code>"
    )
    lines = [
        f"Игра {action}: {title}",
        f"Технический ID: <code>{html_escape(product_id)}</code>",
        f"Обновлено станций: {len(updated_station_names)}",
    ]
    if updated_station_names:
        lines.append("Станции: " + html_escape(", ".join(updated_station_names)))
    if failed_station_names:
        lines.append("Ошибки: " + html_escape(", ".join(failed_station_names)))
    return RenderedMessage("\n".join(lines))


def _truncate_button_text(value: str, *, limit: int = 60) -> str:
    if len(value) <= limit:
        return value
    return value[: max(1, limit - 1)].rstrip() + "…"


def _launch_lines(parameters: LaunchParameters) -> list[str]:
    lines: list[str] = []
    if parameters.game_path:
        lines.append(f"Путь: <code>{html_escape(parameters.game_path)}</code>")
    if parameters.work_path:
        lines.append(f"Рабочая папка: <code>{html_escape(parameters.work_path)}</code>")
    if parameters.args:
        lines.append(f"Аргументы: <code>{html_escape(parameters.args)}</code>")
    if parameters.allowed_paths:
        lines.append(f"Доступные пути: <code>{html_escape(parameters.allowed_paths)}</code>")
    return lines


def _prepaid_settlement_line(settlement: PrepaidSettlement, timezone: str) -> str:
    minutes = max(0, settlement.playtime_msecs // 60_000)
    created_at = (
        f"{format_date(settlement.created_on_ms, timezone)} "
        f"{format_time_short(settlement.created_on_ms, timezone)}"
    )
    source = "заказ" if settlement.has_order else "без заказа"
    return f"{created_at} · {_format_integer(minutes)} мин · {source}"


def _opened_deal_line(deal: OpenedPrepaidDeal, timezone: str) -> str:
    created_at = (
        f"{format_date(deal.created_on_ms, timezone)} "
        f"{format_time_short(deal.created_on_ms, timezone)}"
    )
    return (
        f"{created_at} · сумма {_format_money(deal.gross_amount)} · "
        f"к выплате {_format_money(deal.payout_amount)}"
    )


def _format_integer(value: int) -> str:
    return f"{value:,}".replace(",", " ")


def _format_money(value: float | None) -> str:
    if value is None:
        return "скрыто"
    return f"{value:,.2f}".replace(",", " ")


def render_sessions(
    profile: ChatProfile,
    sessions: Sequence[Session],
    stations: Sequence[Station],
    product_catalog: Mapping[str, str],
    *,
    now: datetime,
    short_mode: bool = False,
    page: int = 0,
    geo_resolver: SessionGeoResolver | None = None,
) -> RenderedMessage:
    station_by_id = {station.uuid: station for station in stations}
    selected = station_by_id.get(profile.selected_station_id or "")
    selected_label = selected.name if selected is not None else "все станции"
    filtered = filter_sessions(sessions, short_mode=short_mode, now=now)
    page_index = _bounded_page(page, len(filtered))
    header = f"Последние {profile.session_limit} сессий · {selected_label} · стр. {page_index + 1}"
    if not filtered:
        return RenderedMessage(f"{html_escape(header)}\n\nСессии не найдены.")

    lines = [html_escape(header), ""]
    page_start = page_index * SESSION_PAGE_SIZE
    page_sessions = filtered[page_start : page_start + SESSION_PAGE_SIZE]
    index = page_start + 1
    current_date: str | None = None
    for session in page_sessions:
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
            else format_time_short(session.finished_on_ms, profile.timezone)
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
        geo_line = _session_geo_line(session, geo_resolver)
        lines.extend(
            [
                f"<b>{index}. {html_escape(title)}</b>",
                html_escape(station_name or "станция неизвестна"),
                f"<code>{html_escape(masked_client_id(session.client_id))}</code>",
            ]
        )
        if geo_line:
            lines.append(geo_line)
        if meta:
            lines.append(html_escape(meta))
        lines.append(
            f"{format_time_short(session.created_on_ms, profile.timezone)}-"
            f"{finish_label} ({duration})"
        )
        if session.score_text:
            lines.append(f"Отзыв: {html_escape(session.score_text)}")
        index += 1
        lines.append("")

    keyboard = KeyboardSpec(rows=_session_keyboard_rows(short_mode, page_index, len(filtered)))
    return RenderedMessage("\n".join(lines).rstrip(), keyboard)


def _bounded_page(page: int, item_count: int) -> int:
    if item_count <= 0:
        return 0
    last_page = (item_count - 1) // SESSION_PAGE_SIZE
    return min(max(0, page), last_page)


def _session_keyboard_rows(short_mode: bool, page: int, item_count: int) -> list[list[ButtonSpec]]:
    page_action = "sessions_short_page" if short_mode else "sessions_page"
    rows = [[ButtonSpec("Обновить", CallbackSpec(action=page_action, page=page).pack())]]
    page_buttons: list[ButtonSpec] = []
    if page > 0:
        page_buttons.append(
            ButtonSpec("Назад", CallbackSpec(action=page_action, page=page - 1).pack())
        )
    if (page + 1) * SESSION_PAGE_SIZE < item_count:
        page_buttons.append(
            ButtonSpec("Вперед", CallbackSpec(action=page_action, page=page + 1).pack())
        )
    if page_buttons:
        rows.append(page_buttons)
    rows.append(
        [
            ButtonSpec(
                "Показать все" if short_mode else "Скрыть короткие",
                CallbackSpec(
                    action="sessions_all" if short_mode else "sessions_short",
                    page=page,
                ).pack(),
            )
        ]
    )
    return rows


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
    geo_resolver: SessionGeoResolver | None = None,
) -> RenderedMessage:
    lines: list[str] = []
    failures = failed_station_ids or set()
    ordered = sort_stations(stations)
    for index, station in enumerate(ordered, start=1):
        session = latest_sessions_by_station.get(station.uuid)
        station_label = station_display_name(station)
        line_prefix = f"{index}. {_publication_marker(station)}"
        if station.uuid in failures:
            lines.append(f"{line_prefix} {html_escape(station_label)} · ошибка загрузки")
            continue
        if session is None:
            lines.append(f"{line_prefix} {html_escape(station_label)} · нет сессий")
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
        city = _session_geo_city(session, geo_resolver)
        city_suffix = f" · {html_escape(city)}" if city else ""
        lines.append(
            f"{line_prefix} {html_escape(station_label)} · <b>{html_escape(title)}</b>"
            f"{meta_suffix} · {format_time_short(session.created_on_ms, profile.timezone)}"
            f" · {duration}{city_suffix}"
        )

    rows: list[list[ButtonSpec]] = [
        [
            ButtonSpec(
                "Обновить",
                CallbackSpec(
                    action="current_refresh_panel" if publish_panel_open else "current_refresh",
                ).pack(),
            )
        ],
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
        rows.append(
            [ButtonSpec("Скрыть панель публикации", CallbackSpec(action="publish_hide").pack())]
        )
    else:
        rows.append(
            [
                ButtonSpec(
                    "Показать панель публикации",
                    CallbackSpec(action="publish_panel").pack(),
                )
            ]
        )
    return RenderedMessage("\n".join(lines), KeyboardSpec(rows))


def _current_status_label(session: Session) -> str:
    if not session.status and session.finished_on_ms is None:
        return "🟢 active"
    return _status_label(session.status)


def _publication_marker(station: Station) -> str:
    return "🌐" if station.published else "🔒"


def _session_geo_line(
    session: Session,
    geo_resolver: SessionGeoResolver | None,
) -> str | None:
    if not session.creator_ip:
        return None
    parts = [f"IP: <code>{html_escape(session.creator_ip)}</code>"]
    city = _session_geo_city(session, geo_resolver)
    if city:
        parts.append(html_escape(city))
    return " · ".join(parts)


def _session_geo_city(
    session: Session,
    geo_resolver: SessionGeoResolver | None,
) -> str | None:
    geo = _safe_session_geo(session, geo_resolver)
    if geo is None or not geo.city:
        return None
    return geo.city


def _safe_session_geo(
    session: Session,
    geo_resolver: SessionGeoResolver | None,
) -> EndpointGeo | None:
    if geo_resolver is None or not session.creator_ip:
        return None
    try:
        return geo_resolver(session)
    except Exception as exc:
        logger.warning(
            "session_geo_lookup_failed",
            session_id=session.uuid,
            error_code=type(exc).__name__,
        )
        return None


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
