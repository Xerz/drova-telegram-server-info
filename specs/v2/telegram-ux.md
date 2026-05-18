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

- Header: `Последние {limit} сессий` plus selected station name if set.
- Group by date.
- Per session line group:
  - bold numbered game title;
  - station name when all stations selected;
  - masked/short client id in monospace;
  - separate IP/location line as `IP: {creator_ip} · {city}` when IP is present, omitting city when unknown;
  - start-finish as `HH:MM-HH:MM` and compact duration;
  - billing/status with emoji labels;
  - feedback if present.
- Buttons: `Обновить`, `Скрыть короткие` or `Показать все`.

## Current Dashboard

- Shows all stations sorted by display name.
- Each station line includes index, publication marker (`🌐` published, `🔒` hidden), station state, latest game, latest session city when known, start time and duration.
- Current dashboard must not display raw client IP addresses.
- Empty station sessions render `нет сессий`.
- API failure for one station renders `ошибка загрузки`, not a full command failure.
- Buttons:
  - `Обновить`
  - `Публикация`
  - when publish panel is open: numbered station buttons and `Скрыть панель`

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
