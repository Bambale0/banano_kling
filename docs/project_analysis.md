# Project Analysis

Дата анализа: 2026-05-25.

Обновление: 2026-06-13 после production-аудита, регрессионных тестов и smoke-проверок.

## Краткое резюме

Проект - production Telegram-бот для генерации AI-контента. Архитектура монолитная: один Python-процесс держит Aiogram dispatcher, aiohttp webhook server, бизнес-логику, интеграции провайдеров, платежи и партнерку.

Система уже содержит важные production-механизмы:

- systemd service и auto-reloader;
- health endpoint;
- SQLite auto-migrations при старте;
- idempotency для Telegram updates, payment credits и части provider callbacks;
- ledger для BoomCoin;
- refunds при ошибках генерации;
- maintenance mode и ban middleware;
- тесты на ключевые database/payment/webhook сценарии.

Главная зона риска - рост сложности в одном процессе и одном большом SQLite-модуле. Проект рабочий, но уже находится на границе, где стоит постепенно выделять домены: payments, partner, generation tasks, provider callbacks, admin.

## Фактическая схема исполнения

`bot.service` запускает:

```bash
/root/bot/banano_kling/scripts/run_bot_foreground.sh
```

Скрипт:

1. Переходит в `/root/bot/banano_kling`.
2. Создает `logs` и `static/uploads`.
3. Активирует `venv`.
4. Запускает `python -m bot.main`.

`bot/main.py` при старте:

1. Загружает `.env`.
2. Вызывает `init_db()`.
3. Создает aiogram `Bot`.
4. Подключает routers.
5. Если `WEBHOOK_HOST` задан, стартует aiohttp server.
6. Если `WEBHOOK_HOST` пустой, стартует polling.

## Домены

### Генерация

Основной пользовательский flow живет в `bot/handlers/generation.py`. Часть дополнительных flow находится в `common.py`:

- Motion Control;
- GPT 5.5;
- Gemini Omni menu helpers;
- общие меню/баланс.
- Wan 2.7 Image/Image Pro/T2V/I2V/R2V/VideoEdit через Kie.ai.

Сильная сторона: все пользовательские сценарии доступны в одном боте, цены централизованы в `price.json`.

Слабая сторона: handlers стали очень крупными. Из-за этого сложнее безопасно менять FSM и provider-specific ветки.

Рекомендация:

- выносить provider orchestration в отдельные сервисы;
- оставлять в handlers только FSM, валидацию пользовательского ввода и вызов доменного сервиса;
- для новых моделей добавлять smoke/unit tests на payload и расчет цены.

Production-наблюдение 2026-06-13:

- Kie.ai live API может отклонять `wan/2-7-image-pro` с `resolution=4K` и `input_urls`, даже если документация допускает 4K в Image Pro. Код отправляет 4K, но при конкретном 422 `resolution 4K is only supported for non-sequential text-to-image` повторяет создание задачи в 2K.
- Provider error dict должен обрабатываться как ошибка API, а не как bytes изображения. Этот сценарий покрыт регрессионными тестами.
- Слишком общий prompt `смени фон` с референсом не должен запускать генерацию и списывать ресурс; бот просит уточнить новый фон.

### Платежи

Платежи находятся в `bot/handlers/payments.py` и `bot/services/tbank_service.py`/`cryptobot_service.py`.

Хорошо:

- завершение транзакции идемпотентно через `add_credits_once()`;
- промокод фиксируется по `order_id`;
- payment webhook отделен от Telegram handler;
- есть поддержка T-Bank и Crypto Bot.

Риски:

- в webhook-логике важно всегда различать "платеж уже обработан" и "ошибка начисления";
- любые новые провайдеры должны писать ledger и иметь external id.

### Партнерка

Текущая логика:

- `referral_code` есть у пользователя;
- `process_referral()` закрепляет реферала один раз;
- первая оплата реферала дает либо BoomCoin-бонус, либо рублевый партнерский бонус;
- рублевый партнерский бонус распределяется до 3 уровней: 30%, 10%, 3%;
- партнерский рублевый баланс выводится через Jump Finance;
- минимальный порог вывода снят через `PARTNER_MIN_WITHDRAWAL_RUB=0`;
- добавлена конвертация партнерского заработка в BoomCoin через `convert_partner_balance_to_credits()`.

Важная деталь: рубли партнерки и BoomCoin - разные балансы. Конвертация должна оставаться явным действием пользователя, чтобы не смешивать бухгалтерию выплат и внутренний баланс.

Рекомендация:

- добавить отдельную таблицу partner balance ledger, если партнерка продолжит расти;
- добавить тест на `convert_partner_balance_to_credits()`;
- в оферте явно описать вывод без порога и перевод в BoomCoin.

### База данных

`bot/database.py` одновременно содержит:

- dataclasses;
- schema creation/migrations;
- users;
- payments;
- partner/referral;
- generation tasks;
- admin stats;
- promo codes;
- settings;
- batch jobs;
- ledger.

Это удобно для небольшого проекта, но файл стал критической точкой риска.

Рекомендация по разбиению без большого рефакторинга:

1. `bot/db/schema.py` - init/migrations.
2. `bot/db/users.py`.
3. `bot/db/credits.py`.
4. `bot/db/payments.py`.
5. `bot/db/partners.py`.
6. `bot/db/generation_tasks.py`.
7. Сохранить обратные импорты в `bot/database.py`, чтобы не ломать handlers.

### Webhooks

Текущие routes:

- Telegram: `{WEBHOOK_PATH}`;
- T-Bank: `/tbank/webhook`;
- Crypto Bot: `/cryptobot/webhook`;
- Kling/PiAPI/Kie-compatible: `/webhook/kling`;
- Kie.ai: `{KIE_AI_WEBHOOK_PATH}`;
- Veo: `/webhook/veo`;
- static: `/uploads/`;
- Telegram Mini App: `/miniapp`, `/miniapp/assets/...`, `/api/tma/app/...`, `/api/tma/admin/...`;
- health: `/health`.

Хорошо:

- AI webhook secret поддерживает query/header/bearer;
- многие ошибки возвращают 200, чтобы не провоцировать бесконечные retries;
- есть friendly error/refund logic.

Риски:

- несколько provider formats обрабатываются в одном `main.py`, файл разрастается;
- нужно стабильно поддерживать idempotency для каждого provider status event.

Рекомендация:

- вынести provider webhook parsers в `bot/webhooks/`;
- для каждого provider держать normalized event schema: `task_id`, `status`, `result_url`, `error`, `raw`.

### Telegram Mini App

Mini App находится в `tma/`, build отдается из `tma/dist`.

Основные пользовательские routes:

- `GET /api/tma/app/bootstrap`;
- `POST /api/tma/app/upload`;
- `POST /api/tma/app/generation`;
- `POST /api/tma/app/gpt55`;
- `POST /api/tma/app/photo-to-prompt`;
- `POST /api/tma/app/payment`;
- `POST /api/tma/app/partner`;
- `GET /api/tma/app/ws`.

Основные admin routes:

- `GET /api/tma/admin/bootstrap`;
- `GET /api/tma/admin/users`;
- `POST /api/tma/admin/users/{telegram_id}/action`;
- `POST /api/tma/admin/generations/{task_id}/action`;
- `POST /api/tma/admin/packages`;
- `POST /api/tma/admin/packages/{package_id}`;
- `POST /api/tma/admin/promos`;
- `POST /api/tma/admin/push`;
- `POST /api/tma/admin/settings`.

Все защищенные TMA endpoints требуют валидный Telegram WebApp `initData`. Без него routes должны возвращать `401`.

Production-наблюдение 2026-06-13:

- Admin dashboard `active_tasks` раньше считал все старые `pending` задачи и показывал 191 активную задачу. Метрика исправлена: теперь считаются только `pending`/`processing` за последние 24 часа.
- `GET /api/tma/app/bootstrap` может возвращать большой JSON около 486 KB. Для дальнейшего роста лучше пагинировать ленту, историю и справочники.

## Текущие операционные факты

На момент анализа 2026-05-25:

- `bot.service` активен и перезапущен после `systemctl daemon-reload`;
- новый PID после перезапуска: `619962`;
- `bot-reloader.service` активен;
- основной лог: `logs/bot.log`;
- stdout/stderr: `logs/bot_output.log`;
- SQLite: `bot.db`, размер около 9.8M;
- production unit читает `.env` через `EnvironmentFile`.

На момент обновления 2026-06-13:

- `bot.service` активен;
- health endpoint `http://127.0.0.1:8443/health` возвращает `200 OK`;
- public Mini App `https://dev.chillcreative.ru/miniapp` возвращает `200 OK`;
- TMA app/admin bootstrap работают с валидным `initData`;
- TMA app/admin bootstrap возвращают `401` без `initData`;
- admin dashboard после фикса показывает реалистичный `active_tasks` вместо старых pending-задач.

## Проверки после изменений

Выполнены:

```bash
python -m py_compile bot/config.py bot/database.py bot/keyboards.py bot/states.py bot/handlers/common.py
```

Также выполнена ручная проверка партнерской конвертации на временной SQLite-БД:

- партнерский баланс: 125 ₽;
- перевод: 12 BoomCoin по курсу 10 ₽;
- итог: 12 BoomCoin начислено, 120 ₽ списано, остаток 5 ₽.

Для полного regression перед релизом желательно:

```bash
pytest -q
python -m compileall -q bot tests
python -m pip check
cd tma && npm run build
cd tma && npm audit --omit=dev --audit-level=high
curl http://127.0.0.1:8443/health
systemctl status bot.service --no-pager -l
```

Фактический результат 2026-06-13:

- backend regression: `228 passed`;
- TMA production build: успешно;
- `pip check`: без конфликтов;
- `npm audit --omit=dev --audit-level=high`: `0 vulnerabilities`;
- production smoke: service active, health 200, miniapp 200, TMA auth smoke OK.

## Риски и приоритеты

### Высокий приоритет

1. Добавить тест на партнерскую конвертацию.

Сейчас функция проверена вручную, но это денежная логика. Нужен pytest рядом с `tests/test_referral_system.py`.

2. Зафиксировать юридический текст партнерки.

Порог вывода снят, появилась конвертация в BoomCoin. Это должно совпадать с публичной офертой.

3. Проверить `.env` на production.

Если там явно стоит `PARTNER_MIN_WITHDRAWAL_RUB=2000`, кодовый дефолт `0` не сработает. Нужно поставить `PARTNER_MIN_WITHDRAWAL_RUB=0`.

4. Разобрать старые `pending` платежи.

В базе есть старые unpaid invoices. Они не входят в revenue, но в админке полезно добавить фильтр по возрасту/статусу и действие архивирования или отмены старых pending.

### Средний приоритет

1. Разнести `database.py`.

Файл слишком большой для безопасного развития. Разносить постепенно, сохраняя публичный API.

2. Разнести provider webhooks из `main.py`.

`main.py` сейчас одновременно entrypoint и большой webhook controller.

3. Включить Redis в production, если еще не включен.

Без Redis часть idempotency/locks после рестарта теряется.

4. Улучшить доставку больших видео.

Telegram может отклонять прямой URL, а upload больших файлов может завершаться `Request Entity Too Large`. Сейчас бот отправляет fallback-ссылку. Для лучшего UX нужен стабильный downloader/CDN или отправка как document при допустимом размере.

### Низкий приоритет

1. Убрать legacy YooKassa, если она больше не используется.

2. Привести docs к одному стилю: README как быстрый старт, `docs/` как глубокие инструкции.

3. Добавить таблицу "модель -> провайдер -> env vars -> webhook route".

## Рекомендуемый ближайший план

1. Добавить pytest на `convert_partner_balance_to_credits()`.
2. Проверить и обновить production `.env`.
3. Добавить админ-инструмент для отмены/архивации старых pending payments/tasks.
4. Пагинировать тяжелые TMA bootstrap-секции.
5. Обновить оферту/правила партнерки.
6. Запланировать разбиение `database.py`, `generation.py` и `main.py` на доменные модули.

## Карта важных файлов

| Файл | Назначение |
|---|---|
| `bot/main.py` | entrypoint, aiohttp server, Telegram/provider webhooks |
| `bot/database.py` | SQLite schema, migrations, balance, partner, tasks |
| `bot/config.py` | env config and derived URLs |
| `bot/handlers/common.py` | меню, партнерка, GPT 5.5, Motion Control |
| `bot/handlers/generation.py` | основной generation UX |
| `bot/handlers/payments.py` | topup и payment webhooks |
| `bot/keyboards.py` | inline keyboards |
| `bot/states.py` | FSM states |
| `bot/image_models.py` | image model registry |
| `bot/video_models.py` | video model registry |
| `data/price.json` | пакеты, цены, model costs |
| `scripts/run_bot_foreground.sh` | production start script |
| `scripts/code_reload_watchdog.py` | auto-restart watcher |
| `docs/watchdog.md` | systemd/watchdog notes |
| `docs/test.md` | regression и smoke runbook |
| `docs/production_audit_2026-06-13.md` | последний production-аудит |
