"""Pure Russian panels and bounded hourly digests."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from drova_bot.game_updates.models import (
    EXPERIMENTAL_PROVIDERS,
    LABELS,
    GameFeed,
    SteamEvent,
    Subscription,
)
from drova_bot.telegram.callbacks import CallbackSpec
from drova_bot.telegram.keyboards import ButtonSpec, KeyboardSpec
from drova_bot.telegram.renderers import RenderedMessage

MODES = {
    "off": "Выключено",
    "selected": "Выбранные игры",
    "all": "Все Steam-игры",
    "all_supported": "Все поддерживаемые игры",
}


def _zone(timezone: str) -> ZoneInfo:
    try:
        return ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("Asia/Yekaterinburg")


def digest_groups(events: list[SteamEvent], timezone: str) -> list[tuple[str, set[str]]]:
    """Return each message with its AppIDs, so delivery can commit individual parts."""
    if not events:
        return []
    zone = _zone(timezone)
    start, end = min(e.observed_at for e in events), max(e.observed_at for e in events)
    heading = (
        "Обновления игр в Steam"
        if all(e.provider == "steam" for e in events)
        else "Обновления игр и лаунчеров"
    )
    header = f"<b>{heading}</b>\nОбнаружены: {start.astimezone(zone):%Y-%m-%d %H:%M}–"
    header += (
        f"{end.astimezone(zone):%H:%M}"
        if start.astimezone(zone).date() == end.astimezone(zone).date()
        else f"{end.astimezone(zone):%Y-%m-%d %H:%M}"
    ) + "\n\n"
    grouped: dict[str, list[SteamEvent]] = defaultdict(list)
    for event in events:
        grouped[event.id].append(event)
    ordered = sorted(grouped.items(), key=lambda item: (item[1][-1].title.casefold(), item[0]))
    parts: list[tuple[str, set[str]]] = []
    text = header
    appids: set[str] = set()
    for appid, updates in ordered:
        latest = max(updates, key=lambda e: (e.observed_at, e.seq))
        title = latest.title[:160] + ("…" if len(latest.title) > 160 else "")
        line = (
            f'• <a href="{escape(latest.news_url, quote=True)}">{escape(title)}</a>'
            f" — {latest.observed_at.astimezone(zone):%H:%M}"
        )
        if latest.provider != "steam":
            kind = {"game": "Игра", "resources": "Ресурсы", "launcher": "Лаунчер"}[latest.kind]
            if latest.provider in {"wargaming", "lesta"} and latest.kind == "game":
                kind = "Дистрибутив"
            line += (
                f" · {LABELS[latest.provider]} · {kind}"
                f" · {escape(latest.version or 'версия недоступна')}"
            )
        if latest.provider in EXPERIMENTAL_PROVIDERS:
            line += " · экспериментально"
        if len(updates) > 1:
            line += f" · обновлений: {len(updates)}"
        if len((text + line + "\n").encode("utf-16-le")) // 2 > 3900 and appids:
            parts.append((text.rstrip(), appids))
            text, appids = header, set()
        text += line + "\n"
        appids.add(appid)
    parts.append((text.rstrip(), appids))
    return parts


def render_digest(events: list[SteamEvent], timezone: str) -> list[str]:
    return [text for text, _ in digest_groups(events, timezone)]


def render_panel(
    feed: GameFeed,
    subscription: Subscription,
    *,
    page: int,
    fetched_at: float | None,
    now: datetime,
    timezone: str,
) -> RenderedMessage:
    query = subscription.search.casefold()
    games = sorted(
        [g for g in feed.games if query in g.title.casefold()],
        key=lambda g: (g.title.casefold(), g.id),
    )
    pages = max(1, (len(games) + 9) // 10)
    page = min(max(0, page), pages - 1)
    lines = [
        "<b>Обновления игр и лаунчеров</b>",
        f"Режим: {MODES[subscription.mode]}",
        "Часовая сводка · игры и связанные лаунчеры",
        f"Выбрано игр: {len(subscription.selected)}",
    ]
    if subscription.suspended:
        lines.append("Рассылка приостановлена. Выберите режим, чтобы возобновить.")
    if subscription.mode == "off":
        lines.append("Отметьте игры и включите «Выбранные игры» или подпишитесь на все.")
    covered = sum(
        g.buildid is not None and g.error_code is None for g in feed.games if g.provider == "steam"
    )
    lines.append(f"Данные Steam: {covered} из {sum(g.provider == 'steam' for g in feed.games)} игр")
    for name, status in sorted(feed.providers.items()):
        stale = status.checked_at is None or (now - status.checked_at).total_seconds() > 900
        lines.append(
            f"{LABELS.get(name, name)}: {status.covered}/{status.total}"
            f" · без соответствия: {status.unmapped}"
            + (" · данные устарели" if stale else "")
            + (" · есть ошибки" if status.error_code else "")
        )
    if feed.catalog_updated_at:
        lines.append(
            f"Каталог: {feed.catalog_updated_at.astimezone(_zone(timezone)):%Y-%m-%d %H:%M}"
        )
    if feed.checked_at:
        lines.append(
            f"Последний обход: {feed.checked_at.astimezone(_zone(timezone)):%Y-%m-%d %H:%M}"
        )
    if (
        fetched_at is None
        or now.timestamp() - fetched_at > 180
        or feed.checked_at is None
        or (now - feed.checked_at).total_seconds() > 900
    ):
        lines.append("Данные обновлений пока недоступны или устарели.")
    if subscription.search:
        lines.append(f"Поиск: {escape(subscription.search)}")
    lines.extend(["Поиск: /game_updates название", f"Страница {page + 1}/{pages}"])
    if not games:
        lines.append("Игры не найдены.")
    rows = [
        [
            ButtonSpec(
                ("✓ " if subscription.mode == mode else "") + label,
                CallbackSpec(action="game_updates_mode", control=mode).pack(),
            )
        ]
        for mode, label in MODES.items()
    ]
    for game in games[page * 10 : (page + 1) * 10]:
        selected = game.id in subscription.selected
        label = ("✓ " if selected else "＋ ") + game.title[:60]
        label += f" · {LABELS[game.provider]}"
        if game.provider in EXPERIMENTAL_PROVIDERS:
            label += " · экспериментально"
        if game.coverage == "resources_only":
            label += " · только ресурсы"
            lines.append(f"{escape(game.title)}: Отслеживаются только ресурсы")
        elif game.coverage == "launcher_only":
            label += " · только BSG Launcher"
            lines.append(f"{escape(game.title)}: Отслеживается только BSG Launcher")
        elif game.buildid is None or game.error_code:
            label += " · нет данных"
        rows.append(
            [
                ButtonSpec(
                    label,
                    CallbackSpec(
                        action="game_updates_remove" if selected else "game_updates_add",
                        product_id=str(game.id),
                        page=page,
                    ).pack(),
                )
            ]
        )
    navigation = []
    if page:
        navigation.append(
            ButtonSpec("Назад", CallbackSpec(action="game_updates_page", page=page - 1).pack())
        )
    if page + 1 < pages:
        navigation.append(
            ButtonSpec("Вперёд", CallbackSpec(action="game_updates_page", page=page + 1).pack())
        )
    if navigation:
        rows.append(navigation)
    rows.extend(
        [
            [ButtonSpec("Обновить", CallbackSpec(action="game_updates_page", page=page).pack())],
            [ButtonSpec("Меню аккаунта", CallbackSpec(action="account_menu").pack())],
        ]
    )
    return RenderedMessage("\n".join(lines), KeyboardSpec(rows))
