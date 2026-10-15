# V2 Fixtures

## API Fixtures

`api/` contains sanitized live API samples. These fixtures are canonical for V2 model parsing and API client contract tests.

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

V2 fixtures must be tracked only after sanitization. Raw API responses stay under `specs/v2/fixtures/api/raw/` or another ignored path.

## Next Iteration Sampling

Future account, station-product, server-control and statistics fixtures are specified in
`../next-iteration.md`. They must be sampled through `.env.specing` with sanitized raw
payloads, and every write fixture must have an explicit rollback/verification path before
it is allowed into the sampler. The sampler is read-only by default; write fixtures require
an explicit `--include-writes` run against `TEST_STATION_UUID`.

## Steam Fixtures

`steam/` contains synthetic public metadata/VDF including missing, truncated and noisy output.
`ui/steam-digest.html` is an exact deterministic digest fixture. No raw Steam dumps are tracked.

## Runtime Fixtures

`runtime/deployment.json` contains expected Compose image references for default deployment,
a pinned release and a custom GHCR repository. These cases contain no credentials.

`platforms/metadata.json` contains minimal synthetic protocol fixtures for public
update adapters; no complete upstream dumps, account credentials or download payloads.

`platforms/epic.json` is a minimal synthetic Fortnite protocol fixture based on research;
`isPreloaded=false` is a required admission assertion, confirmed by two live reads
from the production network on 2026-10-15. Manifest URL is deliberately invalid; no OAuth credentials included.

`platforms/{wot,wgc,mk}-{meta,chain}.xml` and `platforms/nte.xml` are whitelisted
projections of public metadata read on 2026-10-15. Versions, hashes and channel identities
are preserved; CDN/torrent URLs, localization, rollout/device lists and unrelated fields
are removed. Synthetic mutations in tests cover failure/preload branches; they are not
claimed as captured real-world preload responses.
