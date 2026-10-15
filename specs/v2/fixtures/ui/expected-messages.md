# Expected Renderer Snapshots

These snapshots are intentionally high level. Exact punctuation may evolve, but tests must assert the same information hierarchy and safety rules.

## `/sessions`

```text
Последние 5 сессий · все станции

2026-05-18
1. Space Farm
Gamma Trial
client ...abcdef
IP: 198.51.100.30 · Testburg · Test Network
🧪 trial 🟢 active
16:40-🟢 now (20 мин)

2. Cyber Rally
Alpha Station
client ...222222
IP: 203.0.113.20 · Example City · Example Network
💳 prepaid ✅ finished
16:00-16:10 (10 мин)
Отзыв: ok

2026-05-17
3. Desktop Mode
Alpha Station
client ...111111
IP: 203.0.113.10 · Example City · Example Network
🔁 subscription ✅ finished
16:00-16:02 (2 мин)
```

## `/current`

```text
1. Alpha Station · Cyber Rally · Example City · Example Network · 16:00 · 10 мин
2. Beta Test Station · скрыта · UNVERIFIED · нет сессий
3. Gamma Trial · Trial · Space Farm · Testburg · Test Network · active · 20 мин
```

## `/disabled`

```text
Alpha Station
Space Farm: отключен

Beta Test Station
Desktop Mode: не опубликован

Gamma Trial
Space Farm: недоступен
```

## `/stations`

```text
Alpha Station
City A
Внешние:
203.0.113.11:48000
Внутренние:
192.168.1.10:48000

Beta Test Station · скрыта · UNVERIFIED
Endpoints не найдены.

Gamma Trial · Trial
City G
Внешние:
198.51.100.45:48100
```

## `/feedback_notifications`

Synthetic intent from `feedback.json`: the panel starts off, contains a clearly marked
demo before an account snapshot is available, and has one row `Включить | Выключить`.
The same-account review example and standalone notification contain:

```text
Новый отзыв

Станция <А>
Desktop · клиент …123456
13.10 21:50 → 14.10 00:37
2 ч 47 мин · подписка · завершена

⭐⭐⭐☆☆

Комментарий:
Всё хорошо <спасибо> & удачи.

Этот клиент за последние 30 дней
Все ваши станции: 28 ч 47 мин
Эта станция: 2 ч 47 мин
```

Dynamic HTML characters are escaped in Telegram HTML. Missing comment is
`Комментарий не оставлен`; missing score is `Оценка не указана`. A truncated
30-day window prefixes both totals with `не менее`. A finished `ABORTED` session
shows `прервана`. Long comments continue in separately valid messages without loss.
