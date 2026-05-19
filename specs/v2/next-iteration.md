# V2 Next Iteration Spec

This document is the source of truth for the next feature cycle after the current V2 bot
foundation. Current production behavior stays governed by the other `specs/v2` files; this
file captures upcoming product and API work before tests/code are added.

## Goals

- Add paginated `/sessions` UX with at most five sessions rendered per page.
- Fixture and model new Drova account, station-product, statistics and server-control
  endpoints from the real API.
- Add station game management flows: read launch parameters, hide/show a game on one
  station, and hide a game on all stations.
- Add account/balance surfaces after real response shapes are captured.
- Keep the same safety policy: no secret leaks, no production write fixtures without
  `TEST_STATION_UUID`, and rollback for every live write check.

## Sessions Pagination

### Product Behavior

- `/sessions` and `/sessions_short` render page 1 by default.
- A page displays at most `5` sessions.
- Inline buttons:
  - `Обновить` refreshes the current page.
  - `Назад` appears when `page > 1`.
  - `Вперед` appears when more sessions exist within the configured session limit.
  - `Скрыть короткие` / `Показать все` preserve the current station selection and reset
    page to 1 when mode changes.
- Header includes page state:
  - `Последние {limit} сессий · {station_or_all} · стр. {page}`
- If a page becomes empty after station/limit changes, render the nearest existing page or
  page 1 with `Сессии не найдены.`

### Data Loading Rule

Drova sessions API has no observed offset/cursor. Every page callback must make a fresh
Drova request, not reuse handler memory or a local cache.

Recommended first implementation:

- Request up to the chat profile `session_limit` on every page.
- Apply selected station/all-stations rules exactly as today.
- Apply short-mode filtering after the response is normalized.
- Slice the filtered ordered list by fixed `page_size = 5`.
- Determine `Вперед` from the filtered list length.

This keeps paging deterministic and avoids inventing local session storage. If `session_limit`
is later too expensive for large users, add a separate API investigation before changing the
contract.

### Public Interfaces

- Extend session callback payloads with compact page fields while staying under Telegram's
  64-byte callback-data limit.
- Keep old `/sessions short` alias as compatibility for `/sessions_short`.
- Service methods still return `RenderedMessage`, not aiogram objects.

### Tests

- Renderer tests for page 1, middle page, last page, empty page and short-mode reset.
- Handler/callback tests for next/previous/refresh/show-all/short payloads.
- Service tests proving each page performs a new Drova request.
- Callback payload length tests for max page values.

## New Drova API Surface

All methods below are planned additions to `DrovaClient`. Exact response DTO fields must be
derived from sanitized live fixtures before implementation.

### Account And Billing

| Method | Path | Auth | Notes |
| --- | --- | --- | --- |
| `GET` | `/accounting/prepaid/prepaid_stats4merchant/{merchant_id}` | Yes | Minute/prepaid balance stats for account. |
| `GET` | `/accounting/prepaid/list4merchant/{merchant_id}` | Yes | Latest payouts/settlements for minutes. |
| `GET` | `/accounting/tinkoff/prepaid/getOpenedDeals` | Yes | Open prepaid payment/deal balance. |

Planned client methods:

```python
async def get_prepaid_stats(merchant_id: str) -> AccountPrepaidStats
async def get_prepaid_settlements(merchant_id: str) -> list[PrepaidSettlement]
async def get_opened_prepaid_deals() -> list[OpenedPrepaidDeal]
```

UX is not finalized. Candidate commands:

- `/account` for minute balance and payable/open deal summary.
- `/payments` for the latest minute payouts.

### Station Product Management

| Method | Path | Auth | Notes |
| --- | --- | --- | --- |
| `GET` | `/server-manager/serverproduct/list4edit2/{server_id}/{product_id}` | Yes | Read station-product launch parameters. Expected to include four launch parameter variants, including default. |
| `POST` | `/server-manager/serverproduct/set_enabled/{server_id}/{product_id}/{true\|false}` | Yes | Hide/show one game on one station. Empty `{}` payload. Treat as write and do not retry automatically. |

Planned client methods:

```python
async def get_server_product_edit(server_id: str, product_id: str) -> ServerProductEdit
async def set_server_product_enabled(server_id: str, product_id: str, enabled: bool) -> None
```

UX requirements:

- Read launch parameters before showing a game-management panel.
- Display the default launch parameter separately from the other three launch variants.
- Product selection starts from the selected station and uses paginated inline buttons
  by human-readable game title, not product-id-first commands.
- Each page shows no more than 10 games; callbacks may carry one product id only and
  must not carry both station id and product id.
- Hide/show a game on one station via inline button and confirmation.
- Hide a game on all stations via a separate confirmation flow.
- "Hide on all stations" must run per-station writes with partial-failure reporting; do not
  pretend the operation is atomic.
- Write operations must reread affected station product state before rendering success.

Open product decisions before implementation:

- Whether "show on all stations" is needed or only "hide on all stations".

### Account Statistics

| Method | Path | Auth | Notes |
| --- | --- | --- | --- |
| `GET` | `/accounting/statistics/myserverusageprepared` | Yes | Backend-prepared usage statistics. |

Planned client method:

```python
async def get_server_usage_statistics() -> ServerUsageStatistics
```

UX:

- `/usage` renders today, week and month total sessions and usage duration.
- Month details show top stations and top games sorted by usage duration.
- Redacted income values are ignored.

### Server Controls

| Method | Path | Auth | Notes |
| --- | --- | --- | --- |
| `POST` | `/server-manager/servers/{server_id}/set_allow_desktop/{true\|false}` | Yes | Toggle full desktop access. Empty `{}` payload. Treat as write and do not retry automatically. |
| `POST` | `/server-manager/servers/{server_id}/set_disable_updates/{true\|false}` | Yes | Toggle updates disabled flag. Empty `{}` payload. Treat as write and do not retry automatically. |
| `GET` | `/server-manager/servers/{server_id}?user_id={merchant_id}` | Yes | Read server source fields including description source and name. |
| `PUT` | `/server-manager/servers/{server_id}` | Yes | Rewrite server description/name. Payload `{description, name}`. Treat as write and do not retry automatically. |

Planned client methods:

```python
async def set_server_allow_desktop(server_id: str, allow_desktop: bool) -> None
async def set_server_disable_updates(server_id: str, disable_updates: bool) -> None
async def get_server_source(server_id: str, merchant_id: str) -> ServerSource
async def update_server_source(server_id: str, *, name: str, description: str) -> None
```

UX requirements:

- Desktop/update toggles require command confirmation and stale-state protection without
  callback payloads carrying station UUIDs.
- Description editing must never show or log raw sensitive description content unless the user
  explicitly requested viewing it in chat.
- `/server_source` is the explicit view command for selected station description source.
- `/server_description <text>` previews an update, and `/server_description_apply <revision> <text>`
  applies it only when the current source revision still matches.

## Fixture Plan

All new fixtures must be collected through `scripts/sample_live_api.py` or a successor sampler.
The sampler reads `.env.specing`; raw responses remain ignored, sanitized fixtures may be
tracked.

Required `.env.specing` keys for this cycle:

- `DROVA_PROXY_TOKEN`: required for all live sampling.
- `TEST_STATION_UUID`: required for station-specific reads and every write fixture.
- `TEST_PRODUCT_UUID`: optional for station product write checks. If absent, live tests may
  choose any product returned by `TEST_STATION_UUID`; if present, it must belong to that
  station or the write check fails closed.

Planned read fixtures:

- `account_prepaid_stats.json`
- `account_prepaid_settlements.json`
- `account_tinkoff_opened_deals.json`
- `test_station_product_edit.json`
- `server_usage_statistics.json`
- `test_station_source.json`

Planned write/rollback fixtures:

- `test_station_product_enabled_toggle.json`
- `test_station_product_enabled_toggle_confirm.json`
- `test_station_product_enabled_rollback.json`
- `test_station_product_enabled_rollback_confirm.json`
- `test_station_allow_desktop_toggle.json`
- `test_station_allow_desktop_toggle_confirm.json`
- `test_station_allow_desktop_rollback.json`
- `test_station_allow_desktop_rollback_confirm.json`
- `test_station_disable_updates_toggle.json`
- `test_station_disable_updates_toggle_confirm.json`
- `test_station_disable_updates_rollback.json`
- `test_station_disable_updates_rollback_confirm.json`
- `test_station_description_update.json`
- `test_station_description_update_confirm.json`
- `test_station_description_rollback.json`
- `test_station_description_rollback_confirm.json`

Do not add a write fixture unless:

- target station is exactly `TEST_STATION_UUID`;
- target product is exactly `TEST_PRODUCT_UUID` when it is configured, otherwise a product
  read from `TEST_STATION_UUID`;
- original state is read and stored in memory before mutation;
- rollback runs in `finally`;
- rollback is verified by a follow-up read;
- sanitized fixture output does not contain raw description, token, IP, email, wallet or
  private account fields.

## Implementation Order

1. Implement `/sessions` pagination using existing session DTOs and fake clients.
2. Expand sampler and opt-in live read tests for account/statistics/product-source endpoints.
3. Add typed DTOs for account billing/statistics after fixture shapes are reviewed.
4. Implement account summary UX.
5. Add station-product read panel and one-station hide/show flow.
6. Add all-stations hide flow with partial-failure reporting.
7. Add server control toggles with stale-state protection.
8. Add server source read/update only after explicit UX approval for editing descriptions in
   Telegram.
