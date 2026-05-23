# Telegram UX Spec

## Message Style

- All user-facing text is Russian.
- Use concise status headers, then data lines.
- Use Telegram HTML only; every dynamic value is escaped.
- If Telegram rejects HTML, send plain text fallback and log `telegram_html_fallback`.
- Do not expose raw token, full IP, email, wallet, stack trace or request URL with credentials.

## Onboarding

`/start` when not connected:

```text
Бот Drova для владельца станций.

Чтобы подключиться, отправьте:
/token <proxy_token>

Токен дает доступ к вашему кабинету. Используйте только своего бота или доверенный инстанс.
```

`/start` when connected:

```text
Бот подключен.
Станций: {station_count}
Выбор: {selected_station_or_all}
Лимит сессий: {limit}
```

## Station Picker

- `/station` opens inline list with one station per row.
- Add first row: `Все станции`.
- Add pagination when stations > 8.
- Button text format:
  - online published: `{name}`
  - unpublished: `{name} · скрыта`
  - not listen/busy/handshake: `{name} · {state}`
- Callback data uses stable factory fields: action, station id or page.

## Sessions

- Header: `Последние {limit} сессий · {station_or_all} · стр. {page}`.
- Render at most five sessions per page.
- Drova sessions API has no offset/cursor; every page callback must make a fresh request.
- If requested page is out of range after filtering, render the nearest existing page.
- Group by date.
- Per session line group:
  - bold numbered game title;
  - station name when all stations selected;
  - masked/short client id in monospace;
  - separate IP/location line as `IP: {creator_ip} · {city}` when IP is present, omitting city when unknown;
  - start-finish as `HH:MM-HH:MM` and compact duration;
  - billing/status with emoji labels;
  - feedback if present.
- Buttons: `Обновить`, optional `Назад`/`Вперед`, `Скрыть короткие` or `Показать все`,
  plus `Все станции` and `Выбрать станцию`. Station selection opens a paginated picker,
  persists the choice and returns directly to refreshed sessions while preserving full/short
  mode.

## Current Dashboard

- Shows all stations sorted by display name.
- Each station line includes index, publication marker (`🌐` published, `🔒` hidden), station state, latest game, latest session city when known, start time and duration.
- Current dashboard must not display raw client IP addresses.
- Empty station sessions render `нет сессий`.
- API failure for one station renders `ошибка загрузки`, not a full command failure.
- Buttons:
  - `Обновить`
  - `Управление станциями`

## Account

- `/account` shows account billing data from prepaid/accounting endpoints.
- Include prepaid minute stats: available-to-sell minutes, sold minutes, used minutes, and
  minute balance when Drova returns it.
- Include up to five opened payment deals with created date, gross amount and payout amount.
- Include up to five latest prepaid minute settlements with date, minutes and source
  (`заказ` / `без заказа`).
- Redacted or unavailable monetary values render as `скрыто`.

## Usage Statistics

- `/usage` shows backend-prepared usage statistics.
- The summary includes today, week and month total sessions and total usage duration.
- Month details include top stations and top games sorted by usage duration.
- Product ids and station ids are shown only when a cached title/name is unavailable.
- Redacted income values are not shown.

## Promocodes

- `/promocode <minutes>` issues one prepaid promocode for a positive integer number of minutes.
- `/promocodes` lists prepaid promocodes that are not activated yet.
- Promocode values are always rendered as `<code>...</code>` for tap-to-copy.
- Promocode output includes playtime minutes and expiry date/time when available.
- Invalid minutes render a user-safe validation error and do not call Drova.

## Game Management

- Game management uses `/games` as the primary human-facing command.
- `/games` requires one selected station and lists station games sorted by title.
- The list is paginated, with no more than 10 games per page, because stations may
  have hundreds of games.
- Each listed game button shows enabled/problem marker and title. The list message
  does not print product ids.
- Selecting a game opens launch parameters for the selected station and shows
  default and override values.
- The selected-game panel has buttons to hide/show the game on the selected station,
  hide the game on all stations, and return to the paginated list.
- Hide/show on the selected station updates the same selected-game panel in place:
  the status line and primary button change, and the short success text is shown as
  a Telegram toast instead of replacing the panel with a separate result message.
- Hide on all stations is dangerous enough to require an explicit confirmation panel;
  only the confirmation action performs writes and may replace the panel with a
  summary message.
- Game callbacks may carry one product id only; station id comes from the chat's
  selected station, and callbacks never carry tokens.
- `/game <product_id>`, `/game_hide <product_id>`, `/game_show <product_id>`,
  and `/game_hide_all <product_id>` are accepted only as technical compatibility
  aliases, not as primary UX.
- If all-stations mode is selected, station-scoped game flows ask the user to choose
  one station first.

## Server Controls

- `/station_manage` is the primary station-management UX.
- It opens a paginated station picker, without an all-stations option, because station
  operations target one station.
- Selecting a station persists it as the chat's selected station and opens a station
  panel with publication, desktop, updates, games and description actions.
- Station picker and game picker both paginate; callbacks may carry a station id or
  product id, but never both in one payload.
- Publication requires inline confirmation and stale-state protection.
- Desktop/update buttons are inline writes with stale-state protection; success returns
  the refreshed station panel and a short callback toast.
- The station panel shows latest session status using `get_sessions(server_id, limit=1)`.
- The `Games` button opens the selected station's game picker. Game list and game detail
  messages include a button back to the station management panel.
- The `Description` button shows the current escaped HTML description source and puts
  the chat into a 30-minute in-memory waiting state. The next non-command message is
  treated as HTML description draft, previewed with `Apply` and `Cancel` buttons, and
  applied only if the stored source revision is still current.
- Source and description previews display escaped HTML source in
  `<pre><code class="language-html">...</code></pre>` blocks.
- `/desktop_*`, `/updates_*`, `/server_source`, `/server_description ...` and
  `/server_description_apply ...` remain direct compatibility commands.

## Account Menu

- `/account_menu` opens account buttons for balance/payments, usage statistics and unused
  promocodes.
- Account-menu results keep the same account buttons under the result message, without a
  separate back button.
- `/account`, `/usage` and `/promocodes` remain direct compatibility commands.

## Legacy Server Controls

- Server desktop/update controls use command confirmation, not inline callbacks.
- Commands require one selected station:
  - `/desktop_on`
  - `/desktop_off`
  - `/updates_on`
  - `/updates_off`
- The first command reads current server source state and responds with a confirmation command
  that includes only expected `on`/`off` state, never station UUID or source description.
- Confirm commands reread current server source state. If the state differs from expected,
  the write is cancelled as stale.
- Confirmation output must not include raw server description.
- `/server_source` explicitly shows the selected station name and description source.
- Server source output uses Telegram HTML escaping and may truncate long descriptions.
- `/server_description <text>` previews a new description and returns an apply command with
  a short non-reversible source revision hash.
- `/server_description_apply <revision> <text>` rereads server source, rejects stale revision,
  then updates description while preserving the current server name.

## Publish Confirmation

Flow:

1. User taps station number in publish panel.
2. Bot edits or sends confirmation:
   `Изменить публикацию станции "{station_name}" на "{new_state}"?`
3. Buttons: `Подтвердить`, `Отмена`.
4. Confirm calls `set_published`, rereads stations, renders dashboard.

Callback must include expected old state. If actual state changed before confirm, bot cancels and asks user to refresh.

## Disabled Products

- Group by station.
- Empty state: `Проблемных продуктов нет.`
- For each product render title and flags:
  - `отключен`
  - `не опубликован`
  - `недоступен`

## Stations And Endpoints

- `/stations` replaces legacy `/stationsInfo`.
- Group by station with city and state.
- Split endpoints:
  - `Внешние`
  - `Внутренние`
- Render `ip:base_port`, city/provider if available.

## Export UX

- Export commands immediately answer `Готовлю файл...`.
- On success send document with deterministic filename.
- On expected large/export failure send user-safe failure and correlation id.
- Exports should be cancellable later, but V2 initial implementation may only show progress and final result.

## Unknown Input

- Unknown command: `Команда не найдена. Используйте /help.`
- Non-command text: `Я понимаю только команды. Используйте /help.`
