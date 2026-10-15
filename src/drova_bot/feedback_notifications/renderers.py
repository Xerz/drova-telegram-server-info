"""Pure bounded HTML notifications and same-account example panels."""

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from html import escape

from drova_bot.domain.formatters import datetime_from_ms, format_session_duration
from drova_bot.domain.models import Session
from drova_bot.feedback_notifications.models import ClientUsage, FeedbackSettings
from drova_bot.telegram.callbacks import CallbackSpec
from drova_bot.telegram.keyboards import ButtonSpec, KeyboardSpec
from drova_bot.telegram.renderers import RenderedMessage

MESSAGE_LIMIT = 3500


def rating_stars(score: int | None) -> str:
    if type(score) is not int or not 1 <= score <= 5:
        return "Оценка не указана"
    return "⭐" * score + "☆" * (5 - score)


def client_usage(
    session: Session, sessions: Sequence[Session], *, now: datetime
) -> ClientUsage | None:
    if not session.client_id:
        return None
    end = int(now.timestamp() * 1000)
    start = int((now - timedelta(days=30)).timestamp() * 1000)
    total = station_total = 0
    for item in sessions:
        if item.client_id != session.client_id:
            continue
        finish = item.finished_on_ms if item.finished_on_ms is not None else end
        duration = max(0, min(finish, end) - max(item.created_on_ms, start))
        total += duration
        if item.server_id == session.server_id:
            station_total += duration
    incomplete = len(sessions) >= 1000 and min(s.created_on_ms for s in sessions) > start
    return ClientUsage(total // 1000, station_total // 1000, incomplete)


def _hours(seconds: int) -> str:
    return f"{seconds // 3600} ч {seconds // 60 % 60:02} мин"


def _units(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def render_notification(
    session: Session,
    sessions: Sequence[Session],
    station_names: Mapping[str, str],
    product_titles: Mapping[str, str],
    *,
    now: datetime,
    timezone: str,
) -> list[str]:
    start = datetime_from_ms(session.created_on_ms, timezone)
    finish_ms = (
        session.finished_on_ms
        if session.finished_on_ms is not None
        else int(now.timestamp() * 1000)
    )
    finish = datetime_from_ms(finish_ms, timezone)
    station = escape(station_names.get(session.server_id, "Станция неизвестна")[:160])
    game = escape(product_titles.get(session.product_id, "Неизвестная игра")[:160])
    client = f"…{session.client_id[-6:]}" if session.client_id else "неизвестен"
    billing = {"subscription": "подписка", "prepaid": "предоплата", "trial": "пробная"}
    status = {"FINISHED": "завершена", "ABORTED": "прервана"}.get(
        (session.status or "FINISHED").upper(), session.status or "завершена"
    )
    duration = format_session_duration(max(0, (finish_ms - session.created_on_ms) // 1000))
    prefix = (
        f"<b>Новый отзыв</b>\n\n<b>{station}</b>\n{game} · клиент <code>{escape(client)}</code>\n"
        f"{start:%d.%m %H:%M} → {finish:%d.%m %H:%M}\n"
        f"{duration} · {escape(billing.get(session.billing_type or '', 'тип оплаты неизвестен'))}"
        f" · {escape(status[:80])}\n\n{rating_stars(session.score)}\n\nКомментарий:\n"
    )
    usage = client_usage(session, sessions, now=now)
    if usage is None:
        suffix = "\n\nСтатистика клиента недоступна."
    else:
        qualifier = "не менее " if usage.incomplete else ""
        suffix = (
            "\n\n<b>Этот клиент за последние 30 дней</b>\n"
            f"Все ваши станции: {qualifier}{_hours(usage.total_seconds)}\n"
            f"Эта станция: {qualifier}{_hours(usage.station_seconds)}"
        )
    comment = (
        session.score_text
        if session.score_text and session.score_text.strip()
        else "Комментарий не оставлен"
    )
    continuation = "<b>Отзыв · продолжение</b>\n"
    parts: list[str] = []
    chunk = ""
    budget = MESSAGE_LIMIT - _units(prefix + suffix)
    used = 0
    for char in comment:
        encoded = escape(char)
        length = _units(encoded)
        if used + length > budget:
            parts.append(prefix + chunk + suffix if not parts else continuation + chunk)
            chunk, used = "", 0
            budget = MESSAGE_LIMIT - _units(continuation)
        chunk += encoded
        used += length
    parts.append(prefix + chunk + suffix if not parts else continuation + chunk)
    return parts


def render_panel(settings: FeedbackSettings) -> RenderedMessage:
    state = "включены" if settings.enabled else "выключены"
    if settings.suspended:
        state = "приостановлены"
    lines = [
        "<b>Уведомления об отзывах</b>",
        f"Сейчас: {state}",
        "",
        "Новые оценки и комментарии после сессий на всех ваших станциях.",
    ]
    if settings.suspended:
        lines += [
            "Обновите токен через /token или нажмите «Включить»."
            if settings.suspended == "auth"
            else "Разблокируйте бота и нажмите «Включить»."
        ]
    if settings.example_text:
        lines += ["", "<b>Пример уведомления</b>", "", settings.example_text]
    else:
        demo = Session(
            uuid="demo",
            server_id="demo",
            merchant_id="demo",
            product_id="demo",
            client_id="demo-123456",
            creator_ip=None,
            created_on_ms=1767294000000,
            finished_on_ms=1767297600000,
            billing_type="subscription",
            score=3,
            score_text="Спасибо за игру!",
        )
        example = render_notification(
            demo,
            [demo],
            {"demo": "Станция 1"},
            {"demo": "Игра"},
            now=datetime(2026, 1, 1, 21, tzinfo=UTC),
            timezone="Asia/Yekaterinburg",
        )[0]
        lines += ["", "<b>Демонстрационный пример · вымышленные данные</b>", "", example]
    return RenderedMessage(
        "\n".join(lines),
        KeyboardSpec(
            [
                [
                    ButtonSpec(
                        "Включить",
                        CallbackSpec(action="feedback_notifications_mode", control="on").pack(),
                    ),
                    ButtonSpec(
                        "Выключить",
                        CallbackSpec(action="feedback_notifications_mode", control="off").pack(),
                    ),
                ]
            ]
        ),
    )
