# Multi-platform updates (API v2)

This extends steam-updates.md. The Steam transport, baseline, delivery, auth and
cursor guarantees remain unchanged.

## Coverage

UPDATE_PROVIDERS defaults to steam; allowed entries: steam,hoyo,wuwa,endfield,battlenet,bsg.
One existing watcher container/database runs independent non-overlapping provider loops
(300 seconds, bounded backoff to 1800 seconds), and an independent hourly public catalog
refresh. HTTP metadata requests have a 20-second deadline, 2 MiB decoded response limit,
no redirects, at most four simultaneous requests, and no account credentials.
Failures preserve last good data. Empty/broken catalogs preserve the previous snapshot.

A versioned registry explicitly maps Drova product IDs and requiredAccount to provider,
external ID, Windows channel and related objects. No title matching. Only registered
products present in the catalog activate non-Steam objects. Unknown products count as
unmapped; a removed/reintroduced object establishes a new silent baseline.

- HoYo: Global Genshin/HSR/ZZZ, HI3 America/Europe when catalogued. Branches -> Sophon
  getBuild; compare build_id, not stale getGamePackages; ignore pre_download.
- WuWa: Global default game version+indexFileMd5; launcher version+md5. Ignore gray cohorts.
- Endfield: Global game version+game_files_md5, published resource versions, and Official
  GRYPHLINK version+md5. Resource updates are separate objects; never compare CDN URLs.
- Battle.net: explicit production EU product mapping; BuildId+BuildConfig, plus bna launcher.
- BSG: public GetLauncherDistrib zlib/JSON Version+hash; EFT/Arena rows clearly say
  "Отслеживается только BSG Launcher". Do not query authenticated game update endpoints.

No game downloads, binary manifest parsing, preloads, beta builds, HoYoPlay installer
notifications, or promise of server-side/all in-game hotfix coverage.

## Models and compatibility

Objects have stable compact string id, provider, external_id, platform, channel, kind
(game/resources/launcher), title, optional appid (Steam only), related game IDs,
news_url, display version, fingerprint, last_success_at and error_code.
Launcher/resource objects identify the games whose subscriptions accept their events.
Selectable games carry linked object IDs; launcher-only entries have no game fingerprint.

GET /v2/games returns games, objects, per-provider status and catalog/check timestamps.
GET /v2/events retains stream_id:seq cursors and pagination semantics; each event carries
object identity, previous/new fingerprint, display version and observed_at UTC.
GET /v1 endpoints project only Steam fields, advancing the cursor over non-Steam events.
GET /health retains old fields and adds per-provider checks, coverage and safe errors.
All endpoints retain shared Bearer auth and bot-side proxy bypass.

Migrations preserve watcher stream UUID, event sequence, app baselines and all bot queue,
feed/cursor, selection and sent-part records. Legacy Steam payloads map to steam:<appid>.
Old all mode remains Steam-only; all_supported explicitly includes every supported game.

## UX and delivery

/game_updates retains profile auth, search and pages of ten games, adding platform and
coverage labels. Four modes: off, selected, all (Все Steam-игры), all_supported
(Все поддерживаемые игры). Selections survive mode changes. Old numeric callbacks remain
valid for Steam; new callbacks use compact object IDs and remain <=64 bytes.

Selecting a game includes supported linked launchers/resources. Shared launcher events
are delivered once, eligible only after activation of at least one related game. Removal
of the last eligible relation discards pending events; removing one of several keeps them.
Current catalog relations are checked before delivery, so removed games cannot keep a
launcher subscription alive. Historical events never become eligible due to later selection.

Digest groups by object ID (which includes channel/type), displays platform, update kind,
latest version and local time, with official links. Existing all-Steam digest format remains
compatible. UTF-16 message limits, retries, logout, blocked-chat and sent-part guarantees
remain as specified in steam-updates.md.

## Acceptance

Fixtures precede tests and code. Cover every provider's request/response, version and hash
changes, rollback, malformed/missing data, preload/gray exclusion and recovery; mixed API
pagination and auth; both real migration histories; linked notifications, activation,
cancellation, modes, callbacks, split/retry/logout, independent provider scheduling.
Opt-in metadata probes read twice and report coverage/errors/duration, never download games.
CI publishes existing GHCR image names only after full tests/lint/types/Compose validation.
Production deployment is a separate task; new providers remain disabled by default.
