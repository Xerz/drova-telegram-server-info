# Runtime Spec

## Environment

Production:

```dotenv
TELEGRAM_BOT_TOKEN=
BOT_SECRET_KEY=
DATABASE_URL=sqlite+aiosqlite:///data/drova_bot.sqlite3
LOG_LEVEL=INFO
TZ=Asia/Yekaterinburg
HTTP_PROXY=
HTTPS_PROXY=
DROVA_BASE_URL=https://services.drova.io
```

Specing/live tests:

```dotenv
DROVA_PROXY_TOKEN=
TEST_STATION_UUID=
TELEGRAM_BOT_TOKEN=
HTTP_PROXY=
HTTPS_PROXY=
```

## Startup

- Validate required env before starting polling.
- Run database migrations before polling.
- Initialize HTTP clients with timeouts and optional proxies.
- Register BotFather command list from code/config.
- Log startup configuration without secrets.

## Logging

Use structured logs with fields:

- `event`
- `chat_id_hash`
- `request_id`
- `drova_path`
- `status_code`
- `duration_ms`
- `error_code`

Never log token, raw IP, email, wallet or station description.

## Docker

- Runtime image uses Python 3.12+ slim.
- Data directory is mounted separately from source code.
- Compose may include optional xray/proxy service.
- Healthcheck verifies process responsiveness, not Drova credentials.

## Operations

- Bot should survive transient Drova and Telegram failures.
- Fatal startup misconfiguration fails fast.
- Export jobs should not prevent graceful shutdown.
- Live contract tooling is manual/CI-optional and separate from production entrypoint.
