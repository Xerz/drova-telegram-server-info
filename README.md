# Drova Telegram Bot

Telegram-бот для владельцев станций Drova: состояние станций и сессий, управление
публикацией и играми, баланс, промокоды, XLSX/CSV-выгрузки и уведомления об обновлениях игр и лаунчеров.

Запуск — через Docker Compose из готовых образов GHCR. Образы собираются в GitHub Actions;
Python и SteamCMD на хосте устанавливать не требуется.

| Сервис | Назначение | Данные |
| --- | --- | --- |
| `drova-bot` | Команды Telegram, профили, подписки и доставка сводок | Каталог `./data` на хосте |
| `steam-watcher` | SteamCMD и HTTP-адаптеры обновлений, журнал событий и внутренний API | Docker-volume `steam-watcher-data` |

Бот запускается по умолчанию. Вотчер включается отдельно профилем `steam` и получает
публичный каталог Drova без пользовательских токенов. Входящие порты открывать не нужно:
бот использует Telegram polling, API вотчера доступен только в сети Compose и защищён
служебным Bearer-токеном.

## Быстрый запуск

Нужны Docker Engine с Compose V2 (команда `docker compose`) и копия репозитория.
Все команды ниже выполняются из его корня. Для Steam-вотчера используйте Linux-сервер
с архитектурой x86_64: образ рассчитан на `linux/amd64`. При локальной проверке на ARM
под эмуляцией SteamCMD завершался с SIGSEGV; получение buildid нужно проверить на целевом сервере.

### 1. Подготовьте настройки и скачайте образ

При первой установке:

```bash
cp .env.example .env
mkdir -p data
docker compose pull drova-bot
```

По умолчанию используется `ghcr.io/xerz/drova-telegram-server-info:latest`.
Если GHCR возвращает `denied` или `403`, проверьте доступ к пакету и выполните
`docker login ghcr.io --username <GitHub-логин>`. Для приватных пакетов в качестве пароля
используйте GitHub PAT (classic) с правом `read:packages`; публичные пакеты доступны без входа.
После входа повторите `docker compose pull drova-bot`.
Подробнее об авторизации — в [документации GHCR](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry#authenticating-to-the-container-registry).

Сгенерируйте ключ шифрования Drova-токенов:

```bash
docker compose run --rm --no-deps drova-bot python -c \
  'from drova_bot.storage import TokenEncryptor; print(TokenEncryptor.generate_key())'
```

Впишите в `.env` токен бота, полученный у Telegram BotFather, и сгенерированный ключ:

```dotenv
TELEGRAM_BOT_TOKEN=<токен Telegram-бота>
BOT_SECRET_KEY=<сгенерированный Fernet-ключ>
```

Остальные значения из `.env.example` подходят для стандартного запуска. Сохраните
`BOT_SECRET_KEY`: он нужен для расшифровки токенов после перезапуска или восстановления
БД. При обновлении приложения новый ключ генерировать не нужно. `.env` не добавляйте в git.

### 2. Запустите бота

```bash
docker compose config --quiet
docker compose up -d drova-bot
docker compose ps
docker compose logs --tail=100 -f drova-bot
```

При старте бот применяет миграции SQLite и регистрирует команды в Telegram.
`Ctrl+C` завершает просмотр логов; контейнер продолжает работать.

Откройте бота в Telegram, отправьте `/start`, затем `/token <Drova proxy token>`.
Выберите станцию через `/station` или все станции через `/station_all`.
Drova-токен подключается в чате, в `.env` его добавлять не требуется.

## Настройки `.env`

| Переменная | Назначение / значение по умолчанию |
| --- | --- |
| `IMAGE_REPOSITORY` | `ghcr.io/xerz/drova-telegram-server-info` — базовое имя образа; вотчер использует суффикс `-steam-watcher` |
| `IMAGE_TAG` | `latest` — общий тег обоих образов; можно закрепить опубликованную версию или `sha-<shortsha>` |
| `TELEGRAM_BOT_TOKEN` | Обязательный токен Telegram-бота |
| `BOT_SECRET_KEY` | Обязательный Fernet-ключ для шифрования токенов |
| `DATABASE_URL` | `sqlite+aiosqlite:////data/drova_bot.sqlite3` — БД в постоянном каталоге |
| `TZ` | `Asia/Yekaterinburg` — часовой пояс по умолчанию |
| `LOG_LEVEL` | `INFO` |
| `DROVA_BASE_URL` | `https://services.drova.io` |
| `HTTP_PROXY`, `HTTPS_PROXY` | Необязательные прокси для внешних запросов |
| `EXPORT_ROW_LIMIT` | `50000` — ограничение строк экспорта |
| `EXPORT_TIMEOUT_SECONDS` | `120` — таймаут экспорта |
| `GAME_UPDATES_ENABLED` | `false` — рассылка обновлений игр и лаунчеров выключена |
| `STEAM_WATCHER_TOKEN` | Общий служебный секрет бота и вотчера; нужен при включении вотчера |
| `STEAM_POLL_SECONDS` | `300` — интервал проверки сборок |
| `STEAM_CATALOG_SECONDS` | `3600` — интервал обновления каталога |

Compose задаёт боту адрес `http://steam-watcher:8080`. Запросы к нему идут в обход
внешних HTTP-прокси. Пользовательские Drova-токены и токен Telegram вотчеру не передаются.

После изменения `.env` примените настройки командой `docker compose up -d drova-bot`.
Если используете вотчер — `docker compose --profile steam up -d`.
Команда `restart` сама по себе новые переменные окружения не применяет.

## Дополнительные платформы и лаунчеры

В существующем контейнере `steam-watcher` доступны адаптеры `hoyo`, `wuwa`,
`endfield`, `battlenet`, `bsg`. Имя образа, профиль `steam`, volume и адрес API
сохранены для совместимости. По умолчанию `UPDATE_PROVIDERS=steam`: обновление
образов само по себе новые источники не включает.

```dotenv
UPDATE_PROVIDERS=steam,hoyo,wuwa,endfield,battlenet,bsg
```

| Источник | Покрытие |
| --- | --- |
| HoYoverse | Genshin, HSR, ZZZ Global PC; HI3 America/Europe при появлении в каталоге с проверенной Global-ссылкой |
| WuWa | Основная Global PC-сборка и лаунчер WuWa |
| Endfield | Global PC-клиент, опубликованные ресурсы и GRYPHLINK Official |
| Battle.net | Production EU: WoW, Diablo III/IV/II Resurrected, StarCraft II, Overwatch 2, Hearthstone; Battle.net App |
| BSG | Только BSG Launcher, связанный с EFT и Arena; версии самих игр не отслеживаются |

Нестимовые продукты требуют явного соответствия в
`src/drova_bot/steam_watcher/registry.py`; неизвестные продукты отражаются в
покрытии. Call of Duty и неоднозначные WoW Classic-продукты пока не сопоставлены.
Пользовательские аккаунты платформ не нужны. Бета-ветки, индивидуальные каналы
поэтапного распространения и обновления установщика HoYoPlay не отслеживаются.
Явные предзагрузки исключаются; для экспериментальных Wargaming/Lesta и NTE
отделение предзагрузки от выпуска пока не подтверждено официальным клиентом.
Все внутриигровые хотфиксы и серверные изменения не гарантируются.

Подписка на игру включает её поддерживаемые лаунчеры и ресурсы. Общий лаунчер
приходит одной строкой, даже если выбран через несколько игр. Режим «Все Steam-игры»
после миграции остаётся прежним; остальные платформы добавляются через выбор игр
или явное включение «Все поддерживаемые игры». Выбор относится к конкретной платформе.

Перед включением источников выполните два чтения публичных метаданных:

```bash
docker compose --profile steam run --rm --no-deps \
  -v "$PWD/scripts/probe_updates.py:/tmp/probe_updates.py:ro" \
  steam-watcher python /tmp/probe_updates.py --live
```

Можно ограничить проверку: `--live --providers hoyo,wuwa`. Пробник не изменяет БД,
не скачивает игры, выводит версии, число успешных чтений, покрытие и длительность.
Steam проверяется отдельным пробником ниже. Недоступные источники дают ненулевой
код завершения; проверьте их из сети сервера до включения. HTTP-адаптеры используют
настроенный прокси, внутренний API бота всегда обращается напрямую.

После проверки примените изменения через `docker compose --profile steam up -d`.
Обновляются оба образа с одинаковым закреплённым `IMAGE_TAG`. Миграции сохраняют
профиль, курсор, очередь и уже отправленные части сводок. Для отката на старую
схему нужно восстановить согласованную резервную копию обеих БД вместе со старыми
образами; обратная миграция журнала не поддерживается.

API v2: `/v2/games`, `/v2/events`. `/v1` продолжает отдавать только Steam;
`/health` также показывает покрытие и свежесть по источникам. API не публикуется
наружу и требует служебный Bearer-токен. Недокументированные upstream API проверены
на момент реализации; перед production нужны наблюдение и сверка реального обновления.

## Уведомления об обновлениях Steam

### Включение вотчера

Сгенерируйте отдельный служебный секрет:

```bash
docker compose run --rm --no-deps drova-bot python -c \
  'import secrets; print(secrets.token_hex(32))'
```

Сохраните его в `.env`. На время проверки оставьте рассылку выключенной:

```dotenv
STEAM_WATCHER_TOKEN=<сгенерированный служебный секрет>
GAME_UPDATES_ENABLED=false
```

Скачайте и запустите образ вотчера из GHCR:

```bash
docker compose --profile steam pull steam-watcher
docker compose --profile steam up -d steam-watcher
docker compose --profile steam ps
docker compose --profile steam logs --tail=100 -f steam-watcher
```

Перед включением рассылки проверьте настоящий SteamCMD на целевом сервере:

```bash
docker compose --profile steam run --rm --no-deps \
  -v "$PWD/scripts/probe_steam.py:/tmp/probe_steam.py:ro" \
  steam-watcher python /tmp/probe_steam.py --app-id 730 --app-id 570
```

Затем выполните проверку всего каталога, заменив `--app-id 730 --app-id 570` на
`--catalog`. Результат содержит число доступных игр, недоступные AppID, количество
повторных чтений и длительность обхода. Сопоставьте её с интервалом проверки
`STEAM_POLL_SECONDS`. Проверки читают публичные метаданные без скачивания игр;
SteamCMD может обновлять собственный клиент. Некоторые AppID недоступны анонимному входу.

После успешной проверки установите в `.env` `GAME_UPDATES_ENABLED=true` и примените:

```bash
docker compose --profile steam up -d
```

Подписки пользователей изначально выключены — каждый включает их в своём чате.

### Подписки и сводки

`/game_updates` или кнопка «Обновления игр» в `/account_menu` открывает настройки:
«Выключено», «Выбранные игры», «Все Steam-игры», «Все поддерживаемые игры». Поиск — `/game_updates Dota`.
Выбранные игры сохраняются при смене режима, список выводится по 10 игр на страницу.
Нужен подключённый Drova-токен. Подписки относятся к чату и не зависят от выбранной станции.

Вотчер проверяет ветку `public` каждые 5 минут. Первая успешная проверка сохраняет
исходный buildid без события; последующая смена сборки, включая откат, попадает в сводку.
Каталог обновляется каждый час, новые Steam-игры автоматически входят в режим «Все».

Бот отправляет сводку в начале часа, только если есть изменения: название игры,
время обнаружения в часовом поясе чата и ссылка на новости Steam. Несколько обновлений
одной игры объединяются, длинные сводки разбиваются на сообщения. Начало подписки
не рассылает старые события, отключение отменяет очередь, `/logout` удаляет подписки.

`/updates_on` и `/updates_off` по-прежнему управляют обновлениями станции.
Вотчер не проверяет установленные на станциях версии и не обновляет игры.

### Восстановление и диагностика

После простоя бот объединяет накопленные изменения в сводку за фактический период.
Курсор, очередь и подтверждённые части сообщений сохраняются в SQLite. Неоднозначный
сетевой результат отправки в Telegram может привести к редкому дублю. Блокировка бота
приостанавливает рассылку чату; повторный выбор режима возобновляет её с текущего момента.

При недоступности Steam или вотчера остальные команды бота продолжают работать.
Панель `/game_updates` показывает свежесть данных и покрытие каталога. Healthcheck
вотчера проверяет его HTTP API и БД; статус `healthy` сам по себе не подтверждает
успешное получение buildid из Steam. Для диагностики смотрите события в логах:
`steam_cycle_complete`, `steam_refresh_failed`, `steam_feed_unavailable`, `steam_digest_retry`.

## Управление контейнерами

Команды с `--profile steam` применяются к обоим сервисам. Если вотчер не используете,
выполняйте их без этого параметра.

```bash
# Состояние и журналы
docker compose --profile steam ps
docker compose --profile steam logs --tail=100 -f

# Остановить сервисы, сохранив контейнеры и данные
docker compose --profile steam stop

# Запустить ранее остановленные контейнеры
docker compose --profile steam start

# Пересоздать при необходимости и применить текущую конфигурацию
docker compose --profile steam up -d
```

Для отключения Steam установите `GAME_UPDATES_ENABLED=false`, примените настройки
командой `docker compose up -d drova-bot`, затем остановите вотчер:
`docker compose --profile steam stop steam-watcher`.
Один запуск без `--profile steam` уже работающий вотчер не останавливает.

### Обновление контейнеров

Дождитесь успешного workflow CI нужного коммита или релиза в GitHub Actions.
Для обновлений из `main` оставьте `IMAGE_TAG=latest`. Для фиксированной версии укажите
в `.env` тег опубликованного образа без `v`, например `IMAGE_TAG=0.3.0` после выпуска
релиза `v0.3.0`. Оба сервиса будут использовать одну версию.

Загрузите образы и пересоздайте контейнеры:

```bash
docker compose --profile steam pull
docker compose --profile steam up -d
docker compose --profile steam ps
docker compose --profile steam logs --tail=100
```

Без Steam уберите `--profile steam`. Перед обновлением сохраните резервную копию данных.
Если в релизе изменились Compose-файл или параметры окружения, обновите их из соответствующей
версии репозитория, сохранив секреты в `.env`. Миграции применяются автоматически при старте.

### Постоянные данные

- `./data/drova_bot.sqlite3` — профили, зашифрованные токены, настройки и очередь сводок.
- Volume `steam-watcher-data` — БД вотчера `/data/steam_watcher.sqlite3`, сборки и журнал.
  Docker Compose добавляет к имени volume префикс проекта.
- `.env` — настройки и ключ шифрования; храните резервную копию отдельно и защищённо.

Для согласованной резервной копии остановите оба сервиса через
`docker compose --profile steam stop`, скопируйте каталог `./data` и содержимое volume
вотчера, затем выполните `docker compose --profile steam start`. Восстанавливайте БД
при остановленных сервисах вместе с исходным `BOT_SECRET_KEY`.

Обычный `docker compose --profile steam down` сохраняет данные. Добавление `-v` удаляет
именованный volume вотчера. Сохраняйте имя Compose-проекта при переносе, чтобы подключить
тот же volume, и запускайте по одному экземпляру каждого сервиса.
Журнал событий автоматически не очищается — контролируйте свободное место.

## GeoLite: города и ASN

География клиентов опциональна. Поместите базы в каталог `./data`, который Compose
монтирует в `/data`. Например, загрузите готовые базы из проекта P3TERX/GeoLite.mmdb:

```bash
mkdir -p data
curl -L -o data/GeoLite2-City.mmdb https://github.com/P3TERX/GeoLite.mmdb/raw/download/GeoLite2-City.mmdb
curl -L -o data/GeoLite2-ASN.mmdb https://github.com/P3TERX/GeoLite.mmdb/raw/download/GeoLite2-ASN.mmdb
```

Пути внутри контейнера уже указаны в `.env.example`:

```dotenv
GEOLITE_CITY_DB=/data/GeoLite2-City.mmdb
GEOLITE_ASN_DB=/data/GeoLite2-ASN.mmdb
```

После добавления или замены баз перезапустите бот: `docker compose restart drova-bot`.
Без этих файлов бот работает без географии.

## Основные команды

```text
/start                    статус подключения
/token <token>            подключить Drova proxy token
/logout                   удалить токен, настройки и подписки чата
/station                  выбрать станцию
/station_all              выбрать все станции
/station_manage           управление публикацией, доступом, играми и описанием
/limit <N>                лимит последних сессий, 1..100
/sessions                 последние сессии
/sessions_short           сессии дольше 5 минут
/current                  текущее состояние станций
/account_menu             меню аккаунта
/account                  баланс минут и выплаты
/usage                    статистика использования
/disabled                 проблемные продукты
/stations                 станции и endpoints
/games                    выбрать игру на выбранной станции
/game_updates [название]  подписки на обновления игр/лаунчеров и поиск игр
/promocode <minutes>      выпустить prepaid-промокод
/promocodes               неактивированные prepaid-промокоды
/export_sessions          один XLSX со всеми сессиями
/export_sessions_csv      CSV-файлы по каждой станции
/export_products          XLSX-матрица состояния продуктов
/export_product_time      XLSX по времени использования продуктов
```

Совместимые формы `/station all`, `/sessions short`, `/export ...`, `/dump...`,
технический алиас `/game <product_id>` и прямые команды управления станцией сохранены.

## Разработка и проверки

Код находится в [`src/drova_bot`](src/drova_bot), спецификации и фикстуры — в
[`specs/v2`](specs/v2/README.md). Изменения проходят цикл
`spec → fixtures → failing tests → code → passing tests`.

Для разработки вне контейнеров нужны Python 3.12+ и `uv`:

```bash
uv sync --frozen --dev
uv run pytest
uv run ruff check
uv run mypy src tests
```

Обычные тесты не обращаются к реальным Telegram, Drova или Steam и не требуют токенов.
Если установлен Docker Compose, `uv run python scripts/check_compose.py` проверяет
подстановку образов и профили без запуска контейнеров; эта проверка также входит в CI.
Live-проверки выключены по умолчанию и не входят в CI. Drova-проверки используют `.env.specing`:

```bash
uv run pytest tests/live --run-live
uv run pytest tests/live --run-live --run-live-write
```

Write-проверки работают только с `TEST_STATION_UUID` и откатывают изменения в `finally`.
Для проверки игр можно задать `TEST_PRODUCT_UUID`. Подробности — в
[`specs/v2/tests.md`](specs/v2/tests.md).

Автономные Steam-тесты: `uv run pytest tests/steam`. Проверка с установленным SteamCMD:

```bash
STEAM_LIVE=1 STEAMCMD_PATH=/path/to/steamcmd.sh uv run pytest tests/steam/test_live.py
```

## Сборка в GitHub Actions и релизы

Workflow [CI](.github/workflows/ci.yml) запускает pytest, Ruff и mypy, затем собирает
оба образа для `linux/amd64`. Публикация выполняется только после успешных проверок:

| Образ | Назначение |
| --- | --- |
| `ghcr.io/xerz/drova-telegram-server-info` | Бот |
| `ghcr.io/xerz/drova-telegram-server-info-steam-watcher` | Steam-вотчер |

- Push в `main` публикует `latest` и `sha-<shortsha>`.
- Публикация GitHub Release с тегом `v<версия>` публикует эту версию без `v` и SHA-тег.
  Для стабильной версии добавляется тег `<major>.<minor>`; prerelease сохраняет полный суффикс.
- Релизы не меняют `latest`. Push одного тега без публикации Release сборку не запускает.
- Pull requests и ветки `codex/**` проходят тесты и сборку без публикации.

Для выпуска версии обновите `version` в `pyproject.toml` и `uv.lock`, отправьте изменения
в GitHub, затем создайте **Releases → Draft a new release** с новым тегом `v<версия>`
на нужном коммите и нажмите **Publish release**. После успешного CI этот тег без `v`
можно указать в `IMAGE_TAG` на сервере. Создание draft без публикации сборку не запускает.

Actions входит в GHCR через встроенный `GITHUB_TOKEN` с правом `packages: write`.
В форке задайте `IMAGE_REPOSITORY=ghcr.io/<owner>/<repository>` в нижнем регистре.
Видимость пакетов и права на скачивание настраиваются отдельно в GitHub Packages.


### Fortnite (Epic Games)

Провайдер `epic` отслеживает только опубликованную Windows/Live-сборку Fortnite.
Добавьте `epic` к `UPDATE_PROVIDERS` и задайте `EPIC_CLIENT_ID`/`EPIC_CLIENT_SECRET`
в защищённом `.env` (`chmod 600 .env`). Это реквизиты клиентского приложения OAuth,
а не пользовательский логин; их действительность зависит от Epic. Они не встроены
в образ и не загружаются автоматически из сторонних проектов. Access token живёт
только в памяти. Не публикуйте вывод `docker compose config` с заполненным `.env`.

Сравниваются версия и хеш сборки; предзагрузки и неизвестный статус публикации
отклоняются. Манифесты/игры не скачиваются. Серверные изменения Fortnite,
Epic Launcher self-update и остальные игры EGS этим не покрываются.
Первое чтение не вызывает уведомления. Режим «Все Steam-игры» не расширяется;
«Все поддерживаемые игры» включает Fortnite, а в выбранном режиме её нужно отметить.

Перед включением выполните два чтения метаданных из сети сервера:

```sh
docker compose --profile steam run --rm --no-deps \
  -v "$PWD/scripts/probe_updates.py:/probe_updates.py:ro" \
  --entrypoint python steam-watcher /probe_updates.py --live --providers epic
```

Пробник ничего не записывает в БД и не запускает Telegram polling. При ошибках
`epic_credentials_missing`, `epic_unauthorized`, `epic_forbidden` или
`epic_publication_unconfirmed` сначала устраните причину; последняя сборка сохраняется.
Обновляйте бот до включения нового провайдера в вотчере, чтобы он понимал новые записи API.

Wargaming/Lesta и NTE доступны экспериментально: ограничения и найденные протоколы
сохранены в [исследовательской записке](specs/v2/update-source-admission.md).
Два успешных чтения подтверждают доступность источника, но не заменяют сверку
с настоящим обновлением официального клиента.


### Экспериментальные Wargaming, Lesta и NTE

Добавьте `wargaming,lesta,nte` к существующему `UPDATE_PROVIDERS`, чтобы включить:

| Источник | Что отслеживается |
| --- | --- |
| Wargaming | World of Tanks EU (SD, EN) и связанный Wargaming Game Center EU |
| Lesta | Мир кораблей RU (high, RU), без Lesta Game Center |
| NTE | Только Global-ресурсы по ResVersion/listHash, без гарантии детекта клиента и лаунчера |

Мир танков, WoWS/WoWP EU и другие игры автоматически не добавляются. NTE выбирается
как игра в `/game_updates`, а уведомления приходят с типом «Ресурсы». WGC включается
вместе с WoT EU. Режим «Все поддерживаемые игры» получает эти игры автоматически;
«Все Steam-игры» и выбранные подписки сохраняют прежний охват.

Все три источника помечены экспериментальными в меню и сводках. Поведение официальных
клиентов во время предзагрузки ещё не сверено: возможны ранние или пропущенные уведомления.
Явные preload-цепочки Wargaming не учитываются; неизвестные ответы сохраняют последнюю
корректную сборку. Хеши Wargaming/Lesta обозначают дистрибутив: переупаковка тоже может
вызвать уведомление при прежней версии игры. NTE сравнивает основной ResVersion;
UpdateResVersion и списки устройств/дополнительных ресурсов не сравниваются.

Проверка перед включением (без скачивания пакетов, торрентов или игр):

```sh
docker compose --profile steam run --rm --no-deps \
  -v "$PWD/scripts/probe_updates.py:/probe_updates.py:ro" \
  --entrypoint python steam-watcher /probe_updates.py --live --providers wargaming,lesta,nte
```

Обновляйте оба образа, сначала бот, затем вотчер. Поле покрытия `/v2` дополнено
`resources_only`; миграции БД не нужны. Для отката сохраняйте согласованную копию
обеих БД: старый бот не понимает новые источники. Первое чтение создаёт тихую исходную
точку. Для сверки полезно сравнить время сводки с проверкой обновлений в клиенте;
успешные повторные чтения сами по себе не подтверждают полноту обнаружения.
