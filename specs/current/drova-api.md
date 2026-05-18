# Drova API Current Spec

## Sampling Evidence

Live API sampling выполнен через `scripts/sample_live_api.py` и `.env.specing`.

- Все 17 sampled requests завершились HTTP 200.
- Получены 3 станции, 993 продукта каталога, sessions samples с лимитом 5, products/endpoints по каждой станции.
- Configured proxy из `.env.specing` был недоступен на текущем хосте, sampler переключился на direct HTTPS; это зафиксировано в `fixtures/sampling-report.json`.
- Write-flow выполнялся только на `TEST_STATION_UUID`: toggle `published`, чтение-подтверждение, rollback, чтение-подтверждение.

## Общие правила API

- Base URL: `https://services.drova.io`.
- Authenticated endpoints используют header `X-Auth-Token: <token>`.
- Текущий production-код использует `requests` с timeout 5 секунд; sampling-утилита использует timeout 20 секунд.
- При HTTP 401 production-клиент вызывает `POST /token-verifier/renewProxyToken` с JSON `{"proxy_token": old_token}`, сохраняет `proxyToken` и повторяет исходный запрос один раз.
- При сетевом исключении production API wrapper возвращает `(None, 0)`.

## Endpoints

| Label | Method/path | Auth | Params/body | Fixture |
| --- | --- | --- | --- | --- |
| Account | `GET /accounting/myaccount` | Yes | none | `fixtures/account.json` |
| Token renewal | `POST /token-verifier/renewProxyToken` | No | `proxy_token` body | sampled only if needed |
| Product catalog | `GET /product-manager/product/listfull2` | No | none | `fixtures/products_full.json` |
| Servers | `GET /server-manager/servers` | Yes | `user_id` | `fixtures/servers.json` |
| Sessions | `GET /session-manager/sessions` | Yes | optional `merchant_id`, `server_id`, `limit` | `fixtures/sessions_all_limit_5.json`, `fixtures/server_*_sessions_limit_5.json` |
| Server products | `GET /server-manager/serverproduct/list4edit2/{server_id}` | Yes | `user_id` | `fixtures/server_*_products.json` |
| Server endpoints | `GET /server-manager/serverendpoint/list/{server_id}` | Yes | `server_id`, optional `limit` | `fixtures/server_*_endpoints_limit_5.json` |
| Publish toggle | `POST /server-manager/servers/{server_id}/set_published/{true\|false}` | Yes | path boolean | `fixtures/test_station_publish_*.json` |

## Observed Response Fields

- Account: `uuid`, `name`, `roles`, billing flags, balance fields, contact/payment fields. Sensitive fields are redacted in fixtures.
- Server/station: `uuid`, `name`, `state`, `published`, `verified`, `city_name`, `groups_list`, `product_list`, `latitude`, `longitude`, heartbeat and lifecycle timestamps.
- Session container: object with `sessions`.
- Session: `uuid`, `server_id`, `merchant_id`, `product_id`, `client_id`, `creator_ip`, `created_on`, `finished_on`, `billing_type`, `status`; optional fields in code include `score_text`, `score_reason`, `abort_comment`, `score`, `parent`, `sched_hints`.
- Server product: `productId`, `title`, `enabled`, `published`, `available`, `verified`, `needVpn`, `useDefaultDesktop`.
- Endpoint: `uuid`, `server_id`, `ip`, `base_port`, `priority`, `externally_routable`, `user_defined`, `updated_on`.
- Product catalog: `productId`, `title`, display/description/media fields, age/license/account/VPN flags.

## Error Semantics In Current Bot

- Any non-200 or missing body usually becomes `Error` or `Error: <status>`.
- Token validation fails if `/accounting/myaccount` is not 200 or does not include `uuid`.
- Unknown product ids trigger a product catalog refresh and then message rebuild.
- `set_server_published` status 200 is treated as success; any other status becomes `Publish error: <status>`.
