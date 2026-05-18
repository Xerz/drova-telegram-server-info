# Tests Spec

## Pipeline

Every feature follows:

```text
spec -> fixture -> failing test -> implementation -> passing test
```

No command handler is considered done without handler tests and renderer tests.

## Test Groups

- Domain unit tests: duration, state flags, product flags, station sorting, Geo fallback.
- Renderer snapshot tests: `/sessions`, `/current`, `/disabled`, `/stations`, errors.
- API client tests: request path/query/header, response parsing, token renewal, typed errors.
- Storage tests: migrations, token encryption, legacy import.
- Handler tests: command arguments, auth middleware, callback flows.
- Export tests: CSV columns, XLSX headers/formulas, async job behavior.
- Live contract tests: explicitly opt-in and use `.env.specing`.

## Fixture Usage

- `fixtures/api/` are live sanitized API fixtures copied from current sampling.
- `fixtures/ui/` are small deterministic fixtures for renderer and handler snapshots.
- Tests must not depend on raw live dumps.
- Tests must not require internet unless marked live contract.

## Required Acceptance Gates

- `/token` valid and invalid flows.
- `/logout` removes token and selected station.
- `/station` paginated picker and all-stations selection.
- `/limit` valid and invalid inputs.
- `/sessions` full and short mode.
- `/current` dashboard with mixed station states.
- Publish confirmation success, cancel and stale-state failure.
- `/disabled` empty and non-empty states.
- `/stations` endpoint grouping.
- `/promocode <minutes>` validates integer minutes, issues one code and renders it monospace.
- `/promocodes` lists unused codes monospace.
- All export variants.
- Token renewal on 401 with exactly one retry.
- Telegram HTML fallback.

## Live Contract Safety

- Read-only live tests can run for account, products, servers, sessions, server products and endpoints.
- Write live test must only target `TEST_STATION_UUID`.
- Write live test must use `try/finally` rollback and fail if rollback verification fails.
- CI must not run live tests by default.
