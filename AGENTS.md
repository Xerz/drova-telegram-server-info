# AGENTS.md

## Mission

Build the new Drova Telegram bot from scratch using `specs/v2` as the source of truth.

The previous bot implementation was intentionally removed. Do not restore, copy, or pattern-match legacy files from git history unless the user explicitly asks for archaeology. The implementation must follow:

```text
spec -> fixtures -> failing tests -> code -> passing tests
```

## Source Of Truth

Read these files before implementation work:

- `specs/v2/README.md`
- `specs/v2/product.md`
- `specs/v2/architecture.md`
- `specs/v2/telegram-ux.md`
- `specs/v2/drova-api.md`
- `specs/v2/domain-model.md`
- `specs/v2/storage.md`
- `specs/v2/exports.md`
- `specs/v2/tests.md`
- `specs/v2/runtime.md`
- `specs/v2/fixtures/README.md`
- `specs/v2/fixtures/manifest.json`

Use `specs/v2/fixtures/api/` for API model and client contract tests.
Use `specs/v2/fixtures/ui/` for deterministic renderer, handler, and export tests.

## Implementation Order

1. Scaffold a modern Python 3.12+ package under `src/drova_bot/`.
2. Add project metadata, dependency management, test tooling, lint/type tooling, and a minimal README for V2.
3. Implement typed domain models and pure formatters first.
4. Write fixture-based tests for domain rules and renderers before Telegram handlers.
5. Implement the async Drova API client with token-renewal tests.
6. Implement SQLite storage, migrations, token encryption, and legacy import tests.
7. Implement Telegram routers, keyboards, callbacks, middleware, and Russian UX.
8. Implement exports as non-blocking services.
9. Add runtime entrypoint, Docker/deploy files, logging, and operational docs.
10. Add opt-in live contract tests using `.env.specing`.

## Architecture Constraints

- Use `aiogram` 3.x for Telegram.
- Use `httpx.AsyncClient` for Drova API.
- Use Pydantic v2 for response/settings models.
- Use SQLite with SQLAlchemy 2 async ORM and migrations.
- Keep Telegram handlers thin; domain/application services own behavior.
- Keep renderers pure and fixture-testable.
- Keep `scripts/sample_live_api.py` outside the production package.
- Do not block the event loop with sync HTTP or XLSX generation.

## Safety Rules

- Never commit `.env`, `.env.specing`, runtime SQLite databases, raw API dumps, tokens, emails, wallets, raw IPs, or station descriptions.
- Live read checks may use all stations returned by the account.
- Live write checks may only use `TEST_STATION_UUID` and must rollback in `finally`.
- Production publish-toggle must require explicit confirmation and stale-state protection.
- Logs must be structured and must not include secrets or sensitive Drova fields.

## Testing Rules

- Every command and callback in `specs/v2/tests.md` needs tests before implementation.
- API tests must verify paths, query params, auth headers, parsing, retries, and token renewal.
- Renderer tests should use `specs/v2/fixtures/ui/expected-messages.md` as intent.
- Export tests must assert headers, formulas, representative cells, filenames, and injectable clock behavior.
- Live contract tests must be opt-in and skipped by default.

## Current Repo State

At this stage the repository is intentionally mostly specification-only:

- Keep `specs/v2` intact unless the user asks to change the product spec.
- Treat `specs/v2` changes as product decisions, not incidental refactors.
- If implementation reveals a spec gap, update the spec first, then tests, then code.
