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

Docker runtime:

```bash
docker compose up --build
```

The compose file mounts `./data` as the SQLite data directory and reads secrets from
`.env`; secrets are not baked into the image. Healthcheck uses
`python -m drova_bot.tools.healthcheck` and does not call Telegram or Drova.

Still separate follow-up slices: persisted export job lifecycle, deploy CI, and Geo
enrichment.
