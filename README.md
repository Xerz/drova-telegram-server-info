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

Write check for publish toggle:

```bash
python3 -m uv run pytest tests/live --run-live --run-live-write
```

The write check only targets `TEST_STATION_UUID`, verifies the toggled state, and rolls
back in `finally`.

Fixture sampling for spec work also uses `.env.specing`:

```bash
python3 scripts/sample_live_api.py
```

The sampler requires `DROVA_PROXY_TOKEN` and `TEST_STATION_UUID`. Set `TEST_PRODUCT_UUID`
when sampling the next station-product edit fixture. Write/rollback fixtures are skipped
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

CI runs the normal network-free gates and verifies the Docker image builds. Live contract
checks stay manual and opt-in.
