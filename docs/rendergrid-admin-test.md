# RenderGrid Telegram test branch

`feature/rendergrid-admin-test` — отдельная экспериментальная ветка для ручной проверки RenderGrid API прямо из Telegram-бота под админом. В `tanyapi` её мержить не нужно.

## Что появляется в боте

В существующей Telegram админ-панели добавляется кнопка:

```text
🧪 RenderGrid TEST
```

Дополнительно остаётся прямой админский вход `/rendergrid`.

Интерфейс повторяет обычный пользовательский сценарий генерации и не показывает технический JSON, API payload или Creation ID.

На основном экране можно:

- выбрать модель из актуального списка RenderGrid (`GET /models`);
- загрузить, заменить или удалить одно фото-референс;
- написать обычный текстовый промпт;
- выбрать соотношение сторон;
- выбрать качество либо оставить значение модели по умолчанию;
- нажать `🎨 Создать`;
- посмотреть баланс RenderGrid.

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

## Пользовательский поток

```text
/admin
  -> 🧪 RenderGrid TEST
  -> выбрать модель
  -> при необходимости добавить фото
  -> написать промпт
  -> выбрать формат / качество
  -> 🎨 Создать
  -> RenderGrid
  -> автоматическое ожидание результата
  -> готовое изображение приходит в Telegram
```

Фото загружается тем же Telegram helper, который используется основным image-generation flow: JPEG/PNG/WEBP скачивается из Telegram, валидируется и сохраняется как provider-safe reference URL.

Если фото не добавлено, выполняется text-to-image сценарий. Если фото добавлено, его URL автоматически добавляется в запрос как `image_urls`, и пользователь остаётся в том же понятном интерфейсе.

## Что происходит внутри

`bot/handlers/rendergrid_test_compat.py` собирает payload автоматически из выбранных настроек. Пользователь его не видит и не редактирует.

`bot/services/rendergrid_service.py` отвечает за:

- Bearer auth;
- `POST /images/generate`;
- `GET /creations/{id}`;
- `GET /models`;
- `GET /balance`;
- idempotency key;
- retry для `429` и временных `5xx`;
- `Retry-After`;
- polling не чаще одного раза в 5 секунд.

После запуска генерации creation id используется только внутренне. Бот сам дожидается `completed`/`failed`, извлекает `result_urls` и отправляет готовые изображения в Telegram.

## Проверка

```bash
python -m pytest tests/test_rendergrid_integration.py -q
```

Smoke flow:

1. открыть `/admin`;
2. нажать `🧪 RenderGrid TEST`;
3. открыть выбор модели и переключить модель;
4. добавить фото;
5. написать промпт;
6. при необходимости сменить формат и качество;
7. нажать `🎨 Создать`;
8. дождаться готового изображения в Telegram;
9. повторить без фото, чтобы проверить text-to-image.

Ветка предназначена только для теста провайдера и не должна становиться production-фичей автоматически.
