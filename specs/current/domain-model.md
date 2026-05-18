# Domain Model Current Spec

## Account

- Identified by `uuid` from `/accounting/myaccount`.
- Stored as `userIDs[chat_id]` and used as `merchant_id` for sessions and `user_id` for station/product endpoints.
- Token is a Drova proxy token stored per Telegram chat.

## Station

- API object from `/server-manager/servers`.
- Primary id is `uuid`; display name is `name`.
- Current bot stores `stationNames[chat_id][station_uuid] = station_name`.
- State formatting:
  - station name is strikethrough when `state` is not `LISTEN`, `HANDSHAKE` or `BUSY`;
  - station name is italic when `published` is false;
  - station name is bold when there is an active session or station state is `HANDSHAKE`.
- Trial marker is appended when `groups_list` contains `Free trial volunteers`.

## Session

- A session belongs to a station by `server_id`, account by `merchant_id`, and product by `product_id`.
- `created_on` and `finished_on` are millisecond timestamps.
- Active sessions may have no `finished_on`; current duration is calculated from current wall-clock time.
- `/sessions short` filters out sessions with calculated duration <= 5 minutes.
- `/sessions` reverses API order before rendering and numbers entries with `limit - i + 1`.

## Product

- Product catalog maps `productId -> title` and is cached in `products.json`.
- Per-station product state is problematic when any of `enabled`, `published`, `available` is false.
- State text concatenates `Not enabled`, `Not published`, `Not available`; otherwise `Active` or caller-provided ok text.

## Endpoint And Geo

- Endpoints are split by `ipaddress` RFC1918 check.
- GeoLite City DB resolves city for client and endpoint IPs.
- GeoLite ASN DB resolves provider/organization.
- Distance is haversine distance between station latitude/longitude and client IP GeoLite location; missing data returns `-1` and is hidden in `/current`.

## Derived Values

- Short duration format:
  - `< 1h`: `{minutes}m:{seconds}s`
  - `< 1d`: `{hours}h {minutes}m`
  - otherwise `{days}d {hours}h {minutes}m`
- Long duration format for exports: `HH:MM:SS`, with total hours.
- Client id display in `/sessions` is the last 6 characters of `client_id`.
