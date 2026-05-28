# Project Analysis

Дата анализа: 2026-05-25.

## Краткое резюме

Проект - production Telegram-бот для генерации AI-контента. Архитектура монолитная: один Python-процесс держит Aiogram dispatcher, aiohttp webhook server, бизнес-логику, интеграции провайдеров, платежи и партнерку.

Система уже содержит важные production-механизмы:

- systemd service и auto-reloader;
- health endpoint;
- SQLite auto-migrations при старте;
- idempotency для Telegram updates, payment credits и части provider callbacks;
- ledger для бананов;
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

Сильная сторона: все пользовательские сценарии доступны в одном боте, цены централизованы в `price.json`.

Слабая сторона: handlers стали очень крупными. Из-за этого сложнее безопасно менять FSM и provider-specific ветки.

Рекомендация:

- выносить provider orchestration в отдельные сервисы;
- оставлять в handlers только FSM, валидацию пользовательского ввода и вызов доменного сервиса;
- для новых моделей добавлять smoke/unit tests на payload и расчет цены.

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
- первая оплата реферала дает либо banana-бонус, либо рублевый партнерский бонус;
- партнерский рублевый баланс выводится через Jump Finance;
- минимальный порог вывода снят через `PARTNER_MIN_WITHDRAWAL_RUB=0`;
- добавлена конвертация партнерского заработка в бананы через `convert_partner_balance_to_credits()`.

Важная деталь: рубли партнерки и бананы - разные балансы. Конвертация должна оставаться явным действием пользователя, чтобы не смешивать бухгалтерию выплат и внутренний баланс.

Рекомендация:

- добавить отдельную таблицу partner balance ledger, если партнерка продолжит расти;
- добавить тест на `convert_partner_balance_to_credits()`;
- в оферте явно описать вывод без порога и перевод в бананы.

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

## Текущие операционные факты

На момент анализа:

- `bot.service` активен и перезапущен после `systemctl daemon-reload`;
- новый PID после перезапуска: `619962`;
- `bot-reloader.service` активен;
- основной лог: `logs/bot.log`;
- stdout/stderr: `logs/bot_output.log`;
- SQLite: `bot.db`, размер около 9.8M;
- production unit читает `.env` через `EnvironmentFile`.

## Проверки после изменений

Выполнены:

```bash
python -m py_compile bot/config.py bot/database.py bot/keyboards.py bot/states.py bot/handlers/common.py
```

Также выполнена ручная проверка партнерской конвертации на временной SQLite-БД:

- партнерский баланс: 125 ₽;
- перевод: 12 бананов по курсу 10 ₽;
- итог: 12 бананов начислено, 120 ₽ списано, остаток 5 ₽.

Для полного regression перед релизом желательно:

```bash
pytest
curl http://127.0.0.1:8443/health
systemctl status bot.service --no-pager -l
```

## Риски и приоритеты

### Высокий приоритет

1. Добавить тест на партнерскую конвертацию.

Сейчас функция проверена вручную, но это денежная логика. Нужен pytest рядом с `tests/test_referral_system.py`.

2. Зафиксировать юридический текст партнерки.

Порог вывода снят, появилась конвертация в бананы. Это должно совпадать с публичной офертой.

3. Проверить `.env` на production.

Если там явно стоит `PARTNER_MIN_WITHDRAWAL_RUB=2000`, кодовый дефолт `0` не сработает. Нужно поставить `PARTNER_MIN_WITHDRAWAL_RUB=0`.

### Средний приоритет

4. Разнести `database.py`.

Файл слишком большой для безопасного развития. Разносить постепенно, сохраняя публичный API.

5. Разнести provider webhooks из `main.py`.

`main.py` сейчас одновременно entrypoint и большой webhook controller.

6. Включить Redis в production, если еще не включен.

Без Redis часть idempotency/locks после рестарта теряется.

### Низкий приоритет

7. Убрать legacy YooKassa, если она больше не используется.

8. Привести docs к одному стилю: README как быстрый старт, `docs/` как глубокие инструкции.

9. Добавить таблицу "модель -> провайдер -> env vars -> webhook route".

## Рекомендуемый ближайший план

1. Добавить pytest на `convert_partner_balance_to_credits()`.
2. Проверить и обновить production `.env`.
3. Прогнать полный `pytest`.
4. Проверить `curl /health` после рестарта.
5. Обновить оферту/правила партнерки.
6. Запланировать разбиение `database.py` и `main.py` на доменные модули.

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
