# Drova Telegram Bot V2

New implementation scaffold for the Drova Telegram bot. The product source of truth is
`specs/v2`; production code lives under `src/drova_bot`.

## Local Workflow

This project uses `uv` with Python 3.12+:

```bash
python3 -m uv run pytest
python3 -m uv run ruff check
python3 -m uv run mypy src tests
```

Live Drova checks are opt-in and use `.env.specing`. Normal unit tests must not require
network access or real tokens.

## Live Contract Checks

Live checks use the V2 `DrovaClient` against real Drova endpoints and are skipped unless
explicitly enabled. Put secrets only in `.env.specing`; it is ignored by git.
Read-only checks include account, products, stations, sessions, endpoints, station products
and unused promocodes.

Read-only checks:

```bash
python3 -m uv run pytest tests/live --run-live
```

Write checks for publish and station-product enabled toggles:

```bash
python3 -m uv run pytest tests/live --run-live --run-live-write
```

Write checks only target `TEST_STATION_UUID`, verify the toggled state, and roll back
in `finally`. For the station-product enabled toggle, set `TEST_PRODUCT_UUID` to force a
specific game; otherwise the test uses the first product returned for `TEST_STATION_UUID`.

Fixture sampling for spec work also uses `.env.specing`:

```bash
python3 scripts/sample_live_api.py
```

The sampler requires `DROVA_PROXY_TOKEN` and `TEST_STATION_UUID`. Set `TEST_PRODUCT_UUID`
when sampling a specific station-product edit fixture. Write/rollback fixtures are skipped
by default; enable them only when intentionally touching the test station:

```bash
python3 scripts/sample_live_api.py --include-writes
```

## Runtime

Create `.env` from `.env.example` and set `TELEGRAM_BOT_TOKEN` plus a Fernet
`BOT_SECRET_KEY`. A key can be generated with:

```bash
python3 -m uv run python -c "from drova_bot.storage import TokenEncryptor; print(TokenEncryptor.generate_key())"
```

Run locally:

```bash
python3 -m uv run drova-bot
```

Startup validates required env, runs packaged Alembic migrations, registers Telegram
commands, wires storage/application services into aiogram, and starts polling.

GeoLite lookup is optional and local-only. Put these files next to the bot process, or
override `GEOLITE_CITY_DB` / `GEOLITE_ASN_DB`:

```bash
curl -L -o GeoLite2-City.mmdb https://github.com/P3TERX/GeoLite.mmdb/raw/download/GeoLite2-City.mmdb
curl -L -o GeoLite2-ASN.mmdb https://github.com/P3TERX/GeoLite.mmdb/raw/download/GeoLite2-ASN.mmdb
```

Docker runtime:

```bash
docker compose up --build
```

The compose file mounts `./data` as the SQLite data directory and reads secrets from
`.env`; secrets are not baked into the image. Healthcheck uses
`python -m drova_bot.tools.healthcheck` and does not call Telegram or Drova.

Published image:

```bash
docker pull ghcr.io/<owner>/<repo>:latest
docker run --rm --env-file .env -v "$PWD/data:/data" ghcr.io/<owner>/<repo>:latest
```

For a real deployment, replace `<owner>/<repo>` with the GitHub repository path in
lowercase. The container expects `TELEGRAM_BOT_TOKEN`, `BOT_SECRET_KEY`, and optionally
`DATABASE_URL`; the default database URL points at `/data/drova_bot.sqlite3`.

CI runs the normal network-free gates and verifies the Docker image builds. On pushes to
`main` and `v*.*.*` tags it publishes `linux/amd64` images to GHCR as:

- `latest` for `main`;
- `sha-<shortsha>` for published commits;
- `<major>.<minor>.<patch>` and `<major>.<minor>` for version tags.

Runtime secrets stay in `.env` or the deployment environment and are never baked into the
image. Live contract checks stay manual and opt-in.
