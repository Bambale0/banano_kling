# Run Guide

Pytest изолирован от production `.env`: `tests/conftest.py` запрещает загрузку project env и очищает уже экспортированные application settings до импорта `bot.config`. Тестовые значения задаются отдельно, поэтому локальный полный gate не должен использовать production API keys, базы, Redis или webhook settings.

## 1. Назначение

Этот файл описывает безопасный способ локально поднять проект и проверить, что документация, конфиг и runtime не расходятся.

## 2. Backend setup

```bash
python -m venv venv
. venv/bin/activate
pip install -r requirements.txt
```

Убедиться, что настроены:

- `.env`
- при необходимости `.env.postgres`

## 3. Запуск backend

```bash
. venv/bin/activate
python -m bot.main
```

Если нужен webhook-like режим за reverse proxy, подготовить:

- `WEBHOOK_HOST`
- `WEBHOOK_PATH`
- `WEBHOOK_PORT`
- `WEBHOOK_BIND_HOST`

## 4. Локальные проверки после старта

### HTTP

```bash
curl "http://127.0.0.1:${WEBHOOK_PORT:-8443}/health"
```

В текущем production `WEBHOOK_PORT=1888`; локальное значение по умолчанию в `bot/config.py` — `8443`.

### Imports / syntax

```bash
python -m py_compile $(find bot tests scripts -name "*.py")
```

### Tests

```bash
python -m pytest
```

## 5. Mini App frontend

### Development

```bash
cd frontend/miniapp-v0
npm install
npm run dev
```

### Static build

```bash
cd frontend/miniapp-v0
npm run build
```

Локально backend может отдавать export build через `bot/miniapp.py`. В production static export размещён отдельно на `tanyapp.chillcreative.ru`, а API проксируется на `tanyapi.chillcreative.ru`.

Production deploy, TLS, проверки перед переключением и rollback описаны в [miniapp-frontend-deployment.md](miniapp-frontend-deployment.md).

## 6. Что проверять вручную

### Telegram bot

- `/start`
- главное меню
- переход в image flow
- переход в video flow
- баланс
- top-up

### Mini App

- bootstrap
- upload
- generate image
- task detail
- feed/prompts/profile tabs

### Payments

- создание transaction
- webhook completion
- отсутствие двойного зачисления

## 7. Когда не стоит продолжать запуск

Остановиться и сначала чинить окружение, если:

- не читается `BOT_TOKEN`
- `/health` не поднимается
- Redis обязателен, но постоянно падает в fallback
- migration/runtime path неясен между SQLite и PostgreSQL
- webhook paths не совпадают с публичной конфигурацией
