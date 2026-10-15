# Multi-platform updates (API v2)

This extends steam-updates.md. The Steam transport, baseline, delivery, auth and
cursor guarantees remain unchanged.

## Coverage

UPDATE_PROVIDERS defaults to steam; allowed entries: steam,hoyo,wuwa,endfield,battlenet,bsg,epic,wargaming,lesta,nte.
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

No game downloads, binary manifest parsing, beta builds, HoYoPlay installer
notifications, or promise of server-side/all in-game hotfix coverage. Explicit preloads
are excluded; experimental XML source publication semantics remain unverified.

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

## Iteration 2: Fortnite admission and deferred sources

`epic` adds only Fortnite Windows/Live, exact Drova product
`d5f88d94-87d5-11e7-bb31-000000003778`, account `Epic Games`, object `epic:fortnite`.
Namespace fn, catalogItemId 4fe75bbc5a674f4f9b356b5c90567da5, appName Fortnite.
Client-credentials OAuth uses operator-provided EPIC_CLIENT_ID/EPIC_CLIENT_SECRET;
no user login, embedded credentials or runtime credential discovery. Tokens stay in memory,
refresh 60 seconds before expiry, with one refresh/retry on metadata 401. Missing credentials,
403, invalid schemas and preload preserve baseline and report safe coverage errors.
Select exactly one Fortnite / Live-Windows element. Require boolean isPreloaded=false;
missing/unknown publication status fails closed. Compare buildVersion + SHA1 hash, not signed
manifest URLs; never fetch manifests. No Epic Launcher link. Default providers remain steam.
Transport limits (including OAuth POST): 20 seconds, 2 MiB decoded, concurrency four,
no redirects. Never log authorization headers, OAuth response bodies or application secrets.
No DB migration or /v2 wire-shape change. All-Steam remains Steam-only; all_supported includes
newly admitted games. Deploy bot before enabling new provider to accept its model discriminator.

Wargaming/Lesta and NTE are admitted experimentally by explicit operator decision on
2026-10-15. Real-client/preload corroboration remains a reliability limitation, not a
release gate. Unknown/malformed schemas still preserve baseline without an event.

Acceptance: fixture-based OAuth request/expiry/401 tests, exact target and preload validation,
hash-only changes and rollback, network/schema recovery, registry/UI/API/store regression,
then two metadata-only reads from production before enabling epic. Reliability on a real
update is a separate observation, not implied by two equal reads.

Fortnite live admission (2026-10-15): two direct metadata reads from the production server
returned the same buildVersion/hash and element-level `isPreloaded: false`. Only whitelisted
fields were retained; manifest URLs and OAuth responses were not saved. This verifies the
current published Live element, not a historical preload transition or future API stability.


## Experimental XML adapters (operator opt-in)

Providers wargaming, lesta and nte remain disabled by default; production operator enables
all three for observation. Panel and digest label these sources experimental.
- Wargaming: WoT EU (WOT.EU.PRODUCTION), related WGC EU launcher (WGC.EU.PRODUCTION).
- Lesta: Мир кораблей RU (MK.RU.PRODUCTION); display this official title despite legacy
  catalog title World of Warships. Мир танков and LGC remain uncovered.
- NTE: Global resource configuration only. Selectable `nte:global` game has new coverage
  `resources_only` and linked `nte:resources` (kind resources). Only the linked object is
  polled/counts toward coverage; never claim game client or launcher detection.

Wargaming protocol: fixed HTTPS origin + metadata + patches_chain/; two known metadata
layouts, exact production app_id, fixed client_type/lang/required parts. One bounded
metadata refresh/retry on meta_need_update. Only one install chain; explicit preload
chains ignored, unknown or ambiguous chains rejected. delay_preload is not proof of release.
For each required part follow the unique complete chain from version 0 (missing version_from
means 0), reject gaps/branches/duplicates. Compare SHA256 of sorted terminal
(part, version_to, torrent SHA256) tuples; display version_name or primary part version.
Changing distribution hashes can notify without a client version change. No torrent downloads
or arbitrary application/URL redirects. This may still observe a build before its release.

NTE reads fixed Global config.xml, appId=3000001 from base64 JSON ResConfig, Tag=baseTag;
compares ResVersion + Extra/listHash. Display ResVersion. Ignore UpdateResVersion, optional
chunks, Devices, CDN and rollout configuration. A nonzero UpdateResVersion alone does not
notify. Use mirror only after transport/HTTP failure, never invalid metadata or newest-version
selection. Resource publication versus preload is not independently verified.

UTF-8 XML only, DTD/entities rejected before parsing, bounded size and existing HTTP limits.
Errors produce safe coverage codes; baseline, append-only journal, cursor and delivery
invariants unchanged. No DB migrations. Bot must be upgraded before watcher because
provider enums and resources_only extend the v2 contract. Production rollback restores
both coordinated databases, not just old images.
