# Expected Renderer Snapshots

These snapshots are intentionally high level. Exact punctuation may evolve, but tests must assert the same information hierarchy and safety rules.

## `/sessions`

```text
Последние 5 сессий · все станции

2026-05-18
1. Space Farm
Gamma Trial
client ...abcdef
IP: 198.51.100.30 · Testburg
🧪 trial 🟢 active
16:40-🟢 now (20 мин)

2. Cyber Rally
Alpha Station
client ...222222
IP: 203.0.113.20 · Example City
💳 prepaid ✅ finished
16:00-16:10 (10 мин)
Отзыв: ok

2026-05-17
3. Desktop Mode
Alpha Station
client ...111111
IP: 203.0.113.10 · Example City
🔁 subscription ✅ finished
16:00-16:02 (2 мин)
```

## `/current`

```text
1. Alpha Station · Cyber Rally · Example City · 16:00 · 10 мин
2. Beta Test Station · скрыта · UNVERIFIED · нет сессий
3. Gamma Trial · Trial · Space Farm · Testburg · active · 20 мин
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
