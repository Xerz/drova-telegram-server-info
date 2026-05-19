# Architecture Spec

## Stack

- Python 3.12+.
- Telegram framework: `aiogram` 3.x, async routers, callback data factories, middleware.
- HTTP client: `httpx.AsyncClient`.
- Data validation: Pydantic v2 models and `pydantic-settings`.
- Storage: SQLite via SQLAlchemy 2 async ORM and Alembic migrations.
- XLSX: `openpyxl`, executed in a worker thread/process through an explicit export service.
- Tests: `pytest`, `pytest-asyncio`, `respx` or equivalent HTTP mocking, fixture-based snapshot tests.

Pin exact minor versions during implementation in a lock file. The spec depends on these major APIs, not on a specific patch version.

## Package Layout

```text
src/drova_bot/
  app.py
  config.py
  telegram/
    routers/
    keyboards.py
    renderers.py
    callbacks.py
    middleware.py
  drova/
    client.py
    models.py
    errors.py
  domain/
    models.py
    services.py
    formatters.py
  storage/
    database.py
    repositories.py
    encryption.py
    migrations/
  exports/
    sessions.py
    products.py
  observability/
    logging.py
tests/
```

## Dependency Rules

- Telegram handlers call application/domain services, not raw API client directly.
- Drova API client has no dependency on Telegram or storage.
- Renderers are pure functions that accept domain DTOs and return text plus keyboard specs.
- Export services accept domain data, return file metadata and bytes/stream.
- Storage repositories do not perform network calls.
- Specing scripts remain outside `src/drova_bot`.

## Request Flow

1. Telegram update enters aiogram router.
2. Auth middleware loads `ChatProfile` from storage.
3. Handler validates command arguments and calls an application service.
4. Service uses Drova API client and repositories.
5. Renderer builds Russian message text and keyboard.
6. Handler sends or edits Telegram message.

## Error Model

- `UserNotConnected`: no token for chat.
- `InvalidUserInput`: invalid command argument.
- `DrovaUnauthorized`: token invalid and renewal failed.
- `DrovaUnavailable`: network, timeout, 5xx or malformed response.
- `DrovaPermissionDenied`: 403/permission-style API failure.
- `TelegramDeliveryFailed`: send/edit failure after fallback.
- `ExportTooLarge`: export exceeds configured row or time budget.

Each error maps to a stable Russian user message and structured log event.

## Concurrency

- Drova API calls are async.
- Export generation is offloaded so Telegram polling is not blocked.
- Per-chat mutating operations use a lightweight lock to avoid racing token/station settings.
- Publish-toggle confirmation includes station id and expected current `published` value.
