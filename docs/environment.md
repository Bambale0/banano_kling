# Переменные окружения NEUROMIX

Документ описывает группы env-переменных ветки `tanyapi`. Полный программный источник истины — `bot/config.py`.

## 1. Общие правила

- production `.env` хранится вне Git;
- права файла — `600`, владелец — пользователь systemd service или root;
- перед изменением создаётся backup;
- секреты нельзя печатать в issue, документацию, CI logs и shell screenshots;
- пустое значение не всегда равно выключенной функции: проверять код и feature flags;
- после изменения runtime-переменной обычно требуется restart `banano-kling.service`;
- frontend static build использует только переменные, начинающиеся с `NEXT_PUBLIC_`, и встраивает их на этапе сборки.

## 2. Рекомендуемый production skeleton

```dotenv
# Telegram
BOT_TOKEN=REPLACE_ME

# Public backend
WEBHOOK_HOST=https://tanyapi.chillcreative.ru
WEBHOOK_PATH=/webhook
WEBHOOK_BIND_HOST=127.0.0.1
WEBHOOK_PORT=1888

# Mini App
MINI_APP_PATH=/mini-app
MINI_APP_URL=https://cdn.chillcreative.ru/mini-app/
STATIC_BASE_URL=https://tanyapp.xn--e1aikcel5c5a.online

# Storage
DATABASE_URL=REPLACE_ME
REDIS_URL=redis://127.0.0.1:6379/0
REDIS_PREFIX=neuromix

# Security
INTERNAL_API_SECRET=REPLACE_ME
HEALTH_CHECK_SECRET=REPLACE_ME

# Providers and payments
KIE_AI_API_KEY=REPLACE_ME
PAYMENT_PROVIDER=REPLACE_ME

# Admin
ADMIN_IDS=123456789
```

Это шаблон, а не готовый `.env`: конкретный набор providers/payments зависит от включённого production-функционала.

## 3. Telegram

### `BOT_TOKEN`

Токен Telegram-бота. Обязателен для webhook, initData validation и Telegram API.

Никогда не использовать один token одновременно в двух активных production runtimes без понимания webhook/polling conflict.

### `ADMIN_IDS`

Список Telegram ID через запятую:

```dotenv
ADMIN_IDS=123456789,987654321
```

Пробелы допустимы только если parser их обрабатывает; безопаснее писать без пробелов.

## 4. Backend HTTP и webhook

### `WEBHOOK_HOST`

Публичная база backend:

```dotenv
WEBHOOK_HOST=https://tanyapi.chillcreative.ru
```

Без trailing slash.

### `WEBHOOK_PATH`

Telegram webhook path:

```dotenv
WEBHOOK_PATH=/webhook
```

Должен совпадать с Nginx route и установленным webhook Telegram.

### `WEBHOOK_BIND_HOST`

Рекомендуемое production-значение:

```dotenv
WEBHOOK_BIND_HOST=127.0.0.1
```

Frontend обращается к backend через `https://tanyapi.chillcreative.ru`, поэтому открывать aiohttp наружу не требуется.

### `WEBHOOK_PORT`

Локальный порт aiohttp:

```dotenv
WEBHOOK_PORT=1888
```

Если значение меняется, обновить backend Nginx upstream и health commands.

## 5. Mini App

### `MINI_APP_PATH`

Base path API/static fallback:

```dotenv
MINI_APP_PATH=/mini-app
```

Frontend export также собирается с `/mini-app` basePath.

### `MINI_APP_URL`

Публичный URL, который открывает Telegram:

```dotenv
MINI_APP_URL=https://cdn.chillcreative.ru/mini-app/
```

Trailing slash рекомендуется сохранить.

### `STATIC_BASE_URL`

Публичная база сохранённых uploads:

```dotenv
STATIC_BASE_URL=https://tanyapp.xn--e1aikcel5c5a.online
```

Backend формирует URLs вида:

```text
https://tanyapp.xn--e1aikcel5c5a.online/uploads/...
```

Не добавлять `/uploads` в значение, если код уже добавляет этот segment.

### `PERSIST_PROVIDER_RESULTS`

Включает сохранение provider result в локальное storage там, где поддерживается. Перед включением проверить disk capacity и cleanup policy.

Для image results с хостов из `DURABLE_IMAGE_RESULT_HOSTS` локализация выполняется всегда, даже если этот флаг выключен: такие provider URLs считаются временными и не должны попадать в повторную генерацию после истечения TTL.

### `DURABLE_IMAGE_RESULT_HOSTS`

Список хостов provider image results, которые backend обязан сразу зеркалить в durable storage. Значение по умолчанию:

```dotenv
DURABLE_IMAGE_RESULT_HOSTS=cdn.rendergrid.io
```

RenderGrid results нельзя использовать как долговременное хранилище: после завершения задачи backend должен сохранить собственную копию и записать локальный URL в `generation_tasks.result_url`. Каталог durable storage исключён из обычной 24-часовой очистки uploads.

### `FEED_EPHEMERAL_RESULT_HOSTS`

Публичная лента считает временными как минимум `tempfile.aiquickdraw.com` и `cdn.rendergrid.io`. Эти же хосты считаются ephemeral и в runtime-доставке provider results: готовый image/video result сначала принудительно локализуется в backend storage, даже если `PERSIST_PROVIDER_RESULTS=false`, и уже локальный URL сохраняется как канонический для recovery. Если локализация временно не удалась, исходный provider URL остаётся аварийным источником, а Telegram media delivery не должна считаться завершённой только из-за отправленной текстовой ссылки.

### `RENDERGRID_RESULT_TTL_HOURS`

Отдельный TTL для внешнего RenderGrid result URL. Значение по умолчанию:

```dotenv
RENDERGRID_RESULT_TTL_HOURS=24
```

После TTL `cdn.rendergrid.io` не отдаётся напрямую через feed/profile/history/task-detail/Mini App media: если durable-копии нет, generation возвращается как `media_unavailable`. Локальный `/uploads/feed/...` остаётся каноническим и TTL RenderGrid на него не распространяется.

### Legacy RenderGrid reconciliation

Production deploy после health-check запускает ограниченный reconciliation `scripts.backfill_rendergrid_image_results.py`. Он:

- выбирает только completed image rows, всё ещё указывающие на `cdn.rendergrid.io`;
- закрывает DB connection до сетевого скачивания;
- проверяет локальный durable-файл;
- делает compare-and-swap update по исходному `result_url`;
- пишет telemetry `scanned/localized/updated/skipped_race/failed/next_before_id/exhausted`;
- хранит cursor в persistent `/app/data/rendergrid-image-backfill-checkpoint.json`, поэтому следующий deploy продолжает проход, а не начинает с тех же failed rows.

Deploy-параметры ограниченного прохода:

```dotenv
RENDERGRID_DEPLOY_BACKFILL_LIMIT=50
RENDERGRID_DEPLOY_BACKFILL_CONCURRENCY=4
RENDERGRID_DEPLOY_BACKFILL_MAX_BATCHES=1
```

Ошибки legacy reconciliation не откатывают здоровый deploy: runtime resolver всё равно не публикует просроченный внешний RenderGrid URL.

## 6. Database

### `DATABASE_URL`

Формат зависит от выбранного backend.

SQLite example:

```dotenv
DATABASE_URL=sqlite:///bot.db
```

PostgreSQL example:

```dotenv
DATABASE_URL=postgresql://USER:PASSWORD@127.0.0.1:5432/DBNAME
```

Не копировать примерные credentials. Перед переключением использовать migration/verification scripts и документацию PostgreSQL.

## 7. Redis

### `REDIS_URL`

```dotenv
REDIS_URL=redis://127.0.0.1:6379/0
```

При недоступности Redis runtime может использовать in-memory fallback. Это ухудшает устойчивость FSM к restart.

### `REDIS_PREFIX`

Namespace keys:

```dotenv
REDIS_PREFIX=neuromix
```

При совместном Redis нескольких окружений использовать разные prefixes.

## 8. Security

### `INTERNAL_API_SECRET`

Секрет внутренних API. Должен быть длинным случайным значением.

### `HEALTH_CHECK_SECRET`

Если установлен, health route может требовать bearer token. Мониторинг нужно обновить одновременно.

### Provider webhook secrets

Возможные группы:

- `KIE_AI_WEBHOOK_SECRET`;
- `KIE_WEBHOOK_HMAC_KEY`;
- `REPLICATE_WEBHOOK_SECRET`;
- `LAVA_WEBHOOK_SECRET`;
- другие secrets, присутствующие в `bot/config.py`.

Наличие переменной не подтверждает включённый provider. Проверять route registration и active config.

## 9. Providers

Часто используемые ключи:

- `KIE_AI_API_KEY`;
- `KLING_API_KEY`;
- `PIAPI_API_KEY`;
- `GEMINI_API_KEY`;
- `NANOBANANA_API_KEY`;
- `FREEPIK_API_KEY`;
- `NOVITA_API_KEY`;
- `REPLICATE_API_TOKEN`;
- `HIGGSFIELD_API_KEY` (higgsfield.ai, формат `id:secret`);
- Nano Banana fallback keys/base URLs.

Правила:

- один ключ — одна строка без кавычек, если shell syntax их не требует;
- после ротации проверить и direct request, и webhook completion;
- не логировать request headers;
- fallback provider должен быть явно проверен, а не считаться рабочим из-за заполненной переменной.

### Higgsfield Genjutsu

Runtime variables:

- `HIGGSFIELD_API_KEY` — server credential `key_id:key_secret`;
- `HIGGSFIELD_API_BASE_URL` — default `https://api.higgsfield.ai`;
- `GENJUTSU_PUBLIC_BASE_URL` — public HTTPS origin for signed media and callback routes; production: `https://tanyapp.xn--e1aikcel5c5a.online`;
- `GENJUTSU_MEDIA_SIGNING_KEY` — high-entropy HMAC secret;
- `GENJUTSU_MEDIA_ROOT` — private durable storage, production default `/app/data/genjutsu_media`.

Публичная доступность, цены, лимиты и проверенные операции хранятся в управляемой DB-
конфигурации. На чистом запуске `public_enabled=false`, а все цены пусты: настроенные
секреты сами по себе не открывают платные запуски. Полный runbook: `docs/integrations/genjutsu/README.md`.

## 10. Payments

### `PAYMENT_PROVIDER`

Выбирает активный основной provider там, где это предусмотрено кодом.

Возможные группы конфигурации:

- CryptoBot: `CRYPTOBOT_*`;
- Lava: `LAVA_*`;
- Telegram Stars: `TELEGRAM_STARS_*`;
- FreeKassa: `FREEKASSA_*`;
- T-Bank legacy: `TBANK_*`.

В репозитории могут оставаться legacy integrations. Не включать provider только потому, что переменные существуют.

## 11. Partner programme

- `PARTNER_OFFER_URL`;
- `PARTNER_RULES_URL`;
- `PARTNER_MIN_WITHDRAWAL_RUB`.

Изменение minimum withdrawal должно быть согласовано с UI и business rules.

## 12. Logging

Возможные runtime flags:

```dotenv
BANANO_DISABLE_FILE_LOGGING=0
BANANO_LOG_TO_STDOUT=1
```

Технический prefix `BANANO_*` legacy и не является пользовательским брендом.

## 13. Frontend build variables

Frontend может использовать:

- `NEXT_EXPORT=1` — выставляется build script автоматически;
- `NEXT_PUBLIC_MINIAPP_BASE_PATH=/mini-app`;
- runtime/public bot username variables, если они поддерживаются `lib/api.ts`.

`NEXT_PUBLIC_*` не должны содержать secrets: они попадают в клиентский bundle.

## 14. Cloudflare deploy variables

Для `scripts/deploy_media_origin.sh`:

```text
DOMAIN=media.chillcreative.ru
ZONE_NAME=chillcreative.ru
ORIGIN_IPV4=144.76.188.75
PROJECT_DIR=/root/tanya/banano_kling
UPLOADS_DIR=/root/tanya/banano_kling/static/uploads
APP_SERVICE=banano-kling.service
CF_API_TOKEN_FILE=/root/.secrets/cloudflare-media.token
BACKFILL_WEBP=1
RUN_RENEWAL_DRY_RUN=1
```

Обычно они передаются окружением запуска и не обязаны находиться в application `.env`.

## 15. Безопасное изменение `.env`

```bash
cd /root/tanya/banano_kling

BACKUP="/root/backups/neuromix/env-$(date +%Y%m%d-%H%M%S)"
install -d -m 700 /root/backups/neuromix
cp -a .env "$BACKUP"
chmod 600 "$BACKUP"

nano .env

sudo systemctl restart banano-kling.service
sudo systemctl is-active banano-kling.service
curl -fsS http://127.0.0.1:1888/health
journalctl -u banano-kling.service -n 100 --no-pager
```

## 16. Проверка без раскрытия секретов

Показывать только имена заполненных переменных:

```bash
python3 - <<'PY'
from pathlib import Path

for line in Path('.env').read_text().splitlines():
    line = line.strip()
    if not line or line.startswith('#') or '=' not in line:
        continue
    key, value = line.split('=', 1)
    print(f'{key}: {"set" if value.strip() else "empty"}')
PY
```

Никогда не отправлять полный вывод `.env` в чат или issue.

### KIE result delivery recovery

| Variable | Default | Purpose |
| --- | --- | --- |
| `KIE_DELIVERY_LEASE_SECONDS` | `600` | Prevent duplicate KIE webhook/watchdog media delivery while one attempt is active; minimum 120 seconds |
| `EPHEMERAL_RESULT_PERSIST_ATTEMPTS` | `2` | Durable-localization attempts for ephemeral provider image/video results; range 1–4 |
| `EPHEMERAL_RESULT_PERSIST_RETRY_DELAY_SECONDS` | `1` | Linear delay between localization attempts; minimum 0 seconds |

For KIE results on hosts listed in `FEED_EPHEMERAL_RESULT_HOSTS`, the backend
tries to create a durable local copy before Telegram delivery. The canonical
result URL is stored in `generation_tasks.result_url` while the task remains
recoverable. A text/link fallback is recorded as `link_sent`, not
`delivered`; media failure returns the delivery state to `pending` so the
watchdog can retry after the lease expires. `completed` + `delivered` are
written only after Telegram actually accepts image/video media.

### Seedance 2.5 reliability

These settings control result transport and one-time edit-fallback coordination.
They do not change generation pricing:

| Variable | Default | Purpose |
| --- | --- | --- |
| `SEEDANCE25_RESULT_DOWNLOAD_ATTEMPTS` | `2` | Download attempts per delivery cycle, minimum 1 |
| `SEEDANCE25_RESULT_DOWNLOAD_TIMEOUT_SECONDS` | `120` | Timeout per download, minimum 30 seconds |
| `SEEDANCE25_RESULT_DOWNLOAD_RETRY_DELAY_SECONDS` | `1` | Linear retry delay in seconds, minimum 0 |
| `SEEDANCE25_DELIVERY_TIMEOUT_SECONDS` | `360` | Total delivery-attempt deadline, minimum 30 seconds; lease lasts 60 seconds longer |
| `SEEDANCE25_DELIVERY_RETRY_DAYS` | `7` | Recovery window after completion, range 1–30 days |
| `SEEDANCE25_EDIT_RETRY_CLAIM_TTL_SECONDS` | `300` | One-time edit fallback claim TTL, minimum 30 seconds; prevents duplicate provider launches |

A generated result is saved before Telegram delivery. `request_data.delivery_status`
tracks delivery separately: `delivering` holds a lease, `pending` needs retry,
`link_sent` records only a fallback link, `delivered` means media was sent, and
`unavailable` is terminal when Telegram reports `chat not found`, a blocked bot,
or a deactivated user. The stored result remains available in Mini App and no
automatic Telegram retry is scheduled for `unavailable`.
The nullable `users.telegram_chat_state` capability preserves existing users as
`unknown`, records newly created Mini App-only users as `unavailable`, and changes
to `available` after `/start`. Provider callbacks always persist and complete the
result first. If the chat is known unavailable, they then record terminal delivery
metadata (`chat_not_started`) without calling Telegram. A later `/start` enables
delivery for new tasks; it does not resend older results.
`delivery_link_sent` suppresses duplicate fallback links while file retries continue.
Completion and its result_ready marker are committed atomically. Legacy completed
tasks without markers are not automatically resent. Reconciliation
uses `completed_at` (or legacy `created_at`) for the retry window, so repeated
attempts cannot extend it indefinitely. After this window, the stored result remains
available but automatic file delivery stops; inspect provider URL availability and
Telegram errors before operator recovery. No automatic refund is issued for a
completed generation whose Telegram file delivery fails.
