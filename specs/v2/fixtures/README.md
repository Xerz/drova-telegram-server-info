# V2 Fixtures

## API Fixtures

`api/` contains sanitized live API samples copied from `specs/current/fixtures`. These fixtures are canonical for V2 model parsing and API client contract tests.

Use them for:

- Pydantic response model tests.
- API client happy-path parsing tests.
- Regression tests for fields observed in Drova responses.

Do not use them for exact Telegram snapshot text because they are larger than needed and contain redacted placeholders.

## UI Fixtures

`ui/` contains small deterministic fixtures built for renderer and handler tests.

Use them for:

- `/sessions` snapshot tests.
- `/current` dashboard snapshot tests.
- `/disabled` product flags.
- `/stations` endpoint grouping.
- Export unit tests with predictable rows.

## Raw Data Policy

V2 fixtures must be tracked only after sanitization. Raw API responses stay under `specs/current/fixtures/raw/` or another ignored path.
