# Banano Kling AI Bot

Telegram-бот на Aiogram 3.x для генерации изображений и видео через несколько AI-провайдеров, с балансом в "бананах", оплатами, промокодами, партнерской программой, админ-панелью и webhook-интеграциями.

## Что умеет бот

- Генерация изображений: Banana Pro, Banana 2, GPT Image 2, Grok Imagine, Seedream 4.5/5 Lite/Edit, Ideogram Character.
- Генерация видео: Gemini Omni, Kling 3 Std/Pro, Seedance 2.0, Runway, Grok Imagine, Veo 3.1, Hailuo, HappyHorse, Wan 2.7.
- Сценарии: текст -> фото, фото + текст -> фото, текст -> видео, фото + текст -> видео, видео + текст -> видео.
- Motion Control: фото персонажа + видео движения.
- Референсы: фото-референсы и видео-референсы в поддерживаемых сценариях.
- Фото -> промпт и улучшение промпта через GPT 5.5.
- Gemini Omni как отдельный мультимодальный сценарий.
- Баланс в бананах, пополнение через T-Bank и Crypto Bot.
- Промокоды со скидками и лимитом использований.
- Партнерская программа: ссылка, начисления в рублях, выплаты через Jump Finance, перевод партнерского заработка в бананы.
- Админ-панель: статистика, пользователи, баланс, промокоды, цены, рассылка, бан/разбан, техрежим.

## Текущий стек

- Python 3.10+.
- Aiogram 3.x.
- Aiohttp server для Telegram/payment/provider webhooks.
- SQLite через `aiosqlite`; есть черновой план миграции на PostgreSQL.
- Redis опционально для idempotency/locks/rate-limit через `bot.services.reliability`.
- Systemd в production: `bot.service`, `bot-reloader.service`, watchdog.
- Конфигурация через `.env` и `bot/config.py`.

## Быстрый запуск

```bash
cd /root/bot/banano_kling
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp env.example .env
python -m bot.main
```

Если `WEBHOOK_HOST` пустой, бот стартует в polling mode. Если `WEBHOOK_HOST` задан, запускается aiohttp webhook server на `WEBHOOK_BIND_HOST:WEBHOOK_PORT`.

Локальный скрипт:

```bash
./start.sh
./stop.sh
```

Production через systemd:

```bash
systemctl status bot.service --no-pager -l
systemctl restart bot.service
systemctl status bot-reloader.service --no-pager -l
journalctl -u bot.service -n 100 --no-pager
```

После изменения unit-файлов:

```bash
systemctl daemon-reload
systemctl restart bot.service
```

## Systemd

Основной установленный unit: `/etc/systemd/system/bot.service`.

Он:

- читает `/root/bot/banano_kling/.env` через `EnvironmentFile`;
- запускает `/root/bot/banano_kling/scripts/run_bot_foreground.sh`;
- пишет stdout/stderr в `logs/bot_output.log`;
- работает из `/root/bot/banano_kling`;
- перезапускается автоматически.

Дополнительно:

- `bot-reloader.service` следит за кодом и `.env`, затем перезапускает `bot.service`;
- `banano-kling-watchdog.service`/watchdog-скрипты проверяют доступность health endpoint;
- подробности в [docs/watchdog.md](docs/watchdog.md).

## Структура проекта

```text
bot/
  main.py                 aiohttp server, Telegram dispatcher, provider webhooks
  config.py               env-конфиг и derived URLs
  database.py             SQLite schema, migrations, users, balance, payments, partner logic
  states.py               Aiogram FSM states
  keyboards.py            Inline-клавиатуры
  image_models.py         конфиги image-моделей и опций
  video_models.py         конфиги video-моделей и опций
  handlers/
    common.py             /start, меню, баланс, партнерка, GPT 5.5, Motion Control
    generation.py         основные image/video flows
    batch_generation.py   batch/edit flows
    image_analyzer.py     фото -> промпт
    payments.py           T-Bank/Crypto Bot платежи
    admin.py              админ-панель
  services/
    *_service.py          интеграции с AI/payment/storage/reliability
  utils/                  тексты помощи, валидаторы, инструкции ассистента
data/
  price.json              пакеты бананов, цены генераций, admin_ids fallback
  runway_characters.json  локальный storage для Runway character ids
docs/                     эксплуатационные и интеграционные заметки
scripts/                  systemd/watchdog/cleanup helpers
tests/                    pytest suite
static/uploads/           публичные загруженные файлы и результаты
logs/                     bot.log, bot_output.log, watchdog logs
```

## Entrypoint и роутеры

`bot/main.py`:

1. Загружает `.env`.
2. Инициализирует SQLite через `init_db()`.
3. Создает `Bot` с HTML parse mode.
4. Подключает middleware доступа:
   - бан пользователей;
   - maintenance mode;
   - админы обходят эти ограничения.
5. Подключает роутеры в важном порядке:
   - `start_router` - `/start` сбрасывает любое FSM-состояние;
   - `generation_router`;
   - `image_analyzer_router`;
   - `admin_router`;
   - `payments_router`;
   - `batch_generation_router`;
   - `common_router`.
6. В webhook mode поднимает aiohttp server.
7. В polling mode запускает `dp.start_polling(bot)`.

## HTTP routes

В webhook mode доступны:

- `POST {WEBHOOK_PATH}` - Telegram webhook, по умолчанию `/webhook`;
- `POST /tbank/webhook` - T-Bank notifications;
- `POST /cryptobot/webhook` - Crypto Bot notifications;
- `POST /webhook/kling` - Kling/PiAPI/Kie-compatible callbacks;
- `POST {KIE_AI_WEBHOOK_PATH}` - Kie.ai callbacks, по умолчанию `/webhook/kie_ai`;
- `POST /webhook/veo` - Veo callbacks;
- `GET /health` - health check;
- `GET /uploads/...` - static files from `static/uploads`.

AI webhooks проверяются через `AI_WEBHOOK_SECRET`: query `secret`, headers `x-webhook-secret`/`x-ai-webhook-secret` или bearer token.

## Конфигурация

Минимально обязательное:

```env
BOT_TOKEN=
WEBHOOK_HOST=
WEBHOOK_PATH=/webhook
WEBHOOK_BIND_HOST=127.0.0.1
WEBHOOK_PORT=8443
ADMIN_IDS=
DATABASE_URL=sqlite:///bot.db
REDIS_URL=
AI_WEBHOOK_SECRET=
```

Платежи:

```env
PAYMENT_PROVIDER=tbank
TBANK_TERMINAL_KEY=
TBANK_SECRET_KEY=
TBANK_API_URL=https://securepay.tinkoff.ru/v2/
TBANK_SUCCESS_URL=
CRYPTOBOT_API_TOKEN=
CRYPTOBOT_BASE_URL=https://pay.crypt.bot
CRYPTOBOT_ACCEPTED_ASSETS=USDT,TON,BTC,ETH,LTC,BNB,TRX,USDC
CRYPTOBOT_EXPIRES_IN=3600
```

AI-провайдеры:

```env
NANOBANANA_API_KEY=
FREEPIK_API_KEY=
NOVITA_API_KEY=
KIE_AI_API_KEY=
KIE_AI_WEBHOOK_PATH=/webhook/kie_ai
GEMINI_API_KEY=
KLING_API_KEY=
PIAPI_API_KEY=
ALLOW_NSFW=0
```

Партнерка и выплаты:

```env
PARTNER_MIN_WITHDRAWAL_RUB=0
PARTNER_RUB_PER_CREDIT=10
PARTNER_OFFER_URL=
PARTNER_RULES_URL=
JUMP_FINANCE_CLIENT_KEY=
JUMP_FINANCE_BASE_URL=https://api.jump.finance/services/openapi
JUMP_FINANCE_AGENT_ID=
JUMP_FINANCE_BANK_ACCOUNT_ID=
JUMP_FINANCE_PAYOUT_SERVICE_NAME=Партнерское вознаграждение
JUMP_FINANCE_PAYOUT_PURPOSE=Выплата партнерского вознаграждения
```

`PARTNER_MIN_WITHDRAWAL_RUB=0` означает вывод без минимального порога. `PARTNER_RUB_PER_CREDIT=10` означает курс `10 ₽ = 1 банан` для перевода партнерского заработка во внутренний баланс.

## Баланс, платежи и промокоды

Внутренняя валюта - бананы (`users.credits`).

Пакеты и цены живут в `data/price.json`. Runtime-обертка - `bot.services.preset_manager`.

Основной платежный поток:

1. Пользователь выбирает пакет.
2. `handlers/payments.py` создает транзакцию в `transactions`.
3. Провайдер возвращает ссылку/инвойс.
4. Webhook подтверждает оплату.
5. `_complete_transaction()` идемпотентно начисляет бананы через `add_credits_once()`.
6. Если есть реферал, `credit_first_payment_referral_bonus()` начисляет первый бонус.
7. Промокод помечается использованным по `order_id`.

Ledger операций по бананам хранится в `credit_transactions`. Важные причины:

- `payment_completed`;
- `generation_charge`;
- `generation_refund`;
- `admin_adjustment_add`;
- `admin_adjustment_deduct`;
- `referral_signup_bonus`;
- `referral_first_payment_bonus`;
- `referral_first_payment_partner_bonus`;
- `partner_balance_conversion`.

## Партнерская программа

Партнерка находится в `handlers/common.py` и `database.py`.

Поток:

1. У каждого пользователя есть `referral_code`.
2. Ссылка имеет вид `https://t.me/<bot>?start=ref_<code>`.
3. `process_referral()` закрепляет нового пользователя за пригласившим один раз.
4. При первой оплате реферала:
   - если пригласивший не активировал партнерку, начисляется banana-бонус;
   - если активировал, начисляется рублевый партнерский бонус.
5. Базовая ставка - 45%.
6. Gold-ставка - 50% при обороте от 300 000 ₽.
7. Рублевый баланс хранится в `users.partner_balance_rub`.
8. Вывод создает запись в `partner_withdrawals` и резервирует сумму.
9. Если выплата failed/cancelled, сумма возвращается на партнерский баланс.
10. Кнопка `🍌 Использовать в боте` переводит рубли партнерки в бананы по `PARTNER_RUB_PER_CREDIT`.

## База данных

Основная БД: `bot.db` рядом с проектом. Схема создается и мигрирует при старте через `init_db()`.

Ключевые таблицы:

- `users` - пользователи, бананы, рефералы, партнерские поля, бан;
- `transactions` - платежные транзакции T-Bank/Crypto Bot;
- `generation_tasks` - задачи генерации и результаты;
- `generation_history` - история генераций;
- `user_settings` - выбранные image/video модели и сервисы;
- `gpt55_conversations` - история GPT 5.5;
- `promo_codes` и `promo_redemptions` - промокоды;
- `bot_settings` - техрежим и другие настройки;
- `referrals` - связи реферер/реферал;
- `partner_withdrawals` - выплаты партнерам;
- `batch_jobs` - batch-задачи;
- `credit_transactions` - ledger начислений/списаний бананов.

Есть файл [migrations/postgres_schema_v1.sql](migrations/postgres_schema_v1.sql), но runtime сейчас использует SQLite.

## Модели и цены

Image-модели описаны в `bot/image_models.py`.

Video-модели описаны в `bot/video_models.py`.

Стоимость:

- image - `data/price.json -> costs_reference.image_models`;
- video - `data/price.json -> costs_reference.video_models`;
- пакеты пополнения - `data/price.json -> packages`;
- fallback-цены есть в `PresetManager`, но боевой источник - `price.json`.

После правки `price.json` можно перезагрузить конфиг через админ-панель, если соответствующий flow доступен, или перезапустить сервис.

## Reliability

`bot/services/reliability.py` использует `redis_service`:

- idempotency Telegram update ids;
- idempotency provider events;
- generation locks;
- простые rate counters.

Если `REDIS_URL` не задан или Redis недоступен, используется in-memory/null fallback. Это удобно для локального запуска, но после рестарта теряется память о dedupe/locks.

## Логи и файлы

- `logs/bot.log` - Python logging;
- `logs/bot_output.log` - stdout/stderr systemd;
- `logs/code_reload_watchdog.log` - auto-reloader;
- `logs/watchdog.log` - watchdog;
- `static/uploads` - публичные временные и result-файлы.

`on_startup()` запускает cleanup loop: удаляет файлы старше 6 часов из `static/uploads`.

## Тесты

```bash
source venv/bin/activate
pytest
python -m py_compile bot/config.py bot/database.py bot/keyboards.py bot/states.py bot/handlers/common.py
```

Существующие тесты покрывают:

- конфиг;
- database и ledger;
- реферальную/партнерскую систему;
- клавиатуры;
- webhook security/status handling;
- runtime reliability;
- storage policy;
- validators/help texts;
- часть provider payload builders.

Standalone smoke scripts лежат в `tests/standalone` и могут требовать живые API-ключи.

## Операционные команды

```bash
# Статус
systemctl status bot.service --no-pager -l

# Перезапуск кода
systemctl restart bot.service

# Перечитать unit-файлы
systemctl daemon-reload

# Логи сервиса
journalctl -u bot.service -n 100 --no-pager
tail -f logs/bot.log
tail -f logs/bot_output.log

# Проверка health
curl http://127.0.0.1:8443/health

# Проверка активных процессов
pgrep -af "python -m bot.main"
```

## Важные замечания для разработки

- Не хранить секреты в git; `.env` локальный.
- При изменении FSM/роутеров учитывать порядок подключения роутеров в `setup_dispatcher()`.
- Начисление/списание бананов проводить через функции `database.py`, чтобы не обходить ledger.
- Для новых provider webhooks добавлять idempotency и возврат `200` на нефатальные ошибки, иначе внешние сервисы будут ретраить.
- Для платежей использовать idempotent external ids.
- Для новых моделей сначала обновлять `image_models.py`/`video_models.py`, затем `data/price.json`, затем клавиатуры/handlers.
- Для публичных ссылок на uploaded files использовать `config.static_base_url` и helpers из `storage_policy.py`.

Дополнительный технический анализ: [docs/project_analysis.md](docs/project_analysis.md).
