# Exports Current Spec

## Session Exports

Commands:

- `/dumpall` sends one CSV file per station.
- `/dumpOnefile` sends one XLSX file containing all station sessions.

Data source:

- Load stations with `/server-manager/servers`.
- For each station, load `/session-manager/sessions` with `server_id`.
- The current code does not pass an explicit limit in export requests.

Columns:

```text
Game name, creator_ip, City, RangeKm, ASN, Date, Duration, Start time,
Finish time, billing_type, status, abort_comment, client_id, id, uuid,
server_id, merchant_id, product_id, created_on, finished_on, score,
score_reason, score_text, parent, sched_hints
```

Rules:

- `Game name` comes from `products_data[product_id]`, fallback `Unknown game`.
- `City` and `ASN` come from GeoLite.
- `RangeKm` is station-to-client distance; missing data returns `-1`.
- `Date`, `Start time`, `Finish time` are derived from millisecond timestamps.
- If `finished_on` is missing, export mutates the in-memory row to current time before writing.
- CSV export silently skips a station if writing that station CSV raises.
- XLSX export auto-sizes columns and writes `data{user_id}.xlsx`.

## Station Products Exports

Commands:

- `/dumpStationsProducts` writes product state matrix.
- `/dumpStationsProductsWithTime` writes product time matrix across all available sessions.
- `/dumpStationsProductsMonth` writes product time matrix for last 30 days.

Data source:

- Load stations and store station names.
- Load station products with `/server-manager/serverproduct/list4edit2/{server_id}`.
- Time variants additionally load sessions per station.

Rows and columns:

- Rows are sorted product titles.
- Columns are sorted station names from `persistentData["stationNames"][chat_id]`.
- Final column `Всего` is added for time variants and contains a SUM formula.

Cell values:

- Non-time export writes `Active` or concatenated product state errors.
- Time export writes total duration for that product/station using `[h]:mm:ss` number format.
- Disabled/unpublished/unavailable cells are filled yellow.

Filename rules:

- Base: `productStates{user_id}.xlsx`.
- With all-time durations: `productStatesWithTime{user_id}.xlsx`.
- With day limit: `productStatesDays{days_limit}_{user_id}.xlsx`.

## Current Export Gaps

- Export endpoints can be heavy because no explicit limit is passed.
- File names include raw station names or user id in current production behavior.
- XLSX generation is synchronous and can block bot update processing.
- There are no automated tests around column order, formulas, or date/time conversion.
