# V2 Rewrite Backlog Notes

Этот файл не меняет current-spec. Он фиксирует решения и долги для будущего rewrite после утверждения фактического поведения.

## Architecture

- Оставить Python, но перейти на явную layered architecture: Telegram handlers, application services, Drova API client, storage repositories, renderers, exporters.
- Использовать async HTTP client с typed request/response models.
- Все пользовательские сценарии покрывать tests-first: fixture-based unit tests, handler tests, export tests, live contract checks отдельно.
- Sampling-утилиты держать вне production package.

## Security And Data

- Не хранить Drova tokens в plain JSON для production v2 без явного решения.
- Маскировать tokens, IP, email, wallet, station descriptions and coordinates во всех логах и fixtures.
- Write API operations должны иметь явную protection policy: только выбранная тестовая станция в specing, подтверждение/rollback в live checks.
- Отдельно решить миграцию `persistentData.json` или отказ от совместимости.

## Telegram UX

- Перевести ответы в единый русский UX.
- Добавить нормальные ошибки: нет токена, токен истек, API недоступен, станция не найдена, лимит невалиден.
- Переработать `/station` в paginated/selectable UI.
- Для publish-toggle добавить более явное состояние и защиту от случайного нажатия.
- Добавить BotFather command list как часть deploy/runtime checklist.

## API And Reliability

- Централизовать token renewal, retries, timeout policy, typed errors and observability.
- Не блокировать event loop sync HTTP и XLSX generation.
- Ограничить тяжелые export-запросы или сделать progress/status UX.
- Зафиксировать live contract tests на read-only endpoints и отдельный guarded write-flow для `TEST_STATION_UUID`.

## Known Current Bugs Or Risks

- `/limit` может упасть на нечисловом значении.
- `/station <id>` принимает любой текст без проверки существования станции.
- Storage write errors silently ignored.
- `/station` inline keyboard кладет все станции в одну строку.
- `products_data_update` не зарегистрирован как команда.
- `removeToken` не сообщает пользователю, если токена не было.
- Current export mutates session row by setting missing `finished_on`.
- Current API client and export code are synchronous inside async handlers.
