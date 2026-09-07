# Steam game update notifications

## Product and UX

- `/game_updates [search]` and the account-menu button `Обновления игр` require a
  connected Drova profile. Subscriptions belong to the chat, independent of stations.
- Modes: `off` (default), `selected`, `all`. Selected AppIDs survive mode changes.
  Explicit mode changes start a new subscription period; identical callbacks are idempotent.
  Selecting an additional game starts its own activation time. Selecting games does not
  silently enable notifications; the panel explains how to enable selected mode.
- Search is case-insensitive by title, limited to 100 characters, persisted per chat.
  Pages have 10 games. Callbacks encode desired state, AppID and page, never search text.
  Page callbacks use the current saved search; clamp obsolete pages to the nearest page.
- `all` includes future catalog entries. Group duplicate Drova products by Steam AppID;
  use the first title sorted by casefolded title and product ID. Accept only products with
  `requiredAccount=Steam` and an HTTP(S) `store.steampowered.com/app/<positive id>` URL.
- Hourly digests at UTC hour boundaries display chat-local detection times, titles and
  `https://store.steampowered.com/news/app/<appid>` links. No empty messages or patch-note
  fetching. Multiple changes per game produce one line with latest time and count.
- Only observations strictly after subscription activation qualify. At an hour boundary,
  include observations strictly before that boundary. After downtime combine overdue
  pending observations into one digest for their actual period; split on game boundaries
  with a conservative 3900 UTF-16-unit budget (including escaped markup).
- Switching mode discards pending notifications from the old subscription period.
  Removing a selected game cancels its pending notifications; retains other eligible games.
  `/logout` removes notification settings, pending events and digest jobs for that chat.
- Blocked chats are suspended; explicitly selecting a non-off mode resumes a new period.
- `/updates_on` and `/updates_off` retain their existing station-control meaning.

## Watcher

- Separate `steam-watcher` process, SQLite database with Alembic migrations, volume,
  settings and internal aiohttp API. No Telegram token or private Drova token is required.
- Refresh the public Drova catalog on startup and every hour. Preserve previous catalog
  after errors/invalid or unexpectedly empty responses. Removed apps become inactive;
  reintroduced apps establish a fresh baseline to avoid reporting the unmonitored gap.
- Observe unique active AppIDs every 300 seconds, without overlapping cycles. Use one
  managed async SteamCMD PTY session, anonymous login, refreshed app-info cache and VDF
  parsing of `depots.branches.public.buildid`. No app_update, downloads, Steam accounts,
  beta branches, installed-version comparison or station writes.
- Store successful observations and per-app error codes. First read is a silent baseline;
  every later unequal buildid, including rollbacks, atomically updates state and appends
  a journal event. Missing/malformed/truncated output and timeouts never alter the baseline.
  A lost Steam session aborts the remaining scan instead of reconnecting for every AppID;
  failed cycles back off up to 30 minutes. A missing public branch keeps a healthy session.
- Bound command time and output size, restart failed processes, retry with backoff, and
  shut down the complete child process group. Cold-cache `requesting` output triggers
  bounded repeat reads; never interpret it as a successful observation.

## Internal API v1

- All endpoints require `Authorization: Bearer <STEAM_WATCHER_TOKEN>`; constant-time
  comparison. No public Compose port or shared database mount. Bot HTTP bypasses proxies.
- `GET /health`: process/loop responsiveness and catalog/check timestamps and coverage.
  Upstream failures are degraded coverage, not a reason to kill an otherwise live API.
- `GET /v1/games`: `{games, catalog_updated_at, checked_at}`; each game has `appid`,
  `title`, optional `buildid`, `last_success_at`, `error_code`.
- `GET /v1/events?cursor=<stream_uuid>:<sequence>&limit=500`: `{events,next_cursor,has_more}`.
  An omitted cursor starts at zero. Limits are 1..500. Events contain `stream_id`, `seq`,
  `appid`, `title`, `branch=public`, `previous_buildid`, `buildid`, `observed_at` (UTC).
  Sequence is monotonic, and repeated builds remain distinct events. Invalid cursor/limit:
  400; foreign stream or future sequence: 409 with a fresh zero cursor. Journal has no
  automatic retention in v1. Bot records reset diagnostics and consumes the new journal.

## Bot persistence and reliability

- Persist the game snapshot, source cursor, accepted events, settings, eligible pending
  notifications and immutable digest parts in the bot database. Import a page and advance
  its cursor in one transaction; deduplicate by `(stream_id,seq)`. Fan-out only on first import.
- Poll every 60 seconds. Drain pages before building an hourly digest; upstream failure
  still allows delivery of already accepted events. Record snapshot freshness separately
  from last successful API contact; expose both upstream coverage and stale feed status.
- Serialize settings/logout/send for a chat. Before each part verify connected profile,
  active mode and suspension. Selection changes invalidate unsent jobs and rebuild only
  still-eligible events; sent parts are never rebuilt.
- Persist retries and sent state per part. Honor Telegram retry_after, use bounded
  exponential backoff for other delivery failures, and suspend on TelegramForbiddenError.
  HTML parse failures get escaped-free plain-text fallback with working URLs. A crash after
  Telegram accepts a message but before local commit can cause a duplicate; no exactly-once
  promise. Process one bot and one watcher instance per database.
- The runtime flag GAME_UPDATES_ENABLED defaults false. Starting the existing bot without
  a watcher remains supported; feature failures do not stop Telegram polling.

## Acceptance and operations

Follow `spec -> fixtures -> failing tests -> code -> passing tests`. Offline tests cover
catalog mapping, VDF framing and parsing, SteamCMD recovery, baseline/change/rollback,
API auth/cursors/reset, migrations/restart/atomicity, subscription commands and callbacks,
hour boundaries/timezones/grouping/splitting, partial sends/retries/block/logout and runtime
cleanup. Live Steam tests are explicitly opt-in and skip by default; use public metadata
only. A manual catalog probe reports coverage and cycle duration before enabling delivery.
Do not commit raw Steam output. Log only safe error codes, counts, durations and hashed
chat IDs. Docker and CI build a separate linux/amd64 watcher image without publishing its API.

SteamCMD contract reference: https://partner.steamgames.com/doc/sdk/uploading
