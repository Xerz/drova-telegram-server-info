# Feedback notifications

## Product and UX

`/feedback_notifications` requires a connected chat. Append it to the command list,
preserving all existing command ordering, and include it in `/help`.
The panel contains `Уведомления об отзывах`, `Сейчас: выключены/включены`,
`Новые оценки и комментарии после сессий на всех ваших станциях.`, a notification
example and one keyboard row: `Включить`, `Выключить`. Desired-state callbacks are
idempotent and edit the same message. A suspended subscription explains the required
token update or explicit enable. Off always works without a Drova request.

Examples contain only that account's previously fetched data; before a snapshot is
available use a clearly labelled synthetic demonstration. Never embed pilot account
data in production examples or committed fixtures.

Notification: `Новый отзыв`, station, game, last six client ID characters, local
start/end dates and times, duration, billing/status, score, comment, client usage for
all owned stations and this station over 30 days. Ratings are five positions,
`⭐` filled and `☆` empty (3 = `⭐⭐⭐☆☆`). Missing score: `Оценка не указана`;
missing/whitespace-only comment: `Комментарий не оставлен`. Escape dynamic HTML.
Preserve the complete comment across independently valid messages under 3500 UTF-16
units including markup. Panel examples may use the first part of a long review.

Only finished sessions (`finished_on` present) with integer score 1..5 or a nonblank
comment qualify. Booleans, strings, floats and out-of-range scores normalize to null.
Send only the first observation per chat/account/session; edits or later comments
never produce another event. Freeze the first observed content for delivery retries.

## Polling and statistics

Run inside the bot, independently of game-update notifications, using saved encrypted
chat credentials. One task per enabled chat, at most four concurrent scans. Persist
poll start time: starts for a chat must be at least 60 seconds apart, also after
restart or off/on. No overlapping scans for a chat. A supervisor reconciles tasks
every five seconds; API and delivery failures must not stop other chats or polling.

Each scan uses `GET /session-manager/sessions?merchant_id=<owner>&limit=1000`, never
selected station or `/limit`. No per-station fallback or historical pagination. The
observed API caps results at 1000 even for larger limits. Reject foreign-owner or
duplicate-UUID snapshots without changing baseline. Resolve station/game names through
existing caches, refreshing missing names best-effort without failing feedback detection.

Use one injectable UTC clock for detection and statistics. Sum overlap of each matching
full client ID's sessions with `[now - 30 days, now]`; active sessions end at now,
negative durations contribute zero. Output total hours/minutes, not days. If 1000 rows
end inside the period, prefix both totals with `не менее`. Missing client ID yields
`Статистика клиента недоступна.`; never infer another client from its suffix.

## Persistence and lifecycle

Migration adds subscriptions, seen-session keys and durable delivery parts to bot SQLite.
Defaults are off. First successful scan after each explicit off->on establishes a
silent baseline. Already-on is a no-op. Record seen keys and all pending message parts
atomically. Keep baseline/seen keys, parts, retry times and status across bot restarts.
Downtime while on catches up within the current API window, without reinitialization.

Off cancels pending delivery and invalidates in-flight results. Logout clears all
feedback state. A different account clears state and starts off. Replacing credentials
for the same owner preserves preference, baseline, seen and pending delivery, invalidates
old in-flight scans and resumes an authentication suspension. Token renewal is conditional
on current account, subscription generation and encrypted credential snapshot. A stale
renewal must never overwrite newer credentials or resurrect a logged-out profile.

Serialize settings, sends, logout and account replacement using the shared per-chat
lock. Before accepting a scan or sending a part recheck account and subscription.
Never hold a SQLite transaction over network I/O. Persist each sent part separately;
honor `retry_after`, otherwise back off from 60 seconds to one hour. A failed earlier
part prevents later parts overtaking it. TelegramForbidden suspends polling/delivery
until explicit enable; final Drova authorization/permission errors suspend until valid
same-account token replacement or explicit enable. Transient API errors preserve state
and allow already queued delivery. API token renewal keeps the existing one-retry rule.

Telegram HTML errors use plain-text fallback with link previews disabled. As with existing
digests, a crash between Telegram accepting a part and local commit can duplicate it;
no exactly-once transport promise. One bot instance per database. Gracefully cancel and
await supervisor/chat tasks before closing Telegram/storage. Store only rendered delivery
text and session keys, not raw dumps, full client IDs or IPs. Log safe error codes,
counts and hashed chat IDs. No production dependency on `DROVA_DEV_TOKEN`.

## Acceptance

Follow spec -> synthetic fixtures -> failing tests -> implementation -> passing tests.
Cover score normalization/stars; missing text/score; escaped/long comments; midnight;
30-day overlap, active sessions, suffix collisions and partial coverage; auth/menu and
both desired-state callbacks; silent enable/re-enable; late review on old session;
edit dedup; atomic ingestion/restart/partial retry; 429/block/auth errors; cross-chat
isolation, four-scan concurrency and persisted minute spacing; off/logout/account/token
races; migration of existing populated database; runtime cancellation. Full offline
pytest, ruff and mypy are required. Live checks remain opt-in and read-only. Deployment
is a separate action.
