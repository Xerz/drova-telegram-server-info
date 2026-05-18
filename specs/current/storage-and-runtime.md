# Storage And Runtime Current Spec

## Runtime Environment

- Required production env: `TELEGRAM_BOT_TOKEN`.
- Optional production env: `HTTP_PROXY`, `HTTPS_PROXY`, `LOG_LEVEL`, Telegram timeout variables.
- Specing-only env file: `.env.specing`.
  - `DROVA_PROXY_TOKEN` is used for Drova API sampling.
  - `TEST_STATION_UUID` is the only station allowed for write-flow sampling.
  - `TELEGRAM_BOT_TOKEN` is optional for future live Telegram UX checks.
  - `HTTP_PROXY` and `HTTPS_PROXY` are optional; if unreachable, sampler can fall back to direct HTTPS.

## Persistent Data

`persistentData.json` is a local JSON store ignored by git. Current top-level shape:

```json
{
  "authTokens": {},
  "userIDs": {},
  "limits": {},
  "selectedStations": {},
  "stationNames": {}
}
```

- Keys are stringified Telegram chat ids.
- `authTokens` stores Drova proxy tokens.
- `userIDs` stores Drova account UUIDs.
- `limits` stores integer session limits.
- `selectedStations` stores station UUID or absence for all stations.
- `stationNames` stores per-chat station UUID to station name maps.

Writes are immediate JSON rewrites. Storage errors are swallowed by the current code.

## Product Cache

- `products.json` maps `productId` to title.
- Loaded at import/start if present.
- Refreshed from `/product-manager/product/listfull2` after successful `/token` and when `/sessions` sees `Unknown game`.
- Cache write failures are not surfaced to Telegram users.

## GeoLite Data

- `GeoLite2-City.mmdb` and `GeoLite2-ASN.mmdb` are loaded from repo root.
- If missing, current code attempts to download them from `P3TERX/GeoLite.mmdb`.
- If loading fails, city/provider/distance gracefully fall back to default values.

## Docker And Proxy

- Docker image uses `python:3.12-slim`.
- Compose starts `bot` and `xray`.
- Compose injects `HTTP_PROXY=http://xray:10808` and `HTTPS_PROXY=http://xray:10808` into the bot container.
- `xray-config/config.json` is required at runtime and ignored by git.
- Compose bind-mounts the whole repo into `/app`, so runtime JSON/cache files persist on host.

## Specing Artifacts

- `scripts/sample_live_api.py` is a specing utility only and must not be imported by the future bot.
- `specs/current/fixtures/*.json` are sanitized and tracked.
- `specs/current/fixtures/raw/` is ignored and may contain sensitive raw API responses.
