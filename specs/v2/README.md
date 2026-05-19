# Drova Telegram Bot V2 Spec

Этот каталог является итоговым spec для нового бота from scratch. Старый код используется только как источник фактов, но не как архитектурный шаблон.

## Цель

Собрать современного Telegram-бота для владельца Drova-станций, который:

- показывает состояние станций, последние сессии, endpoints и проблемные продукты;
- управляет публикацией только через защищенный UX;
- делает CSV/XLSX выгрузки без блокировки обработки апдейтов;
- хранит токены безопаснее текущего `persistentData.json`;
- строится строго по пайплайну `spec -> tests -> code`.

## Состав V2 Spec

- `product.md` - продуктовый объем, роли, команды и правила UX.
- `architecture.md` - стек, слои, модули, зависимости.
- `telegram-ux.md` - команды, callback flows, тексты, клавиатуры и состояния.
- `drova-api.md` - контракт Drova API client и live contract policy.
- `domain-model.md` - типы, вычисления, инварианты.
- `storage.md` - SQLite schema, token security, migration from legacy.
- `exports.md` - CSV/XLSX контракты и async generation.
- `tests.md` - tests-first matrix и acceptance gates.
- `runtime.md` - env, Docker, logging, observability, operations.
- `next-iteration.md` - backlog/spec for the next V2 feature cycle.
- `fixtures/` - API и UI fixtures для разработки и тестов.

## Non-goals

- Не переносить legacy-код в новый package.
- Не сохранять текущие англо-русские тексты как UX-контракт.
- Не выполнять write live checks на production-станциях.
- Не добавлять web admin panel в V2.
