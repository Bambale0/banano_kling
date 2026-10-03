# Higgsfield Genjutsu: официальный API-контракт и gap-анализ ветки

Дата проверки: 2026-10-03.

## Краткий вывод

В официальном API Genjutsu представлен тремя самостоятельными workflow:

| Workflow | Production endpoint ID |
| --- | --- |
| Motion transfer | `higgsfield/genjutsu/motion-transfer/v1.0` |
| Object swap | `higgsfield/genjutsu/object-swap/v1.0` |
| Restyle | `higgsfield/genjutsu/restyle/v1.0` |

Источник: [официальный обзор Genjutsu API](https://docs.higgsfield.ai/docs/models/genjutsu.md).

Текущий `bot/services/higgsfield_provider.py` — общий асинхронный транспорт для
Higgsfield, но его публичные builders и регистрация в `bot/config.py` /
`bot/services/__init__.py` реализуют Seedance 2.5 (`text-to-video`,
`image-to-video`, `reference-to-video`), а не Genjutsu. Поэтому состояние ветки
нельзя считать полноценной интеграцией Genjutsu.

## Приоритет источников

Официальный индекс документации требует считать model-specific документацию
источником истины для endpoint и schema, общую документацию использовать для
auth/lifecycle/webhooks/errors, а `openapi.json` — лишь дополнительным
источником. Отсутствие модели в OpenAPI не доказывает её недоступность. Источник:
[официальный индекс документации](https://docs.higgsfield.ai/docs/llms.txt).

В исследовании использованы только первичные источники Higgsfield:

- [страница продукта Genjutsu](https://higgsfield.ai/genjutsu);
- [обзор Genjutsu API](https://docs.higgsfield.ai/docs/models/genjutsu.md);
- [Motion transfer API](https://docs.higgsfield.ai/docs/models/genjutsu/motion-transfer.md);
- [Object swap API](https://docs.higgsfield.ai/docs/models/genjutsu/object-swap.md);
- [Restyle API](https://docs.higgsfield.ai/docs/models/genjutsu/restyle.md);
- общие официальные документы, перечисленные по разделам ниже;
- [официальный Python SDK](https://github.com/higgsfield-ai/higgsfield-client) и
  [официальный TypeScript SDK](https://github.com/higgsfield-ai/higgsfield-js).

## Endpoint и авторизация

Base URL: `https://api.higgsfield.ai`.

Новые интеграции должны использовать пути с корректным namespace
`higgsfield/...`:

```text
POST /higgsfield/genjutsu/motion-transfer/v1.0
POST /higgsfield/genjutsu/object-swap/v1.0
POST /higgsfield/genjutsu/restyle/v1.0
```

В старых страницах Playground встречается опечатанный namespace
`higgsfiled/...`. Актуальные model-specific документы прямо называют его
legacy endpoint, который пока остаётся callable, но скрыт из discovery. Для
новой интеграции его использовать нельзя. Источники:
[Motion transfer](https://docs.higgsfield.ai/docs/models/genjutsu/motion-transfer.md),
[Object swap](https://docs.higgsfield.ai/docs/models/genjutsu/object-swap.md).

Авторизация:

```http
Authorization: Key YOUR_KEY_ID:YOUR_KEY_SECRET
Content-Type: application/json
```

Legacy-заголовки `hf-api-key` и `hf-secret` ещё принимаются, но для новых
интеграций рекомендован `Authorization`. Credential должен оставаться только
на backend. Источник: [Authentication](https://docs.higgsfield.ai/docs/authentication.md).

## Model-specific request schema

### Motion transfer

`POST /higgsfield/genjutsu/motion-transfer/v1.0`

| Поле | Обязательность | Контракт |
| --- | --- | --- |
| `video_url` | да | public URI, строка 1..2083 символов |
| `image_urls` | да | массив из 1..8 public image URI; порядок значим |
| `prompt` | нет | string, default `""`, максимум 10 000 символов |
| `resolution` | нет | `480p`, `720p` или `1080p`; default `720p` |

Source video должен быть не короче 4 секунд. Первые 30 секунд используются у
более длинного видео; output duration следует подготовленному source video.
`additionalProperties: false`, то есть других model inputs endpoint не
принимает. Источник: [Motion transfer API](https://docs.higgsfield.ai/docs/models/genjutsu/motion-transfer.md).

### Object swap

`POST /higgsfield/genjutsu/object-swap/v1.0`

Schema совпадает с Motion transfer: обязательные `video_url` и `image_urls`
(1..8), опциональные `prompt` (до 10 000 символов, default `""`) и
`resolution` (`480p`/`720p`/`1080p`, default `720p`),
`additionalProperties: false`.

Дополнительное ограничение: source video должен содержать не менее 409 600
пикселей в каждом кадре (`width × height`). Duration: минимум 4 секунды,
видео длиннее 30 секунд обрезается до первых 30 секунд. Источник:
[Object swap API](https://docs.higgsfield.ai/docs/models/genjutsu/object-swap.md).

### Restyle

`POST /higgsfield/genjutsu/restyle/v1.0`

| Поле | Обязательность | Контракт |
| --- | --- | --- |
| `video_url` | да | напрямую скачиваемый public/signed URI; минимум 4 секунды; максимум 200 MiB; первые 30 секунд длинного файла |
| `preset_id` | да | UUID из актуального списка presets |
| `image_urls` | нет | 0..5 character image URI; default `[]`; максимум 64 MiB на изображение |
| `prompt` | нет | string, default `""`, максимум 10 000 символов |
| `resolution` | нет | `480p`, `720p` или `1080p`; default `720p` |

`null` для optional-полей не поддержан; их нужно опустить либо передать
документированные empty/default значения. Restyle сохраняет source audio, но
не даёт управления soundtrack. Output framing берётся из source; точные
duration/FPS могут отличаться от source в зависимости от preset.

Preset нельзя хардкодить как постоянный каталог. Его нужно получать перед
выбором:

```text
GET /models/higgsfield/genjutsu/restyle/v1.0/presets
```

Ответ: `{ "model": ..., "items": [{ "id": UUID, "name": string,
"preview_url": URL }] }`. Используется именно `items[].id`; name, позиция и
preview URL не являются идентификатором. Каталог может изменяться; исчезнувший
saved preset требует refresh и нового выбора. Источник:
[Restyle API](https://docs.higgsfield.ai/docs/models/genjutsu/restyle.md).

### Что не является входным параметром Genjutsu

Model-specific JSON schemas не содержат `duration`, `aspect_ratio`, `fps`,
`seed`, `output_format`, `bitrate_mode`, `generate_audio`, batch size или
provider selection. Duration определяется source video, framing/aspect ratio —
source framing. Особенно явно это зафиксировано для
[Restyle](https://docs.higgsfield.ai/docs/models/genjutsu/restyle.md); schemas
Motion transfer и Object swap также закрыты через `additionalProperties: false`.

## Media input и upload

Model endpoints принимают URL, доступные серверам Higgsfield без browser
cookies и custom authentication headers. Для локальных файлов официальный API
предлагает:

1. `POST /files/generate-upload-url` с `{"content_type": ...}`;
2. `PUT` файла в выданный `upload_url` со всеми `upload_headers`;
3. передачу выданного `public_url` в model request.

Presigned upload URL истекает через один час. Документированы типы
`image/jpeg`, `image/jpg`, `image/png`, `image/webp`, `image/gif`,
`audio/wav`, `audio/x-wav`, `video/mp4`. API credentials нельзя отправлять на
storage URL. Источник: [File uploads](https://docs.higgsfield.ai/docs/concepts/file-uploads.md).

## Submit response, polling и result

Generation асинхронна. Принятый submit возвращает handle, а не видео:

```json
{
  "status": "queued",
  "request_id": "REQUEST_ID",
  "status_url": "https://api.higgsfield.ai/requests/REQUEST_ID/status",
  "cancel_url": "https://api.higgsfield.ai/requests/REQUEST_ID/cancel"
}
```

Документация требует сохранять `request_id` сразу и использовать выданные URL,
не конструируя их вручную. Статусы:

| Status | Terminal | Значение |
| --- | :-: | --- |
| `queued` | нет | ожидает запуска, ещё можно отменить |
| `in_progress` | нет | выполняется, отмена уже невозможна |
| `completed` | да | output доступен |
| `failed` | да | failure, может содержать `error` |
| `nsfw` | да | отклонён moderation |
| `canceled` | да | отменён до начала обработки |

Успешный Genjutsu result находится в `video.url`. Output URL доступен минимум
семь дней и затем может быть удалён, поэтому результат нужно копировать в своё
хранилище. Источники:
[Requests and lifecycle](https://docs.higgsfield.ai/docs/concepts/requests.md),
[Billing and retention](https://docs.higgsfield.ai/docs/concepts/billing-and-retention.md).

Рекомендуемый polling: начать с 2 секунд, увеличивать интервал в 1.5 раза до
10 секунд, добавить jitter, остановиться на terminal status и иметь общий
application timeout. `GET` status повторяется при network failure/`5xx`, но
не при `401`/`404`. Источник: [Polling](https://docs.higgsfield.ai/docs/concepts/polling.md).

Cancel: `POST /requests/{request_id}/cancel`; успех — `202` с пустым body.
После начала обработки возвращается `400`. Источник:
[Requests and lifecycle](https://docs.higgsfield.ai/docs/concepts/requests.md).

## Idempotency

Каждый generation submit должен иметь `Idempotency-Key`. Правила:

- 1..255 visible ASCII characters без whitespace; UUID рекомендован;
- один key обозначает один generation intent в пределах account;
- при ambiguous timeout/network failure/`5xx` повторяется тот же endpoint,
  body и webhook с тем же key;
- изменение endpoint/body/webhook при том же key возвращает `422`;
- порядок JSON object fields не важен, но array order, omitted fields,
  explicit `null` и URL важны;
- terminal request сохраняет identity: replay не запускает generation заново;
- rejection до acceptance (auth/validation) key не потребляет.

Источник: [Idempotent requests](https://docs.higgsfield.ai/docs/concepts/idempotency.md).

## Webhooks

Webhook передаётся query parameter `hf_webhook` в submit URL. Endpoint должен
быть публичным HTTPS, принимать JSON и отвечать не дольше 10 секунд. Delivery
приходит для `completed`, `failed` и `nsfw` (официальный документ не обещает
delivery для `canceled`). Video success envelope:

```json
{
  "request_id": "...",
  "status": "completed",
  "error": null,
  "payload": {
    "video": {
      "url": "https://.../generated.mp4",
      "content_type": "video/mp4"
    }
  }
}
```

Receiver должен сначала durable-записать событие, затем ответить `2xx`.
Network/`5xx` delivery повторяется до двух часов; `4xx` не повторяется.
Duplicates допустимы, dedup key — `(request_id, terminal status)`. Polling
остаётся recovery path.

Критичный пробел официального публичного контракта: документ не описывает
подпись webhook, shared secret, timestamp/replay window или способ
криптографической верификации sender. Поэтому webhook нельзя считать
аутентифицированным только по наличию полей в body; итоговый status/result
следует подтверждать через authenticated status API, пока Higgsfield не
предоставит отдельный verified signing contract. Источник:
[Webhooks](https://docs.higgsfield.ai/docs/how-to/webhooks.md).

## Errors, retries, billing и limits

| HTTP status | Официальная семантика | Retry |
| --- | --- | --- |
| `400` | invalid input либо достигнут concurrency limit | только после исправления или ожидания |
| `401` | invalid/missing credentials | нет |
| `403` | недостаточно credits | после пополнения |
| `404` | request/model недоступен этому account | нет |
| `422` | validation или idempotency mismatch | нет |
| `423` | model временно blocked | позже |
| `500` | unexpected server error | да, backoff |
| `503` | model disabled/not ready | позже |

`failed` и `nsfw` не тарифицируются; reserved credits возвращаются. Успешно
отменённый queued request также refunded. Каждый API response содержит
`X-Correlation-ID`; его нужно сохранять рядом с `request_id`.

Account/model limits доступны только в Console. Основное ограничение — число
одновременно queued/processing requests. При достижении concurrency API сейчас
возвращает `400` без стандартных rate-limit headers и без `Retry-After`.
Источники: [Errors and retries](https://docs.higgsfield.ai/docs/concepts/errors.md),
[Rate limits](https://docs.higgsfield.ai/docs/concepts/rate-limits.md),
[Billing and retention](https://docs.higgsfield.ai/docs/concepts/billing-and-retention.md).

Restyle публикует ориентировочную стоимость за секунду source video:
`$0.318` для 480p, `$0.681` для 720p, `$1.632` для 1080p; duration для billing
округляется вверх после обрезки до 30 секунд. Это не точная quote. Для
production pricing авторитетен estimate для конкретного authenticated account,
а не hardcoded price. Источник: [Restyle API](https://docs.higgsfield.ai/docs/models/genjutsu/restyle.md)
и [Billing and retention](https://docs.higgsfield.ai/docs/concepts/billing-and-retention.md).

## SDK

Официально доступны:

- Python 3.8+: `pip install higgsfield-client`, sync и async API;
- Node.js/TypeScript: `npm install @higgsfield/client`, server-side v2 API.

SDK умеют submit/subscribe, polling, cancellation и upload. Для Genjutsu в
официальных model docs приведены вызовы `subscribe`/`subscribe_async` с теми же
production endpoint IDs, поэтому отдельный Genjutsu SDK не нужен. Источник:
[Client libraries](https://docs.higgsfield.ai/docs/how-to/sdk.md).

## UI-продукт и public API: важное различие

Продуктовая страница описывает два пользовательских режима — Motion Transfer и
Object Swap — и заявляет source video 4..30 секунд и до 30 reference images.
Однако authoritative public API schemas допускают только 1..8 images для этих
двух endpoints, а Restyle — 0..5. Это не следует объединять в один лимит:
UI capability не доказывает, что API принимает 30 images. Источники:
[страница продукта](https://higgsfield.ai/genjutsu),
[Motion transfer API](https://docs.higgsfield.ai/docs/models/genjutsu/motion-transfer.md),
[Object swap API](https://docs.higgsfield.ai/docs/models/genjutsu/object-swap.md),
[Restyle API](https://docs.higgsfield.ai/docs/models/genjutsu/restyle.md).

## Сопоставление с текущей веткой

### Что уже можно переиспользовать

- `HiggsfieldVideoProvider` отправляет `POST /{model_path}` на правильный base
  URL и использует правильный `Authorization: Key id:secret`.
- На submit генерируется и сохраняется в рамках retries один
  `Idempotency-Key`.
- Общие terminal statuses, polling 2s → ×1.5 → 10s с jitter, status retry для
  network/`5xx`, cancel `202` и извлечение `video.url` совпадают с общим
  контрактом.
- Generic `model_path` позволяет создать отдельные provider instances для
  Genjutsu без переписывания HTTP transport.

### Что отсутствует или несовместимо

1. Нет Genjutsu model IDs/config entries/registration. Зарегистрированы только
   три Seedance 2.5 workflow.
2. Нет Genjutsu builders. Текущие builders формируют поля `duration`,
   `aspect_ratio`, `output_format`, `bitrate_mode`, `generate_audio`,
   `video_urls`, `audio_urls`, которые запрещены Genjutsu schemas.
3. Текущий `reference-to-video` допускает до 30 images и прочие reference
   types; Genjutsu Motion/Object требуют именно 1..8 `image_urls` и один
   `video_url`.
4. Нет Restyle preset discovery/cache/refresh и обработки исчезнувшего preset.
5. Нет upload flow через `/files/generate-upload-url`, поэтому Telegram uploads
   нельзя безопасно превратить в public Genjutsu input без отдельного шага.
6. Нет webhook submit/query support и receiver с durable dedup/reconciliation.
7. `wait_for_completion(status_url=...)` фактически вызывает status по
   вручную собранному URL; provider-issued `status_url` используется только в
   timeout log, хотя документация требует использовать returned URL.
8. `X-Correlation-ID` не сохраняется и не прокидывается в telemetry.
9. Retry taxonomy не моделирует отдельно `423`, temporary `503` и `400`
   concurrency; вызывающий код получает в основном `None`, теряя причину и
   возможность корректного later retry/refund decision.
10. Нет проверки model-specific URI length, prompt length, reference count,
    Object Swap minimum pixels, source duration/size и Restyle `preset_id` UUID.
11. Нет пользовательского подключения: Telegram FSM, Mini App contract,
    catalog/model capabilities, цены/estimate, balance/refund, repeat,
    persistent task state, result storage и production telemetry не используют
    этот adapter.

### Неподтверждённые предположения, которые нельзя хардкодить

- Конкретные account concurrency limits и доступ аккаунта к каждой Genjutsu
  модели — проверяются только в Console/реальным authenticated request.
- Exact cost Motion Transfer/Object Swap и скидки account; нужно использовать
  estimate/Console, а не рекламную цену.
- Максимальный download size video/images для Motion Transfer и Object Swap:
  их model-specific страницы его не задают. Нельзя переносить лимиты Restyle
  (200 MiB/64 MiB) на другие endpoints без подтверждения.
- Поддерживаемые image/video codecs сверх общего upload списка.
- Output FPS, exact dimensions, aspect-ratio conversion и точность сохранения
  source audio для Motion Transfer/Object Swap.
- Webhook authenticity/signature: публичный официальный signing contract не
  найден.
- SLA/обычное и максимальное время generation: нужен configurable application
  timeout и наблюдение по production telemetry.
- Доступность legacy `higgsfiled/...` в будущем: документы гарантируют лишь
  текущую совместимость, поэтому на него нельзя строить новую интеграцию.

## Минимальный целевой контракт полной интеграции

1. Три явных workflow с production IDs и отдельными schema builders.
2. Dynamic Restyle presets через authenticated endpoint, без hardcoded UUID.
3. Public/signed media URL либо официальный upload flow с сохранением срока
   действия URL на время ingest.
4. Persistent `request_id`, `status_url`, `cancel_url`, idempotency key,
   workflow/model, `X-Correlation-ID`, input asset IDs и terminal payload.
5. Polling recovery и, при использовании webhook, durable idempotent receiver с
   обязательной authenticated status reconciliation.
6. Configurable timeout/concurrency/retry; явные error categories для auth,
   credits, validation, throttling/model unavailable, moderation и provider
   failure.
7. Estimate-backed pricing и транзакционно идемпотентные charge/refund rules.
8. Хранение completed video вне Higgsfield до истечения семидневного окна.
9. Единые Telegram и Mini App validation/UI rules: source video, 1..8 images
   для Motion/Object, 0..5 + current preset для Restyle, resolution enum.
10. Contract tests для exact body/endpoint/auth/idempotency, terminal states,
    duplicate webhook, ambiguous submit retry, preset refresh, upload headers,
    moderation/refund и expiration-safe result transfer.
