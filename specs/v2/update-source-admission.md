# Admission record: next update sources (2026-10-15)

## Fortnite: admitted for implementation and production probe

Exact catalog mapping and OAuth contract: platform-updates.md. Production-network research
read the official endpoint twice: matching build/hash, element.isPreloaded=false.
The checked fixture contains only whitelisted fields and a synthetic manifest URL.
Client app credentials were explicitly approved by the operator, provisioned once from
Legendary's public client configuration, and saved only in the server's protected environment.
Runtime never fetches that configuration. Rotation/revocation can interrupt coverage.
There is no official SLA for this launcher API. A real update transition remains unobserved.

Metadata endpoint:
https://launcher-public-service-prod06.ol.epicgames.com/launcher/api/public/assets/v2/platform/Windows/namespace/fn/catalogItem/4fe75bbc5a674f4f9b356b5c90567da5/app/Fortnite/label/Live

## Wargaming/Lesta: hold, no supported provider yet

Two-step anonymous XML candidates, repeat reads succeeded during research:

| Object | Origin | GUID | Parts | client_type/lang |
| --- | --- | --- | --- | --- |
| WoT EU | https://wgus-woteu.wargaming.net | WOT.EU.PRODUCTION | client,locale,sdcontent | sd/EN |
| WGC EU | https://wguswgc-eu.wargaming.net | WGC.EU.PRODUCTION | win32 | wgc/EN |
| Мир кораблей RU | https://lstus-ru.lesta.ru | MK.RU.PRODUCTION | client,locale,sdcontent,hotfix | high/RU |

GET /api/v1/metadata/?chain_id=unknown&protocol_version=7.5&guid=GUID
Then GET /api/v1/patches_chain/ (trailing slash required), query game_id=GUID,
protocol_version=1.11, metadata_protocol_version=7.5, installation_id=metadata-research,
client_type/lang from table, metadata_version/chain_id from metadata,
and PART_current_version=0 for each required part.

Catalog snapshot mappings (must revalidate live before implementation):
WoT EU c1661a7c-4950-4346-a193-103fb385b6d6;
Мир кораблей 21d8c648-8d39-4b3f-8989-69d58fbe7dff, account Lesta,
shop URL https://lesta.ru/ru/games/mk despite snapshot title World of Warships.
Do not map by title. Old WOWS.RU.PRODUCTION redirects application ID to MK.RU.PRODUCTION;
never follow arbitrary upstream redirect URLs.

Missing evidence: actual preload fixture/client capture distinguishing published install
chains, and corroboration of WGC win32 self-update with an installed client's version/log.
Current delay_preload=False is insufficient. No guessed XML adapter is shipped as supported.
Once admitted: safe XML (no DTD/entities), accept only known chains/components, canonical
fingerprint of sorted part/terminal version_to/torrent SHA256. Hash-only changes mean
redistributed packages, not necessarily modified gameplay. Ignore URLs/config metadata version.

## NTE Global: hold, no supported provider yet

GET https://ntecdn2.perfectworld.com/clientRes/publish_PC/Version/Windows/config.xml
Mirror ntecdn1.perfectworld.com. Both read twice during research, same ResVersion/listHash.
Base64 JSON ResConfig contains appId=3000001, branchName=PC_140.
Candidate fingerprint ResVersion + Extra/listHash; AppVersion=0.0 is not a client version.
Catalog snapshot UUID 3d02d4c9-0dfb-44fd-aeb2-2a00d288bf11, account NTE.

Missing evidence: official Global client's request to this configuration, interpretation as
client vs resources, publication vs preload. Do not substitute CN (appId=1289), installation
EXE version, or maximum mirror version. Do not download ResList.bin.zip.

## Minimal client evidence needed to resume held stages

On an ordinary official Windows client, record cold start and manual update-check requests:
method, hostname/path, query/header names and sanitized metadata response, displayed versions,
channel and whether preload is offered. Do not retain authorization/cookies/device IDs,
private paths or signed URLs. Include a known preload/release transition for WG/NTE and a
launcher version/log match for WGC. Verify metadata-only replay without user credentials.
If unavailable, leave the source unsupported; release Fortnite independently.
