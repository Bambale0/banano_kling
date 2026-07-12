# Roadmap

Этот roadmap описывает не wish-list, а реальное состояние репозитория и ближайшие приоритеты по стабилизации на `2026-07-12`.

## 1. Уже реализовано

### Core product

- Telegram bot с webhook runtime
- Mini App backend и static frontend path
- Image generation flows
- Video generation flows
- Motion control
- Talking avatar
- Prompt-by-photo
- Video-to-prompt paid flow
- Feed, prompt library, repeat/remix/share сценарии
- Balance, packages, promo codes, referrals, partner mechanics

### Integrations

- Kie/Kie Market callbacks
- Kling-family flows
- Seedream / Seedance / Grok / Veo / Gemini Omni / Wan / Nano Banana families
- CryptoBot / Lava / YooKassa / Telegram Stars

### Operations

- health endpoint
- internal read-only APIs
- DB backup loop
- payment reconcile loops
- test suite по критичным потокам

## 2. Главный текущий фокус

Проект выглядит как продукт в late integration stage: фичей много, поэтому следующий выигрыш не в наращивании surface area, а в стабилизации.

### Приоритет A: runtime consistency

- сократить расхождения между Telegram flow и Mini App flow
- удерживать единые model ids, price ids и deep-link semantics
- упрощать крупные orchestration modules без изменения публичного поведения

### Приоритет B: storage clarity

- окончательно нормализовать SQLite/Postgres documentation и migration path
- держать schema/docs/tests синхронными
- сократить ambiguity around legacy DB assets in repo

### Приоритет C: webhook/payment hardening

- сохранять strict idempotency
- сохранять signature verification coverage
- укреплять retry/reconciliation contracts

### Приоритет D: docs and operator ergonomics

- привести документацию к коду
- задокументировать scripts/backfill/repair workflows
- снизить зависимость от устных знаний по эксплуатации

## 3. Ближайший практический backlog

### Документация и контракты

- поддерживать `README`, `architecture`, `tracemap_*`, `runbook` синхронно с кодом
- для новых provider changes обновлять не только сервис, но и docs/tests

### Mini App maturity

- довести `frontend/miniapp-v0` до полностью опирающегося на текущие backend contracts production UI
- убрать неочевидные расхождения между static export и fallback serving

### Domain cleanup

- постепенно выносить крупные участки orchestration из `bot/main.py` и `bot/miniapp.py`
- удерживать alias compatibility, но сокращать количество legacy имен в пользовательском слое

### Observability

- улучшать операторские сигналы вокруг payment reconciliation, orphan webhooks и task watchdog flows

## 4. Что не стоит делать без отдельного проекта

- большой rewrite всей доменной модели
- отказ от backward compatibility по model ids / callbacks / links
- агрессивное удаление legacy assets без явного migration/rollback плана

## 5. Критерии актуальности roadmap

Roadmap нужно пересматривать, если меняется хотя бы одно из:

- набор моделей в `bot/keyboards.py` и `data/price.json`
- HTTP surface в `bot/main.py` / `bot/miniapp.py`
- storage path (`DATABASE_URL`, schema, migration scripts)
- payment providers
- Mini App export/serving strategy
