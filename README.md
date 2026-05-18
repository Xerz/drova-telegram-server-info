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

