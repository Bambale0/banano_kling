# RenderGrid Telegram test branch

`feature/rendergrid-admin-test` — отдельная экспериментальная ветка. Её назначение: руками проверить RenderGrid API прямо из Telegram-бота под админом. В `tanyapi` её мержить не нужно.

## Что появляется в боте

В существующей Telegram админ-панели добавляется кнопка:

```text
🧪 RenderGrid TEST
```

Она видна только внутри админского контура, а каждый callback дополнительно проверяет `config.is_admin(user_id)`.

После открытия доступны:

- `💰 Баланс` — прямой `GET /balance`;
- `📦 Модели` — прямой `GET /models`;
- `⚡ Генерация` — отправка произвольного JSON в `POST /images/generate`;
- `🔎 Creation ID` — ручная проверка `GET /creations/{id}`;
- `🔄 Проверить статус` — повторная проверка последнего creation.

Никакие бананы, пользовательский биллинг, история генераций и Mini App не используются.

## Environment

На backend тестового запуска:

```dotenv
RENDERGRID_API_KEY=rg_live_REPLACE_ME
```

Опционально:

```dotenv
RENDERGRID_BASE_URL=https://api.rendergrid.io/api/public/v1
RENDERGRID_TIMEOUT_SECONDS=60
```

Ключ остаётся только на backend.

## Поток

```text
Telegram admin
  -> Админ-панель
  -> 🧪 RenderGrid TEST
  -> bot/handlers/rendergrid_test_compat.py
  -> bot/services/rendergrid_service.py
  -> https://api.rendergrid.io/api/public/v1
```

## Генерация

Бот просит прислать JSON одним сообщением. Например:

```json
{
  "model": "MODEL_FROM_RENDERGRID",
  "prompt": "A cinematic portrait of a red fox",
  "aspect_ratio": "1:1"
}
```

JSON передаётся в RenderGrid как есть. Клиент проверяет только обязательные `model` и `prompt`, добавляет `Idempotency-Key` и возвращает сырой ответ API в Telegram.

Если ответ содержит creation id, бот сохраняет его в FSM и показывает кнопку повторной проверки статуса.

## Клиент

`bot/services/rendergrid_service.py` содержит изолированный async client:

- Bearer auth;
- `POST /images/generate`;
- `GET /creations/{id}`;
- `GET /models`;
- `GET /balance`;
- idempotency key;
- retry для `429` и временных `5xx`;
- `Retry-After`;
- polling не чаще одного раза в 5 секунд;
- URL-encoding creation id как одного path segment.

## Проверка

```bash
python -m pytest tests/test_rendergrid_integration.py -q
```

После запуска тестовой ветки с `RENDERGRID_API_KEY`:

1. открыть Telegram админ-панель;
2. нажать `🧪 RenderGrid TEST`;
3. проверить баланс;
4. открыть список моделей;
5. взять реальный model id;
6. отправить тестовый JSON генерации;
7. проверить creation до `completed`/`failed`;
8. посмотреть сырой ответ и `result_urls`.

Ветка предназначена только для ручного теста провайдера и не должна становиться production-фичей автоматически.
