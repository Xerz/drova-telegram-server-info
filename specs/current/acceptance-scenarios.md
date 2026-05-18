# Acceptance Scenarios For Rewrite

Эти сценарии должны быть реализованы как tests-first набор перед написанием v2-кода. Все API-зависимые сценарии используют sanitized fixtures, live contract checks выполняются отдельно.

## Telegram Commands

- `/start`: новый пользователь получает справку и предупреждение о токене; команда не требует Drova token.
- `/token <valid>`: бот валидирует token через account endpoint, сохраняет token/user id, обновляет products cache и station names.
- `/token <invalid>`: бот не сохраняет token и возвращает понятную ошибку.
- `/removeToken`: при наличии token удаляет его и подтверждает; без token возвращает явное состояние.
- `/station`: при наличии token показывает список станций с выбором `all`; без token просит setup.
- `/station <valid_id>`: сохраняет выбранную станцию и подтверждает.
- `/station <invalid_id>`: v2 должен валидировать station id и не сохранять мусор.
- `/limit <positive_int>`: сохраняет лимит и подтверждает.
- `/limit <invalid>`: не падает и возвращает ошибку валидации.
- `/sessions`: строит список последних сессий по выбранной станции или всем станциям.
- `/sessions short`: скрывает сессии длительностью до 5 минут.
- `/current`: показывает по одной последней сессии на станцию и state-formatting.
- `/disabled`: показывает проблемные продукты или empty-state.
- `/stationsInfo`: разделяет внешние и внутренние endpoints.

## Callback Flows

- `update_sessions` редактирует исходное сообщение и сохраняет short/full режим.
- `set_server_id_{uuid}` меняет выбранную станцию; `set_server_id_-` выбирает все станции.
- `current:update` обновляет `/current`.
- `current:publish:show` и `current:publish:hide` меняют только видимость publish-кнопок.
- `current:publish:toggle:{uuid}` меняет `published`, перечитывает станции и показывает результат.
- `update_disabled` и `update_stationsinfo` перечитывают данные и редактируют исходные сообщения.

## Exports

- `/dumpall`: генерирует CSV по каждой станции с ожидаемыми колонками.
- `/dumpOnefile`: генерирует один XLSX с теми же данными.
- `/dumpStationsProducts`: генерирует state matrix по продуктам и станциям.
- `/dumpStationsProductsWithTime`: генерирует time matrix по всем доступным сессиям.
- `/dumpStationsProductsMonth`: генерирует time matrix только за 30 дней.

## API Failure And Safety

- Drova 401 запускает token renewal и ровно один retry исходного запроса.
- Drova non-200 превращается в typed error и пользовательское сообщение.
- Telegram HTML parse error приводит к plain text fallback.
- Live write contract check разрешен только для `TEST_STATION_UUID` и обязан вернуть `published` к исходному состоянию.
