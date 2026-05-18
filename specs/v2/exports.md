# Exports Spec

## Commands

- `/export_sessions`
- `/export_sessions_csv`
- `/export_products`
- `/export_product_time`
- Backward-compatible aliases map to these commands: `/export sessions`, `/export products`,
  `/export product-time`, `/dumpall`, `/dumpOnefile`, `/dumpStationsProducts`,
  `/dumpStationsProductsWithTime`, `/dumpStationsProductsMonth`.

## Execution

- Export generation runs outside the Telegram update handler.
- Handler sends progress message before work starts.
- Export service has a configurable timeout and row limit.
- On completion, bot sends document and edits progress message to success.
- On failure, bot edits progress message with a user-safe error.

## Session Export

Formats:

- CSV per station for `/export_sessions_csv` and legacy `/dumpall`.
- Single XLSX for `/export_sessions`, legacy `/export sessions` and `/dumpOnefile`.

Columns:

```text
station_name, game_name, creator_ip, city, range_km, asn, date,
duration, start_time, finish_time, billing_type, status, abort_comment,
client_id, uuid, server_id, merchant_id, product_id, created_on,
finished_on, score, score_reason, score_text, parent, sched_hints
```

V2 changes from legacy:

- Do not mutate source session when `finished_on` is missing.
- Use deterministic filenames without raw user id: `drova-sessions-{YYYYMMDD-HHMMSS}.xlsx`.
- CSV station filenames sanitize station names.
- Include station name as a column even in one-file mode.

## Product State Export

- Rows are product titles sorted ascending.
- Columns are station names sorted ascending.
- Cell states:
  - `Active`;
  - `отключен`;
  - `не опубликован`;
  - `недоступен`;
  - combined flags joined by `, `.
- Problem cells are highlighted yellow.

## Product Time Export

- Periods:
  - all available sessions;
  - last 30 days;
  - future extension: custom period.
- Duration cells use `[h]:mm:ss`.
- Last column is `Всего`.
- Total formulas must cover only station columns.

## Testable Output

- Tests assert workbook sheet names, headers, formulas and representative cell values.
- Tests do not assert generated timestamp except through injectable clock.
