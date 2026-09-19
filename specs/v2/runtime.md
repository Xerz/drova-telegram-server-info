# Runtime Spec

## Environment

Production:

```dotenv
TELEGRAM_BOT_TOKEN=
BOT_SECRET_KEY=
DATABASE_URL=sqlite+aiosqlite:///data/drova_bot.sqlite3
LOG_LEVEL=INFO
TZ=Asia/Yekaterinburg
HTTP_PROXY=
HTTPS_PROXY=
DROVA_BASE_URL=https://services.drova.io
GEOLITE_CITY_DB=/data/GeoLite2-City.mmdb
GEOLITE_ASN_DB=/data/GeoLite2-ASN.mmdb
```

Specing/live tests:

```dotenv
DROVA_PROXY_TOKEN=
TEST_STATION_UUID=
TELEGRAM_BOT_TOKEN=
HTTP_PROXY=
HTTPS_PROXY=
```

## Startup

- Validate required env before starting polling.
- Run database migrations before polling.
- Initialize HTTP clients with timeouts and optional proxies.
- Register BotFather command list from code/config.
- Log startup configuration without secrets.

## Logging

Use structured logs with fields:

- `event`
- `chat_id_hash`
- `request_id`
- `drova_path`
- `status_code`
- `duration_ms`
- `error_code`

Never log token, raw IP, email, wallet or station description.

## Docker

- Runtime image uses Python 3.12+ slim.
- Production Compose pulls prebuilt `linux/amd64` images from GHCR; it has no `build` entries.
- `IMAGE_REPOSITORY` defaults to `ghcr.io/xerz/drova-telegram-server-info`; the watcher
  uses the same repository prefix with `-steam-watcher`. Both use `IMAGE_TAG` (default `latest`).
- GitHub Actions builds both images only after the test job succeeds. Pushes to `main`
  publish `latest` and `sha-<shortsha>`. Published GitHub Releases with `v<semver>` tags
  publish version tags without `v` and SHA tags. Stable releases also publish major.minor.
  Releases never move `latest`; pushing a tag alone does not publish a version.
- Branch/PR builds validate Dockerfiles without publishing. GHCR login uses GITHUB_TOKEN.
- Install and update with `docker compose pull` then `docker compose up -d`; add
  `--profile steam` to manage the watcher. No host Python, SteamCMD or local image build.
- Private GHCR packages require Docker login with package read access before pulling.
- Data directory is mounted separately from source code.
- Compose may include optional xray/proxy service.
- Healthcheck verifies process responsiveness, not Drova credentials.

## Operations

- Bot should survive transient Drova and Telegram failures.
- Fatal startup misconfiguration fails fast.
- Export jobs should not prevent graceful shutdown.
- Live contract tooling is manual/CI-optional and separate from production entrypoint.
- GeoLite lookup is optional and local-only. Download URLs:
  - `GeoLite2-City.mmdb`: `https://github.com/P3TERX/GeoLite.mmdb/raw/download/GeoLite2-City.mmdb`;
  - `GeoLite2-ASN.mmdb`: `https://github.com/P3TERX/GeoLite.mmdb/raw/download/GeoLite2-ASN.mmdb`.
- The standard Docker layout downloads databases into host `./data` and mounts that directory
  as container `/data`. A direct non-Docker launch may override the paths with relative
  `data/GeoLite2-*.mmdb` values.

## Optional Steam Watcher

GAME_UPDATES_ENABLED defaults false; STEAM_WATCHER_URL defaults to http://steam-watcher:8080.
When enabled, STEAM_WATCHER_TOKEN is required. The watcher has separate settings and volume;
Compose uses an optional steam profile. The bot survives watcher outages. See `steam-updates.md`.

## Multi-platform game updates

See `platform-updates.md` for the API v2 extension, linked launcher subscriptions,
provider registry and backwards-compatible migration/delivery requirements.
