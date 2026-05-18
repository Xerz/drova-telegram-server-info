# Expected Renderer Snapshots

These snapshots are intentionally high level. Exact punctuation may evolve, but tests must assert the same information hierarchy and safety rules.

## `/sessions`

```text
Последние 5 сессий · все станции

2026-05-18
1. Space Farm
Gamma Trial
client ...abcdef
trial active
11:20:00-now (40 мин 0 сек)

2. Cyber Rally
Alpha Station
client ...222222
prepaid finished
10:40:00-10:50:00 (10 мин 0 сек)
Отзыв: ok

2026-05-17
3. Desktop Mode
Alpha Station
client ...111111
subscription finished
10:40:00-10:42:00 (2 мин 0 сек)
```

## `/current`

```text
1. Alpha Station · Cyber Rally · 10:40 · 10 мин
2. Beta Test Station · скрыта · UNVERIFIED · нет сессий
3. Gamma Trial · Trial · Space Farm · active · 40 мин
```

## `/disabled`

```text
Alpha Station
Space Farm: отключен

Beta Test Station
Desktop Mode: не опубликован

Gamma Trial
Space Farm: недоступен
```

## `/stations`

```text
Alpha Station
City A
Внешние:
203.0.113.11:48000
Внутренние:
192.168.1.10:48000

Beta Test Station · скрыта · UNVERIFIED
Endpoints не найдены.

Gamma Trial · Trial
City G
Внешние:
198.51.100.45:48100
```
