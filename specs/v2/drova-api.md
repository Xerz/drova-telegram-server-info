# Drova API Spec

## Client Contract

The V2 `DrovaClient` exposes typed async methods:

```python
async def get_account() -> Account
async def renew_token(proxy_token: str) -> str
async def get_products_full() -> list[CatalogProduct]
async def get_servers(user_id: str) -> list[Station]
async def get_sessions(
    merchant_id: str | None = None,
    server_id: str | None = None,
    limit: int | None = None,
) -> SessionPage
async def get_server_products(user_id: str, server_id: str) -> list[StationProduct]
async def get_server_endpoints(server_id: str, limit: int | None = None) -> list[Endpoint]
async def set_server_published(server_id: str, published: bool) -> None
async def issue_promocode(minutes: int) -> list[Promocode]
async def get_unused_promocodes() -> list[Promocode]
```

## Endpoint Mapping

| Method | Path | Auth | Notes |
| --- | --- | --- | --- |
| `GET` | `/accounting/myaccount` | Yes | Validates token and returns account. |
| `POST` | `/token-verifier/renewProxyToken` | No | Body `{"proxy_token": token}`; returns `proxyToken`. |
| `GET` | `/product-manager/product/listfull2` | No | Full public product catalog. |
| `GET` | `/server-manager/servers` | Yes | Query `user_id`. |
| `GET` | `/session-manager/sessions` | Yes | Query `merchant_id`, `server_id`, `limit` as needed. |
| `GET` | `/server-manager/serverproduct/list4edit2/{server_id}` | Yes | Query `user_id`. |
| `GET` | `/server-manager/serverendpoint/list/{server_id}` | Yes | Query `server_id`, optional `limit`. |
| `POST` | `/server-manager/servers/{server_id}/set_published/{true\|false}` | Yes | No body required by observed API. |
| `GET` | `/accounting/prepaid/issue_promocodes/1/{playtime_msecs}` | Yes | Issues one prepaid promocode. Treat as write and do not retry automatically. |
| `GET` | `/accounting/prepaid/list_unused_promocodes/false` | Yes | Lists not-yet-activated promocodes. |

## Token Renewal

- On HTTP 401 for an authenticated request, call `renew_token`.
- If renewal returns a token, persist it before retrying.
- Retry original request exactly once.
- If retry fails with 401, raise `DrovaUnauthorized`.
- Never log old or new token.

## HTTP Policy

- Default timeout: 10 seconds connect/read total budget unless implementation chooses separate `httpx.Timeout` fields.
- Retry only idempotent read requests on network timeout, max 2 attempts with small jitter.
- Do not automatically retry `set_server_published` or `issue_promocode`.
- Validate JSON shape through Pydantic models; unknown fields are allowed and preserved only when useful for logging/tests.

## Live Contract Fixtures

Canonical live sanitized fixtures live under `fixtures/api/`.

- `account.json`
- `servers.json`
- `sessions_all_limit_5.json`
- `server_*_sessions_limit_5.json`
- `server_*_products.json`
- `server_*_endpoints_limit_5.json`
- `products_full.json`
- `promocodes_issue_60.json`
- `promocodes_unused.json`
- `test_station_publish_*.json`
- `schema-summary.json`
- `sampling-report.json`

## Live Contract Checks

- Read-only checks may run against all stations from `.env.specing`.
- Write check may run only when `TEST_STATION_UUID` is set.
- Write check sequence:
  1. Read servers and find test station.
  2. Store original `published`.
  3. Toggle to `not original`.
  4. Read servers and verify new state.
  5. Roll back to original in `finally`.
  6. Read servers and verify original state.

Any write check implementation must fail closed if the target station is not present.
