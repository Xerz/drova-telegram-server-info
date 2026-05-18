# Domain Model Spec

## Core Types

```text
Account
  uuid: str
  name: str | None
  roles: list[str]

ChatProfile
  telegram_chat_id: int
  drova_user_id: str | None
  encrypted_proxy_token: bytes | None
  selected_station_id: str | None
  session_limit: int
  timezone: str

Station
  uuid: str
  name: str
  state: StationState
  published: bool
  verified: str | None
  city_name: str | None
  groups_list: list[str]
  latitude: float | None
  longitude: float | None

Session
  uuid: str
  server_id: str
  merchant_id: str
  product_id: str
  client_id: str | None
  creator_ip: str | None
  created_on_ms: int
  finished_on_ms: int | None
  billing_type: str | None
  status: str | None
  score_text: str | None

StationProduct
  product_id: str
  title: str
  enabled: bool
  published: bool
  available: bool

Endpoint
  uuid: str
  server_id: str
  ip: str
  base_port: int
  externally_routable: bool | None

Promocode
  id: int
  promocode: str
  created_on_ms: int
  expired_on_ms: int
  expired: bool
  merchant_id: str
  playtime_msecs: int
```

## Station State Presentation

- Online states: `LISTEN`, `HANDSHAKE`, `BUSY`.
- Offline or unavailable state: any other value.
- Display markers:
  - unpublished: `скрыта`;
  - offline/unverified: show state text;
  - active latest session: highlight through text marker, not only HTML style.

## Session Rules

- Duration uses `finished_on_ms - created_on_ms` when finished exists.
- Active duration uses injectable clock, never direct `datetime.now()` inside renderer.
- Short mode includes only duration strictly greater than 5 minutes.
- Sessions are rendered newest first unless Drova API proves a different stable order; tests must assert desired order explicitly.

## Product Rules

- Product title lookup priority:
  1. station product title;
  2. full catalog title;
  3. `Неизвестная игра`.
- Product problem flags:
  - `enabled is false` -> `отключен`;
  - `published is false` -> `не опубликован`;
  - `available is false` -> `недоступен`.

## Geo Rules

- RFC1918 endpoints are internal.
- Invalid IPs are rendered as unknown and logged.
- City/provider lookup is best-effort and must not fail command rendering.
- Distance is shown only when station coordinates and client coordinates are available.

## Formatting

- Short duration:
  - `< 1h`: `{m} мин {s} сек`;
  - `< 1d`: `{h} ч {m} мин`;
  - otherwise `{d} д {h} ч {m} мин`.
- Export duration: `HH:MM:SS` with total hours.
- Date display: `YYYY-MM-DD`.
- Time display: `HH:MM:SS`.
