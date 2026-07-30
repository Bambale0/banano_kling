# Banano Kling

`Banano Kling` — production-oriented Telegram bot + Telegram Mini App для генерации изображений и видео, prompt-assist сценариев, платежей, feed/prompt-library и внутреннего админского API.

Документация актуализирована по production-схеме на `2026-07-30`. Если описание ниже конфликтует с кодом, источником истины считаются `bot/`, `frontend/miniapp-v0/`, `tests/` и `data/price.json`.

## Что есть в проекте сейчас

- Telegram bot на `aiogram 3` с webhook runtime через `aiohttp`
- Telegram Mini App с backend в `bot/miniapp.py`
- Генерация изображений, видео, motion control, talking avatar, photo-to-prompt, video-to-prompt
- Feed, prompt library, remix/repeat/share сценарии
- Баланс в кредитах (`бананы`), promo codes, partner/referral flows
- Платёжные провайдеры: `CryptoBot`, `Lava`, `YooKassa`, `Telegram Stars`, legacy `T-Bank`
- Internal API:
  - `/internal/v1/*` для health/stats
  - `/internal/admin/*` для read-only admin aggregation
- SQLite-first слой с PostgreSQL runtime path через совместимый DB facade
- Redis для FSM/cache с fallback на in-memory storage
- Набор regression tests по webhook, платежам, Mini App, routing и DB helpers

## Ключевые пользовательские сценарии

- `Создать фото`
  - text-to-image
  - image edit / reference-based generation
  - batch presets
- `Создать видео`
  - text-to-video
  - image-to-video
  - video-reference generation
  - Veo / Grok / Seedance / Gemini Omni / Kling family
- `Motion Control`
  - фото персонажа + motion video
- `Prompt по фото`
  - анализ изображения и подготовка текстового описания
- `Prompt по видео`
  - анализ видео в отдельный credit-based flow
- `Mini App`
  - bootstrap профиля и задач
  - генерация
  - upload
  - feed/prompt actions
  - profile/referral/share links
- `Баланс и партнёрка`
  - пополнение
  - promo code
  - реферальные начисления
  - partner balance / withdrawals / exchange

## Актуальный стек

- Backend: Python 3, `aiogram`, `aiohttp`
- Storage:
  - SQLite для local-first / legacy compatibility
  - PostgreSQL path через `DATABASE_URL`
  - Redis для FSM/cache
- Frontend:
  - Mini App backend в Python runtime
  - `frontend/miniapp-v0` на `Next.js 16`, React 19, Tailwind 4
  - production static frontend отдельно на `tanyapp.chillcreative.ru`, API на `tanyapi.chillcreative.ru`
- Integrations:
  - Kie / Kie Market
  - Kling / Replicate-style callbacks
  - Grok, Veo, Seedream, Seedance, Wan 2.7, Nano Banana family
  - CryptoBot, Lava, YooKassa, Telegram Stars

## Актуальные модели и семейства

### Изображения

- `banana_pro` / `nano-banana-pro`
- `banana_2`
- `nano-banana-2-lite`
- `seedream_edit`
- `seedream_5_pro`
- `flux_pro`
- `grok_imagine_i2i`
- `wan_27`

### Видео

- `v3_pro`
- `v3_std`
- `v26_pro`
- `motion_control_v26`
- `grok_imagine`
- `grok_imagine_v15`
- `seedance_2`
- `veo3`
- `veo3_fast`
- `veo3_lite`
- `gemini_omni_video`
- `gemini_omni_audio`
- `gemini_omni_character`
- `glow`
- `avatar_std`
- `avatar_pro`

Источники истины по labels/costs/options:

- `bot/keyboards.py`
- `bot/services/preset_manager.py`
- `data/price.json`

## Runtime surface

### Основные HTTP endpoints

- Telegram webhook: `config.WEBHOOK_PATH` (`/webhook` по умолчанию)
- CryptoBot webhook: `config.CRYPTOBOT_WEBHOOK_PATH`
- Lava webhook: `config.LAVA_WEBHOOK_PATH`
- YooKassa webhook:
  - `/yookassa/webhook`
  - `/webhook/yookassa`
- Kling/Replicate-style webhook: `/webhook/kling`
- Kie AI webhook: `config.KIE_AI_WEBHOOK_PATH`
- Kie Market webhook relay: `config.KIE_MARKET_WEBHOOK_PATH`
- Health: `/health`

### Internal API

- `/internal/v1/health`
- `/internal/v1/stats`
- `/internal/admin/health`
- `/internal/admin/summary`
- `/internal/admin/users`
- `/internal/admin/generations`
- `/internal/admin/finance`

### Mini App

Base path: `config.MINI_APP_PATH` (`/mini-app` по умолчанию)

Основные endpoints:

- `POST /mini-app/api/bootstrap`
- `POST /mini-app/api/action`
- `POST /mini-app/api/upload`
- `POST /mini-app/api/generate-image`
- `POST /mini-app/api/generate-video`
- `POST /mini-app/api/generate-motion`
- `POST /mini-app/api/photo-to-prompt`
- `POST /mini-app/api/task-detail`
- `POST /mini-app/api/create-payment`
- `POST /mini-app/api/ai-assistant`
- prompt/feed/profile endpoints under `/mini-app/api/*`
- public API mirror under `/mini-app/api/v1/*` for selected feed/prompt routes

Подробности: [docs/architecture.md](docs/architecture.md), [docs/tracemap.md](docs/tracemap.md). Production deploy и rollback frontend: [docs/miniapp-frontend-deployment.md](docs/miniapp-frontend-deployment.md).

## Структура репозитория

```text
.
├── bot/
│   ├── main.py
│   ├── miniapp.py
│   ├── config.py
│   ├── database.py
│   ├── db.py
│   ├── handlers/
│   ├── services/
│   ├── utils/
│   └── internal_*.py
├── data/
│   └── price.json
├── docs/
├── frontend/miniapp-v0/
├── scripts/
├── tests/
├── tracemap_*.md
└── schema_postgres.sql
```

## Конфигурация

Основные группы env-переменных задаются в `bot/config.py`:

- Telegram:
  - `BOT_TOKEN`
  - `WEBHOOK_HOST`
  - `WEBHOOK_PATH`
  - `WEBHOOK_BIND_HOST`
  - `WEBHOOK_PORT`
- Mini App:
  - `MINI_APP_PATH`
  - `MINI_APP_URL`
  - `STATIC_BASE_URL`
- DB/Cache:
  - `DATABASE_URL`
  - `REDIS_URL`
  - `REDIS_PREFIX`
- Internal/security:
  - `INTERNAL_API_SECRET`
  - `HEALTH_CHECK_SECRET`
  - `KIE_AI_WEBHOOK_SECRET`
  - `KIE_WEBHOOK_HMAC_KEY`
  - `YOOKASSA_WEBHOOK_SECRET`
  - `LAVA_WEBHOOK_SECRET`
- Payments:
  - `PAYMENT_PROVIDER`
  - `CRYPTOBOT_*`
  - `LAVA_*`
  - `YOOKASSA_*`
  - `TBANK_*`
- Providers:
  - `KIE_AI_API_KEY`
  - `KLING_API_KEY`
  - `PIAPI_API_KEY`
  - `GEMINI_API_KEY`
  - `NANOBANANA_API_KEY`
  - fallback API keys for Nano Banana families

## Быстрый запуск

### Backend

```bash
python -m venv venv
. venv/bin/activate
pip install -r requirements.txt
python -m bot.main
```

### Тесты

```bash
python -m pytest
python -m py_compile $(find bot tests scripts -name "*.py")
```

### Mini App frontend

```bash
cd frontend/miniapp-v0
npm install
npm run build
```

`bot/miniapp.py` умеет отдавать:

1. static export из `frontend/miniapp-v0/out`
2. alternative build dir
3. fallback assets, если export не собран

## Документация

- [docs/README.md](docs/README.md) — карта документации
- [docs/architecture.md](docs/architecture.md) — актуальная архитектура
- [docs/roadmap.md](docs/roadmap.md) — статус и ближайшие приоритеты
- [docs/tracemap.md](docs/tracemap.md) — индексы по основным потокам
- [docs/runbook.md](docs/runbook.md) — эксплуатация и инциденты
- [docs/run_guide.md](docs/run_guide.md) — локальный запуск и dev-проверки
- [docs/postgres-migration.md](docs/postgres-migration.md) — Postgres runtime path
- [docs/migration.md](docs/migration.md) — миграции, backfill и data repair scripts

## Ограничения и фактический статус

- Документация по provider APIs в `docs/*.md` частично хранится как reference snapshots; для интеграционной правды важнее сервисы и тесты.
- В репозитории есть legacy/backup файлы (`*.bak`, старые DB dumps, старые docs). Они не считаются источником истины для текущего runtime.
- Некоторые сценарии описывают и Telegram bot, и Mini App одновременно; точная привязка по экрану/route расписана в tracemap.
