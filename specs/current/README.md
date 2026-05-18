# Current Bot Spec Pack

Этот каталог фиксирует фактическое поведение текущего Telegram-бота и Drova API по состоянию на 2026-05-18. Spec основан на текущем коде и live API sampling через `.env.specing`.

## Состав

- `telegram-ux.md` - команды, callback-сценарии, тексты и ошибки Telegram UX.
- `drova-api.md` - используемые Drova API endpoints, параметры, поля ответов и write-flow.
- `domain-model.md` - доменные сущности и правила форматирования/расчетов.
- `storage-and-runtime.md` - окружение, локальные файлы, Docker/proxy, GeoLite.
- `exports.md` - CSV/XLSX выгрузки и правила расчета.
- `acceptance-scenarios.md` - будущие tests-first сценарии для rewrite.
- `fixtures/` - обезличенные live API fixtures и schema summary.

Raw API dumps хранятся только локально в `fixtures/raw/` и игнорируются git.
