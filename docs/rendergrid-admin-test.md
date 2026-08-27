# RenderGrid admin test client

Эта интеграция изолирована в `feature/rendergrid-admin-test` и не подключена к пользовательскому биллингу/генерационному flow NEUROMIX.

## Назначение

В Mini App у пользователей из `ADMIN_IDS` появляется вкладка **«Тест»**. Она позволяет напрямую проверить RenderGrid:

- состояние конфигурации;
- каталог доступных моделей;
- баланс RenderGrid;
- `POST /images/generate`;
- статус creation через `GET /creations/{id}`;
- итоговые `result_urls`;
- idempotency key;
- model-specific параметры через дополнительный JSON, включая поддерживаемые RenderGrid поля для resolution, reference images и `webhook_url`.

Обычный пользователь не видит вкладку. Backend повторно проверяет подписанный Telegram Mini App `initData` и `config.is_admin(telegram_id)`, поэтому скрытие кнопки не является единственной защитой.

## Environment

На backend добавить:

```dotenv
RENDERGRID_API_KEY=rg_live_REPLACE_ME
```

Опционально:

```dotenv
RENDERGRID_BASE_URL=https://api.rendergrid.io/api/public/v1
RENDERGRID_TIMEOUT_SECONDS=60
```

`RENDERGRID_API_KEY` является серверным секретом. Не добавлять его в `NEXT_PUBLIC_*`, frontend env, исходники или Mini App bundle.

## Поток

```text
Telegram Mini App admin
  -> /mini-app/api/admin/rendergrid/*
  -> Telegram initData validation
  -> ADMIN_IDS validation
  -> bot/services/rendergrid_service.py
  -> https://api.rendergrid.io/api/public/v1
```

Маршруты прокси регистрируются до generic `/mini-app/api/{tail:.*}` catch-all и используют существующий production proxy `/mini-app/api/*`.

## Backend API для тестового экрана

```text
GET  /mini-app/api/admin/rendergrid/health
GET  /mini-app/api/admin/rendergrid/models
GET  /mini-app/api/admin/rendergrid/balance
POST /mini-app/api/admin/rendergrid/images/generate
GET  /mini-app/api/admin/rendergrid/creations/{creation_id}
```

Каждый маршрут требует `X-Telegram-Init-Data` и admin Telegram ID.

## Polling и retry

RenderGrid возвращает generation request асинхронно. Клиент:

- считает `completed` и `failed` terminal status;
- не poll-ит creation чаще одного раза в 5 секунд;
- обрабатывает `429` и временные `5xx` с backoff;
- учитывает `Retry-After`, когда он присутствует;
- повторяет POST с тем же idempotency key, чтобы сетевой retry не создавал намеренно новый request.

Mini App использует 5.5 секунды между автоматическими status checks.

## Проверка перед использованием

Backend:

```bash
python -m pytest tests/test_rendergrid_integration.py -q
```

Frontend:

```bash
cd frontend/miniapp-v0
npm ci
npm run lint
npm run build
```

После настройки `RENDERGRID_API_KEY` открыть Mini App из Telegram под ID, входящим в `ADMIN_IDS`, открыть **«Тест»**, проверить `Ключ: подключён`, баланс/модели и выполнить одну тестовую generation.
