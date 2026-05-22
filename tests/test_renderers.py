from __future__ import annotations

from dataclasses import replace
from datetime import datetime

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
)
from drova_bot.telegram.callbacks import parse_callback_data
from drova_bot.telegram.renderers import (
    EndpointGeo,
    latest_sessions_by_station,
    render_account_billing,
    render_account_menu,
    render_current,
    render_disabled,
    render_error,
    render_game_enabled_result,
    render_game_hide_all_confirmation,
    render_help,
    render_promocode_issued,
    render_server_control_confirmation,
    render_server_control_result,
    render_server_description_preview,
    render_server_description_request,
    render_server_description_result,
    render_server_source,
    render_sessions,
    render_start_connected,
    render_start_not_connected,
    render_station_game_detail,
    render_station_games,
    render_station_manage_panel,
    render_station_manage_picker,
    render_station_picker,
    render_stations,
    render_unused_promocodes,
    render_usage_statistics,
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
    assert "/station_manage - управление станциями" in help_text
    assert "/account_menu - меню аккаунта" in help_text
    assert "/sessions_short - последние сессии дольше 5 минут" in help_text
    assert "/usage - статистика использования" in help_text
    assert "/desktop_on - включить полный доступ на выбранной станции" in help_text
    assert "/updates_off - выключить обновления на выбранной станции" in help_text
    assert "/server_source - исходник описания выбранной станции" in help_text
    assert "/server_description &lt;text&gt; - обновить описание выбранной станции" in help_text
    assert "/promocode &lt;minutes&gt; - выпустить prepaid-промокод" in help_text
    assert "/promocodes - неактивированные prepaid-промокоды" in help_text
    assert "/export_sessions - один XLSX со всеми сессиями" in help_text
    assert "/export_sessions_csv - CSV-файлы по каждой станции" in help_text
    assert "/export_products - XLSX-матрица состояния продуктов по станциям" in help_text
    assert "/export_product_time - XLSX по времени использования продуктов" in help_text
    assert "/games - выбрать игру на выбранной станции" in help_text
    assert "/game &lt;product_id&gt; -" not in help_text
    assert "/sessions short -" not in help_text
    assert "/export sessions -" not in help_text
    assert render_error("unknown_command").text == "Команда не найдена. Используйте /help."
    assert "целым числом больше 0" in render_error("invalid_promocode_minutes").text


def test_account_billing_renderer_formats_minutes_and_payments() -> None:
    message = render_account_billing(
        PrepaidStats(
            merchant_id="merchant-1",
            allowed_to_sell_minutes=2683,
            sold_minutes=205126,
            used_minutes=207817,
            balance=123.5,
        ),
        settlements=[
            PrepaidSettlement(
                uuid="settlement-1",
                client_id=None,
                created_on_ms=1779125315305,
                has_order=True,
                playtime_msecs=10_800_000,
            )
        ],
        opened_deals=[
            OpenedPrepaidDeal(
                created_on_ms=1777593600000,
                deal_id="deal-1",
                payout_amount=10340.79,
                gross_amount=13390.0,
                terminal_index=0,
            )
        ],
        timezone="Asia/Yekaterinburg",
    )

    assert "Аккаунт" in message.text
    assert "Доступно к продаже: 2 683 мин" in message.text
    assert "Баланс минут: 123.50" in message.text
    assert "2026-05-18 22:28 · 180 мин · заказ" in message.text
    assert "2026-05-01 05:00 · сумма 13 390.00 · к выплате 10 340.79" in message.text


def test_usage_statistics_renderer_shows_totals_and_top_rows(
    ui_stations: list[Station],
    ui_catalog: dict[str, str],
    ui_usage_statistics: ServerUsageStatistics,
) -> None:
    message = render_usage_statistics(ui_usage_statistics, ui_stations, ui_catalog)

    assert "Статистика использования" in message.text
    assert "Сегодня: 2 сессий · 2 ч 10 мин" in message.text
    assert "Неделя: 7 сессий · 9 ч 10 мин" in message.text
    assert "Месяц: 10 сессий · 16 ч 0 мин" in message.text
    assert "1. Alpha Station · 8 сессий · 12 ч 0 мин" in message.text
    assert "2. Beta Test Station · 2 сессий · 4 ч 0 мин" in message.text
    assert "1. Cyber Rally · 6 сессий · 10 ч 0 мин" in message.text
    assert "2. Space Farm · 4 сессий · 6 ч 0 мин" in message.text
    assert "totalincome" not in message.text.lower()


def test_server_control_renderers_use_command_confirmation_without_raw_source(
    ui_stations: list[Station],
    ui_server_source: ServerSource,
) -> None:
    station = ui_stations[0]
    confirmation = render_server_control_confirmation(
        station,
        ui_server_source,
        action="desktop_on",
    )
    assert "Полный доступ сейчас: выключен" in confirmation.text
    assert "<code>/desktop_on_confirm off</code>" in confirmation.text
    assert "station-online" not in confirmation.text
    assert "<description:redacted>" not in confirmation.text

    result = render_server_control_result(
        station,
        replace(ui_server_source, allow_desktop=True),
        action="desktop_on",
    )
    assert "Полный доступ включен: Alpha Station" in result.text
    assert "Текущее состояние: включен" in result.text
    assert "<description:redacted>" not in result.text


def test_server_source_renderer_escapes_explicit_description_view(
    ui_stations: list[Station],
    ui_server_source: ServerSource,
) -> None:
    message = render_server_source(
        ui_stations[0],
        replace(ui_server_source, description="<b>raw & station source</b>"),
    )

    assert "Исходник описания станции Alpha Station" in message.text
    assert "Название: <code>Alpha Station</code>" in message.text
    assert '<pre><code class="language-html">' in message.text
    assert "&lt;b&gt;raw &amp; station source&lt;/b&gt;" in message.text
    assert "<b>raw & station source</b>" not in message.text


def test_server_description_update_renderers_use_revision_commands(
    ui_stations: list[Station],
) -> None:
    station = ui_stations[0]
    preview = render_server_description_preview(
        station,
        description="<b>new & source</b>",
        revision="abc123",
    )
    assert "Новое описание для Alpha Station" in preview.text
    assert '<pre><code class="language-html">' in preview.text
    assert (
        "<code>/server_description_apply abc123 &lt;b&gt;new &amp; source&lt;/b&gt;</code>"
        in preview.text
    )
    assert "station-online" not in preview.text

    result = render_server_description_result(station, revision="def456")
    assert "Описание обновлено: Alpha Station" in result.text
    assert "<code>def456</code>" in result.text


def test_station_management_renderers_are_button_first(
    ui_stations: list[Station],
    ui_server_source: ServerSource,
) -> None:
    many_stations = [
        replace(ui_stations[0], uuid=f"station-{index:02}", name=f"Station {index:02}")
        for index in range(30)
    ]
    picker = render_station_manage_picker(many_stations, page=0, page_size=8)
    assert "Управление станциями · стр. 1/4" in picker.text
    assert "Выберите станцию:" in picker.text
    assert picker.keyboard is not None
    assert picker.keyboard.rows[0][0].text == "Station 00"
    assert picker.keyboard.rows[-1][0].text == "Вперед"
    assert parse_callback_data(picker.keyboard.rows[0][0].callback_data).action == (
        "station_manage_select"
    )
    assert parse_callback_data(picker.keyboard.rows[-1][0].callback_data).action == (
        "station_manage_page"
    )

    panel = render_station_manage_panel(ui_stations[0], ui_server_source)
    assert "Управление станцией" in panel.text
    assert "<b>Alpha Station</b>" in panel.text
    assert "Публикация: опубликована" in panel.text
    assert "Полный доступ: выключен" in panel.text
    assert "Обновления: выключены" in panel.text
    assert panel.keyboard is not None
    assert panel.keyboard.rows[0][0].text == "Скрыть станцию"
    assert parse_callback_data(panel.keyboard.rows[0][0].callback_data).action == (
        "station_publish_prompt"
    )
    assert panel.keyboard.rows[1][0].text == "Включить полный доступ"
    assert panel.keyboard.rows[1][1].text == "Включить обновления"
    assert panel.keyboard.rows[2][0].text == "Игры"
    assert panel.keyboard.rows[3][0].text == "Исходник описания"
    assert panel.keyboard.rows[3][1].text == "Обновить описание"

    request = render_server_description_request(ui_stations[0])
    assert "Пришлите новое HTML-описание" in request.text
    assert request.keyboard is not None
    assert parse_callback_data(request.keyboard.rows[0][0].callback_data).action == (
        "station_description_cancel"
    )


def test_account_menu_keeps_buttons_under_results() -> None:
    empty = render_account_menu()
    with_result = render_account_menu("Баланс минут: скрыто")

    assert empty.text == "Меню аккаунта"
    assert empty.keyboard is not None
    assert [row[0].text for row in empty.keyboard.rows] == [
        "Баланс и выплаты",
        "Статистика использования",
        "Неактивированные промокоды",
    ]
    assert "Баланс минут: скрыто" in with_result.text
    assert with_result.keyboard is not None
    assert parse_callback_data(with_result.keyboard.rows[0][0].callback_data).action == (
        "account_balance"
    )


def test_game_management_renderers_are_command_friendly(
    ui_stations: list[Station],
    ui_products_by_station: dict[str, list[StationProduct]],
) -> None:
    station = ui_stations[0]
    games = render_station_games(station, ui_products_by_station["station-online"])
    assert "Игры станции Alpha Station · стр. 1/1" in games.text
    assert "Выберите игру:" in games.text
    assert "product-a" not in games.text
    assert games.keyboard is not None
    assert games.keyboard.rows[0][0].text == "✅ Cyber Rally"
    assert games.keyboard.rows[1][0].text == "🚫 Space Farm · отключен"
    assert parse_callback_data(games.keyboard.rows[0][0].callback_data).action == "game_select"
    assert parse_callback_data(games.keyboard.rows[0][0].callback_data).product_id == "product-a"

    detail = render_station_game_detail(
        station,
        ServerProductEdit(
            product_id="product-a",
            title="Cyber Rally",
            enabled=True,
            published=True,
            available=True,
            verified=2,
            default_launch=LaunchParameters(
                game_path="C:\\Steam\\Steam.exe",
                work_path="C:\\Steam",
                args="-language russian",
                allowed_paths="",
            ),
            current_launch=LaunchParameters(),
        ),
    )
    assert "Игра на станции Alpha Station" in detail.text
    assert "<b>Cyber Rally</b>" in detail.text
    assert "Технический ID: <code>product-a</code>" in detail.text
    assert "Путь: <code>C:\\Steam\\Steam.exe</code>" in detail.text
    assert "Переопределения: нет" in detail.text
    assert detail.keyboard is not None
    assert detail.keyboard.rows[0][0].text == "Скрыть на станции"
    assert parse_callback_data(detail.keyboard.rows[0][0].callback_data).action == "game_hide"
    assert parse_callback_data(detail.keyboard.rows[0][0].callback_data).product_id == "product-a"
    assert detail.keyboard.rows[1][0].text == "Скрыть на всех станциях"
    assert (
        parse_callback_data(detail.keyboard.rows[1][0].callback_data).action
        == "game_hide_all_prompt"
    )

    result = render_game_enabled_result(
        product_title="Space Farm",
        product_id="product-b",
        enabled=False,
        updated_station_names=["Alpha Station", "Gamma Trial"],
        failed_station_names=["Beta Test Station"],
    )
    assert "Игра скрыта: <b>Space Farm</b>" in result.text
    assert "Обновлено станций: 2" in result.text
    assert "Ошибки: Beta Test Station" in result.text


def test_game_hide_all_confirmation_requires_explicit_confirm(
    ui_stations: list[Station],
) -> None:
    confirmation = render_game_hide_all_confirmation(
        ui_stations[0],
        ServerProductEdit(
            product_id="product-a",
            title="Cyber Rally",
            enabled=True,
            published=True,
            available=True,
            verified=2,
            default_launch=LaunchParameters(),
            current_launch=LaunchParameters(),
        ),
        page=2,
    )

    assert "Скрыть игру на всех станциях?" in confirmation.text
    assert "<b>Cyber Rally</b>" in confirmation.text
    assert confirmation.keyboard is not None
    assert confirmation.keyboard.rows[0][0].text == "Да, скрыть на всех"
    confirm = parse_callback_data(confirmation.keyboard.rows[0][0].callback_data)
    assert confirm.action == "game_hide_all_confirm"
    assert confirm.product_id == "product-a"
    assert confirm.page == 2
    cancel = parse_callback_data(confirmation.keyboard.rows[1][0].callback_data)
    assert cancel.action == "game_select"
    assert cancel.product_id == "product-a"
    assert cancel.page == 2


def test_station_games_renderer_paginates_large_lists(ui_stations: list[Station]) -> None:
    products = [
        StationProduct(
            product_id=f"product-{index}",
            title=f"Game {index:02}",
            enabled=True,
            published=True,
            available=True,
        )
        for index in range(13)
    ]

    first = render_station_games(ui_stations[0], products, page=0, page_size=10)
    second = render_station_games(ui_stations[0], products, page=1, page_size=10)

    assert "стр. 1/2" in first.text
    assert "стр. 2/2" in second.text
    assert first.keyboard is not None
    assert second.keyboard is not None
    assert [row[0].text for row in first.keyboard.rows[:2]] == ["✅ Game 00", "✅ Game 01"]
    assert all("Game 10" not in row[0].text for row in first.keyboard.rows[:10])
    assert [row[0].text for row in second.keyboard.rows[:3]] == [
        "✅ Game 10",
        "✅ Game 11",
        "✅ Game 12",
    ]
    assert first.keyboard.rows[-1][0].text == "Вперед"
    assert second.keyboard.rows[-1][0].text == "Назад"
    for row in first.keyboard.rows:
        for button in row:
            assert len(button.callback_data.encode("utf-8")) <= 64


def test_promocode_renderers_use_monospace_codes() -> None:
    promocodes = [
        Promocode(
            id=14035,
            promocode="27400125",
            created_on_ms=1779132366809,
            expired_on_ms=1781810766809,
            expired=False,
            merchant_id="merchant-1",
            playtime_msecs=3_600_000,
        )
    ]

    issued = render_promocode_issued(
        promocodes,
        requested_minutes=60,
        timezone="Asia/Yekaterinburg",
    )
    unused = render_unused_promocodes(promocodes, timezone="Asia/Yekaterinburg")
    empty = render_unused_promocodes([], timezone="Asia/Yekaterinburg")

    assert "Выпущен промокод на 60 мин" in issued.text
    assert "<code>27400125</code> · 60 мин · до 2026-06-19 00:26" in issued.text
    assert "Неактивированные промокоды:" in unused.text
    assert "<code>27400125</code> · 60 мин · до 2026-06-19 00:26" in unused.text
    assert empty.text == "Неактивированных промокодов нет."


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


def test_sessions_renderer_paginates_five_sessions_per_page(
    ui_profile: ChatProfile,
    ui_sessions: list[Session],
    ui_stations: list[Station],
    ui_now: datetime,
) -> None:
    profile = replace(ui_profile, session_limit=12)
    sessions = [
        replace(
            ui_sessions[0],
            uuid=f"session-page-{index}",
            product_id=f"product-page-{index}",
            created_on_ms=ui_sessions[0].created_on_ms - index * 60_000,
        )
        for index in range(7)
    ]
    catalog = {f"product-page-{index}": f"Game {index}" for index in range(7)}

    first_page = render_sessions(profile, sessions, ui_stations, catalog, now=ui_now)
    second_page = render_sessions(profile, sessions, ui_stations, catalog, now=ui_now, page=1)

    assert "Последние 12 сессий · все станции · стр. 1" in first_page.text
    assert "<b>1. Game 0</b>" in first_page.text
    assert "<b>5. Game 4</b>" in first_page.text
    assert "<b>6. Game 5</b>" not in first_page.text
    assert first_page.keyboard is not None
    assert [button.text for row in first_page.keyboard.rows for button in row] == [
        "Обновить",
        "Вперед",
        "Скрыть короткие",
    ]

    assert "Последние 12 сессий · все станции · стр. 2" in second_page.text
    assert "<b>6. Game 5</b>" in second_page.text
    assert "<b>7. Game 6</b>" in second_page.text
    assert "<b>5. Game 4</b>" not in second_page.text
    assert second_page.keyboard is not None
    assert [button.text for row in second_page.keyboard.rows for button in row] == [
        "Обновить",
        "Назад",
        "Скрыть короткие",
    ]
    assert second_page.keyboard.rows[-1][0].callback_data.endswith("|p=1")


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
