# Drova Telegram Bot

Telegram-бот для владельца станций Drova. Бот показывает состояние станций, текущие и
последние сессии, проблемы с играми, баланс prepaid-минут, статистику использования,
позволяет управлять публикацией станций, играми на станции, промокодами и выгрузками.

Код новой версии находится в `src/drova_bot`, продуктовая спецификация и фикстуры - в
`specs/v2`.

## Возможности

- подключение Drova proxy token через `/token`;
- выбор одной станции или режима всех станций;
- `/current` с публикацией, текущими сессиями и городом клиента;
- `/sessions` и `/sessions_short` с пагинацией, IP и городом клиента;
- `/station_manage` для управления выбранной станцией через кнопки;
- `/account_menu` для аккаунтных сводок через кнопки;
- `/disabled`, `/stations`, `/usage`, `/account`;
- `/games` с постраничным выбором игры, чтением параметров запуска, скрытием/открытием
  игры на выбранной станции и подтверждением скрытия на всех станциях;
- `/promocode <minutes>` и `/promocodes` для prepaid-промокодов;
- XLSX/CSV выгрузки: сессии, матрица продуктов, время по продуктам;
- SQLite storage с Alembic migrations и шифрованием токенов через `BOT_SECRET_KEY`;
- opt-in live contract tests против реального Drova API.

## Основные команды

```text
/start                 статус подключения
/token <token>         подключить Drova proxy token
/logout                удалить токен и настройки чата
/station               выбрать станцию
/station_all           выбрать все станции
/station_manage        меню управления станциями
/limit <N>             лимит последних сессий, 1..100
/sessions              последние сессии
/sessions_short        сессии дольше 5 минут
/current               текущее состояние станций
/account_menu          меню аккаунта
/account               баланс минут и выплаты
/usage                 статистика использования
/disabled              проблемные продукты
/stations              станции и endpoints
/games                 выбрать игру на выбранной станции
/promocode <minutes>   выпустить prepaid-промокод
/promocodes            неактивированные prepaid-промокоды
/export_sessions       один XLSX со всеми сессиями
/export_sessions_csv   CSV-файлы по каждой станции
/export_products       XLSX-матрица состояния продуктов
/export_product_time   XLSX по времени использования продуктов
```

Старые формы вроде `/station all`, `/sessions short`, `/export ...`, `/dump...`,
технические `/game <product_id>` алиасы и прямые команды управления станцией остаются для
совместимости, но основной UX для операций - `/station_manage` и `/account_menu`.

## Локальная разработка

Проект использует Python 3.12+ и `uv`.

```bash
python3 -m uv sync --dev
python3 -m uv run pytest
python3 -m uv run ruff check
python3 -m uv run mypy src tests
```

Обычные тесты не требуют сети, Telegram token или Drova token.

## Запуск

Создайте `.env` из `.env.example` и задайте как минимум:

```dotenv
TELEGRAM_BOT_TOKEN=
BOT_SECRET_KEY=
DATABASE_URL=sqlite+aiosqlite:///data/drova_bot.sqlite3
TZ=Asia/Yekaterinburg
DROVA_BASE_URL=https://services.drova.io
```

Fernet-ключ для `BOT_SECRET_KEY`:

```bash
python3 -m uv run python -c "from drova_bot.storage import TokenEncryptor; print(TokenEncryptor.generate_key())"
```

Локальный polling-запуск:

```bash
python3 -m uv run drova-bot
```

При старте бот валидирует env, прогоняет Alembic migrations, регистрирует команды в
Telegram и запускает polling.

## Docker

Локальная сборка и запуск через compose:

```bash
docker compose up --build
```

`docker-compose.yml` читает секреты из `.env` и монтирует `./data` как директорию SQLite.
Секреты не попадают в образ.

Опубликованный образ в GHCR:

```bash
docker pull ghcr.io/<owner>/<repo>:latest
docker run --rm --env-file .env -v "$PWD/data:/data" ghcr.io/<owner>/<repo>:latest
```

Замените `<owner>/<repo>` на путь GitHub-репозитория в нижнем регистре. По умолчанию база
ожидается в `/data/drova_bot.sqlite3`.

## GeoLite

GeoIP-интеграция опциональна. Если базы не заданы, бот продолжит работать без географии.

```bash
curl -L -o GeoLite2-City.mmdb https://github.com/P3TERX/GeoLite.mmdb/raw/download/GeoLite2-City.mmdb
curl -L -o GeoLite2-ASN.mmdb https://github.com/P3TERX/GeoLite.mmdb/raw/download/GeoLite2-ASN.mmdb
```

Пути можно задать через `GEOLITE_CITY_DB` и `GEOLITE_ASN_DB`.

## Live Contract Tests

Live-проверки используют `.env.specing`, выключены по умолчанию и не входят в обычный CI.
Секреты кладите только в `.env.specing`; файл игнорируется git.

Read-only проверки:

```bash
python3 -m uv run pytest tests/live --run-live
```

Write-проверки публикации и скрытия/открытия игры:

```bash
python3 -m uv run pytest tests/live --run-live --run-live-write
```

Write-тесты работают только с `TEST_STATION_UUID`, проверяют состояние и откатывают
изменения в `finally`. Для station-product toggle можно задать `TEST_PRODUCT_UUID`;
иначе берется первая игра тестовой станции.

Сэмплер фикстур:

```bash
python3 scripts/sample_live_api.py
python3 scripts/sample_live_api.py --include-writes
```

## Релизы и GHCR

CI запускает сетево-независимые gates и проверяет Docker build. При пуше в `main` и при
пуше тегов `v*.*.*` workflow публикует `linux/amd64` образ в GHCR:

- `latest` для `main`;
- `sha-<shortsha>` для опубликованных коммитов;
- `<major>.<minor>.<patch>` и `<major>.<minor>` для version tags.

Обычный релиз:

```bash
git checkout main
git pull origin main
git merge codex/rewrite-2026
python3 -m uv run pytest
python3 -m uv run ruff check
python3 -m uv run mypy src tests
git push origin main
git tag v0.2.0
git push origin v0.2.0
```

Если версия уже была опубликована, сначала поднимите `version` в `pyproject.toml`,
закомитьте изменение в `main`, затем ставьте новый tag.
