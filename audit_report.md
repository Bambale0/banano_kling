# 🔴 AUDIT REPORT — banano_kling

**Дата:** 2026-07-04
**Аудитор:** Senior QA Architect / Security Reviewer / Backend Auditor
**Объём:** ~90 файлов, ~15K строк кода
**Методология:** статический анализ кода, построение карты связей, сравнение handler/keyboard, аудит payload'ов API

---

## 1. Executive Summary

| Параметр | Значение |
|----------|----------|
| **Проект запускается?** | Требует проверки — не проверялся живой запуск |
| **P0 рисков** | 12 |
| **P1 рисков** | 28 |
| **P2 рисков** | 19 |
| **P3 рисков** | 8 |
| **Главная угроза деньгам** | Отсутствие атомарных транзакций при списании баланса + двойное списание при race condition |
| **Главная угроза безопасности** | Отсутствие проверки Telegram initData в mini-app; IDOR через подмену task_id в callback_data |
| **Главная угроза стабильности** | 429/500 от внешних API не обрабатываются с возвратом средств; задачи застревают в статусе `processing` |
| **Готов к production** | **НЕТ** — требуется устранение P0 и P1 перед релизом |
| **Топ-5 исправлений** | 1. Транзакционное обновление баланса 2. Идемпотентность webhook'ов 3. Возврат средств при ошибке API 4. Проверка initData в mini-app 5. Обработка 429/500 от провайдеров |

---

## 2. Карта проекта

### 2.1 Стек

| Слой | Технология |
|------|-----------|
| Python | 3.x |
| Telegram Bot | aiogram 3.x |
| База данных | SQLite (dev) / PostgreSQL (prod) через aiosqlite + адаптер |
| Redis | redis-py 5.x (FSM storage + кэш) |
| HTTP Server | aiohttp (webhook) |
| Frontend | Next.js 14 + React + Tailwind + shadcn/ui (Telegram Mini App) |
| Платежи | YooKassa, CryptoBot, Lava.top, Telegram Stars, TBank |
| AI API | Kie.ai (Kling, Seedance, Seedream, Veo, Wan27), Google Gemini, OpenAI GPT-Image, xAI Grok |
| Конфигурация | python-dotenv + pydantic |
| Type hints | typing-extensions |

### 2.2 Точки входа

| Точка | Файл | Тип |
|-------|------|-----|
| `main()` | `bot/main.py:701` | Запуск бота |
| `/webhook` | `bot/main.py:182` (aiohttp) | Telegram webhook |
| `/webhook/yookassa` | `bot/services/yookassa_service.py` | YooKassa webhook |
| `/webhook/cryptobot` | `bot/services/cryptobot_service.py` | CryptoBot webhook |
| `/webhook/lava` | `bot/services/lava_service.py` | Lava webhook |
| `/webhook/tbank` | `tbank_payment/webhooks.py` | TBank webhook |
| `/healthcheck` | `bot/main.py` (aiohttp) | Healthcheck |
| `/api/generation/webhook` | Сервисы Kie.ai | AI provider callback |

### 2.3 Handlers / Routes

| Router | Файл | Handler'ов |
|--------|------|-----------|
| main_router | `bot/handlers/common.py` | ~15 |
| generation_router | `bot/handlers/generation.py` | ~25 |
| payment_router | `bot/handlers/payments.py` | ~18 |
| admin_router | `bot/handlers/admin.py` | ~20 |
| batch_router | `bot/handlers/batch_generation.py` | ~5 |
| image_analyzer_router | `bot/handlers/image_analyzer.py` | ~5 |

### 2.4 Внешние API

| API | Сервис | Аутентификация |
|-----|--------|---------------|
| Kie.ai | `kling_service.py`, `seedance_service.py`, `seedream_service.py`, `veo_service.py`, `wan27_service.py`, `kie_file_upload_service.py`, `kie_market_service.py` | API Key в Header |
| Google Gemini | `gemini_service.py`, `gemini_omni_service.py` | API Key |
| OpenAI GPT-Image | `gpt_image_service.py` | API Key |
| xAI Grok | `grok_service.py` | API Key |
| YooKassa | `yookassa_service.py`, `services/yookassa_client.py` | Shop ID + Secret |
| CryptoBot | `cryptobot_service.py` | API Token |
| Lava.top | `lava_service.py` | Secret Key |
| TBank | `tbank_payment/` | API Token |
| NanoBanana API | `nano_banana_2_service.py`, `nano_banana_pro_service.py` | API Key |
| Redis | `redis_service.py` | Redis URL |

### 2.5 БД-сущности

| Таблица | Ключевые поля |
|---------|--------------|
| `users` | id, telegram_id, credits, referral_code, referred_by, is_admin, subscription, limits |
| `transactions` | id, user_id, type, amount, provider_payment_id, status, metadata |
| `generation_tasks` | id, user_id, service_name, prompt, status, external_task_id, result_url, credits_spent, created_at |
| `referral_codes` | id, code, created_by |
| `referral_bonuses` | id, user_id, referred_user_id, transaction_id, amount |
| `subscriptions` | user_id, plan, active_until, auto_renew |
| `feed` | id, user_id, content, media_urls, created_at |
| `presets` | id, user_id, name, prompt, negative_prompt, model, params |
| `admin_ai_logs` | id, admin_id, request_text, response_text, actions_taken |

### 2.6 Тесты

- **Фреймворк:** pytest (pytest.ini присутствует)
- **Тестов:** **НЕ ОБНАРУЖЕНО** — в репозитории нет ни одного тестового файла
- **pytest.ini** содержит `asyncio_mode = auto`, но тестовые модули отсутствуют

---

## 3. Реестр дефектов

### P0 — Критические (12)

| ID | Severity | Area | Симптом | Причина | Файл/строка | Как воспроизвести | Ожидаемо | Фактически | Fix |
|----|----------|------|---------|---------|-------------|-------------------|----------|------------|-----|
| **P0-01** | P0 | БД/Баланс | Двойное списание баланса при race condition | `UPDATE users SET credits = credits - :amount WHERE id = :uid` без `SELECT ... FOR UPDATE` и без проверки текущего баланса | `bot/database.py:get_user_credits()` / `update_user_credits()` | Два быстрых нажатия "Сгенерировать" → два запроса параллельно | Баланс списан один раз | Оба списания проходят, баланс уходит в минус | Обернуть в транзакцию с `SELECT ... FOR UPDATE`, проверять `credits >= amount` внутри UPDATE |
| **P0-02** | P0 | Платежи | Webhook YooKassa не идемпотентен | Нет проверки `event_id` / дублирования при повторном webhook'е | `bot/services/yookassa_service.py` | Отправить webhook дважды с одним payment_id | Повторный webhook игнорируется | Баланс начисляется дважды | Сохранять `webhook_event_id` в отдельную таблицу/поле, проверять уникальность перед обработкой |
| **P0-03** | P0 | Платежи | Webhook CryptoBot не идемпотентен | Аналогично P0-02 | `bot/services/cryptobot_service.py` | Отправить webhook дважды | Игнорируется | Двойное начисление | Добавить `UNIQUE(provider_payment_id)` constraint + проверку |
| **P0-04** | P0 | Генерация | Ошибка внешнего API не возвращает средства | При HTTP 429/500/502 от Kie.ai задача получает статус `failed`, но `credits` не возвращаются | `bot/services/kling_service.py`, `bot/handlers/generation.py` | Мокнуть Kie.ai с 500 ошибкой | Баланс восстановлен | Баланс списан безвозвратно | В обработчике ошибок вызывать возврат credits через `update_user_credits(uid, +amount)` с аудитом |
| **P0-05** | P0 | Генерация | Задача застревает в статусе `processing` навсегда | Нет фонового процесса/polling'а для зависших задач | Все сервисы (Veo, Seedance, Wan27) используют callback_url, но не имеют fallback polling | Задача создана, webhook потерян (сеть, перезагрузка) | Задача переходит в failed/timed_out через N минут | Задача висит processing вечно | Добавить background job для опроса задач старше N минут без финального статуса |
| **P0-06** | P0 | Безопасность | IDOR: пользователь может получить чужую задачу | `callback_data` содержит `task_id`, но нет проверки `task.user_id == current_user.id` в некоторых handler'ах | `bot/handlers/generation.py:check_task_status()`, `admin.py` | Подменить `task_id` в callback_data на чужой | Отказ в доступе | Выдаётся чужая задача/результат | Добавить `WHERE user_id = :current_user_id` во все запросы по `task_id` |
| **P0-07** | P0 | Безопасность | Mini-app не проверяет Telegram initData | `frontend/miniapp-v0/app/page.tsx` использует WebApp.initData но backend не валидирует подпись | `bot/miniapp.py`, `bot/main.py` webapp endpoint | Отправить поддельный initData напрямую в бота | Запрос отклонён | Запрос принимается, злоумышленник действует от имени любого пользователя | Внедрить `validate_telegram_webapp_data()` на backend для всех mini-app endpoint'ов |
| **P0-08** | P0 | Безопасность | Webhook Kie.ai не проверяет подпись/источник | `callBackUrl` принимает любые POST-запросы без аутентификации | `bot/main.py`, webhook handler генерации | Отправить поддельный webhook с success + result_url | Webhook должен быть аутентифицирован | Злоумышленник может пометить задачу completed и подменить URL результата | Добавить HMAC-секрет в callback_url как query-параметр и проверять его |
| **P0-09** | P0 | Платежи | Lava webhook не проверяет подпись | `bot/services/lava_service.py` — webhook handler не содержит проверки HMAC-подписи | `bot/services/lava_service.py` | Отправить поддельный webhook | Проверка подписи → reject | Начисление без реальной оплаты | Добавить проверку HMAC-SHA256 подписи в webhook-обработчике |
| **P0-10** | P0 | Платежи | TBank webhook не проверяется | `tbank_payment/webhooks.py` — отсутствует проверка подписи уведомления | `tbank_payment/webhooks.py` | Отправить поддельный webhook | Проверка подписи | Неконтролируемое начисление | Имплементировать проверку TBank Notification Signature |
| **P0-11** | P0 | БД | Отсутствие транзакций при списании + создании задачи | `deduct_credits + insert generation_task + call external API` не в одной транзакции | `bot/handlers/generation.py` | Баланс списан, insert упал | Rollback всей операции | Орфан: баланс списан, задачи нет | Обернуть в DB transaction |
| **P0-12** | P0 | Конфигурация | Секреты в `config.py` без fallback по умолчанию | Некоторые вызовы `.get()` без `.required()` могут привести к None при запуске — падение с невнятной ошибкой | `bot/config.py` | Запустить без `KIE_API_KEY` | Понятная ошибка при старте | `AttributeError: 'NoneType' has no attribute ...` в рантайме | Все `config.get()` для обязательных ключей заменить на `.required()` с pydantic валидацией |

### P1 — Высокие (28)

| ID | Severity | Area | Симптом | Файл/строка | Fix |
|----|----------|------|---------|-------------|-----|
| P1-01 | P1 | Callback | `callback_data` для кнопки "Назад" не содержит state для возврата | `bot/keyboards.py`, `bot/handlers/common.py` | Сохранять предыдущее состояние в callback_data или FSM |
| P1-02 | P1 | Callback | `generate_model:X` callback парсится через `.split(":")`, но model_name может содержать `:` | `bot/handlers/generation.py` | Использовать `split(":", 1)` или другой разделитель |
| P1-03 | P1 | FSM | Состояние FSM может быть очищено middleware `clear_state_before_start`, но handler всё ещё ожидает его | `bot/main.py` middleware, `bot/handlers/generation.py` | Добавить проверку наличия state-данных перед их использованием |
| P1-04 | P1 | API | `callBackUrl` параметр в Kie.ai — camelCase, но некоторые сервисы передают `callback_url` (snake_case) | `bot/services/veo_service.py`, `bot/services/seedance_service.py` | Унифицировать: `callBackUrl` согласно API Kie.ai |
| P1-05 | P1 | API | `image_url` для референсов: локальный путь vs публичный URL | `bot/services/reference_storage_service.py` | Убедиться, что файл загружен в публичное хранилище перед отправкой во внешний API |
| P1-06 | P1 | API | Seedance `generate_video()` не передаёт `callBackUrl` во всех случаях | `bot/services/seedance_service.py` | Гарантировать передачу `callBackUrl` для отслеживания статуса |
| P1-07 | P1 | API | Gemini: `response_format` не всегда парсится корректно при ответах с несколькими кандидатами | `bot/services/gemini_service.py` | Добавить итерацию по `candidates` и проверку `finish_reason` |
| P1-08 | P1 | Платежи | YooKassa: сумма платежа в копейках vs рублях — возможно расхождение | `bot/services/yookassa_service.py` | Явно документировать и валидировать, что сумма в копейках |
| P1-09 | P1 | Платежи | CryptoBot: invoice создаётся без `expires_in` | `bot/services/cryptobot_service.py` | Добавить `expires_in` для автоотмены неоплаченных инвойсов |
| P1-10 | P1 | Referral | Начисление реферального бонуса при self-referral | `bot/services/referral_service.py` | Добавить проверку `referrer_id != referred_user_id` |
| P1-11 | P1 | Referral | Реферальный бонус может начислиться дважды за одну оплату | `bot/services/referral_service.py` | Добавить `UNIQUE(payment_id, bonus_type)` constraint |
| P1-12 | P1 | Админ | `/admin` команда доступна по прямому тексту, но middleware не проверяет is_admin на уровне роутера | `bot/handlers/admin.py`, middleware в `bot/main.py` | Убедиться, что ВСЕ admin handler'ы проходят проверку `is_admin` |
| P1-13 | P1 | Админ | `AdminStates.waiting_ai_request` — любой пользователь может вручную установить это состояние через deep link? | `bot/states.py`, `bot/handlers/admin.py` | Добавить проверку is_admin при входе в admin-состояние |
| P1-14 | P1 | Mini-app | Нет обработки ошибок сети между mini-app и ботом | `frontend/miniapp-v0/`, `bot/miniapp.py` | Добавить retry на фронтенде + graceful degradation |
| P1-15 | P1 | Mini-app | История задач загружается без пагинации — потенциально медленно | `frontend/miniapp-v0/components/task-history-list.tsx` | Добавить пагинацию/cursor |
| P1-16 | P1 | БД | `referral_code` в SQLite НЕ имеет UNIQUE constraint через индекс (в отличие от PG) | `bot/database.py:init_db()` | Добавить `CREATE UNIQUE INDEX IF NOT EXISTS idx_users_referral_code` |
| P1-17 | P1 | БД | `transactions.provider_payment_id` — нет UNIQUE constraint | `bot/database.py` | Добавить `UNIQUE(provider_payment_id)` для защиты от дублей |
| P1-18 | P1 | БД | `generation_tasks.external_task_id` — нет индекса | `bot/database.py` | Добавить `INDEX ON generation_tasks(external_task_id)` для webhook lookup |
| P1-19 | P1 | Валидация | Prompt не валидируется на длину перед отправкой в API | `bot/handlers/generation.py` | Обрезать/валидировать prompt до лимитов конкретного провайдера |
| P1-20 | P1 | Валидация | Нет проверки размера загружаемого файла | `bot/handlers/common.py` | Добавить лимит (Telegram: 20MB, API: различный) |
| P1-21 | P1 | Ошибки | `try/except Exception` в некоторых handler'ах проглатывает ошибку без логирования | `bot/handlers/generation.py`, `bot/handlers/payments.py` | Логировать `exc_info=True` |
| P1-22 | P1 | Ошибки | 400 ошибка от Kie.ai: не парсится тело ответа с деталями ошибки | `bot/services/kling_service.py` | Парсить `response.json()` и возвращать детали ошибки пользователю |
| P1-23 | P1 | Ошибки | При network timeout нет retry логики | Все сервисы | Добавить `tenacity` / exponential backoff |
| P1-24 | P1 | FSM | Пользователь может начать новый flow, не завершив старый — состояние теряется | `bot/states.py` | Добавить `cancel` команду или тайм-аут FSM состояний |
| P1-25 | P1 | Логи | Нет correlation_id в логах — невозможно отследить цепочку запросов | Все handler'ы и сервисы | Добавить `structlog` с `task_id`/`user_id`/`request_id` |
| P1-26 | P1 | Mini-app | `Telegram.WebApp.initDataUnsafe` используется вместо `initData` для проверки | `frontend/miniapp-v0/` | Всегда проверять подпись на backend с `initData` |
| P1-27 | P1 | БД | `updated_at` не обновляется автоматически в SQLite | `bot/database.py` | Добавить `updated_at = CURRENT_TIMESTAMP` в UPDATE-запросах или использовать SQLite trigger |
| P1-28 | P1 | API | `aspect_ratio` не валидируется перед отправкой — API может вернуть 400 с невнятной ошибкой | `bot/handlers/generation.py`, `bot/services/kling_service.py` | Валидировать enum значений aspect_ratio на фронте + бэкенде |

### P2 — Средние (19)

| ID | Area | Симптом | Fix |
|----|------|---------|-----|
| P2-01 | UX | Кнопка "Назад" возвращает в главное меню, а не на предыдущий шаг | Сохранять историю навигации в FSM |
| P2-02 | UX | При ошибке генерации пользователь видит техническое сообщение | Использовать `user_facing_errors.py` для маппинга |
| P2-03 | Кэш | Redis не используется для кэширования результатов — повторные запросы идут в API | Кэшировать результаты для одинаковых prompt |
| P2-04 | Rate Limit | Нет rate limiting на API endpoints | Добавить `aiogram-throttling` или Redis rate limiter |
| P2-05 | Документация | API docs (`docs/kling_api.md`) устарели — не соответствуют текущему коду | Обновить документацию |
| P2-06 | CI | Нет CI/CD pipeline | Добавить GitHub Actions для lint + test |
| P2-07 | Lint | `requirements.txt` не закрепляет минорные версии | Использовать `pip freeze` или `poetry.lock` |
| P2-08 | Docker | Нет Dockerfile | Добавить Dockerfile и docker-compose |
| P2-09 | Логи | `print()` используется вместо `logging` в некоторых местах | Заменить на `logging.getLogger(__name__)` |
| P2-10 | Graceful | Нет graceful shutdown — задачи в processing теряются | Добавить сохранение состояния при SIGTERM |
| P2-11 | Конфиг | `postgres_aiosqlite.py` транслирует SQLite-диалект на лету — хрупкий подход | Использовать SQLAlchemy + Alembic |
| P2-12 | Schema | `schema_postgres.sql` и `bot/database.py` могут расходиться | Автоматизировать генерацию схемы |
| P2-13 | Мёртвый код | `bot/neuromix_copy.py`, `bot/partner_copy.py`, `bot/support_copy.py` — судя по названиям, старые версии | Удалить или отрефакторить |
| P2-14 | Тесты | Нет ни одного теста | Создать базовый test suite |
| P2-15 | Webhook | `allowed_updates` не настроен — бот получает все типы обновлений | Фильтровать `allowed_updates=["message", "callback_query"]` |
| P2-16 | N+1 | Загрузка истории задач: N отдельных запросов вместо одного batch | JOIN или batch query |
| P2-17 | Реферал | Реферальный код генерируется без проверки коллизий | Добавить retry при генерации |
| P2-18 | Ошибки | `bot/utils/user_facing_errors.py` существует, но не используется систематически | Интегрировать во все handler'ы |
| P2-19 | Цены | `data/price.json` и `bot/pricing_final.py` — два источника цен, могут расходиться | Оставить один источник истины |

### P3 — Улучшения (8)

| ID | Area | Fix |
|----|------|-----|
| P3-01 | UX | Добавить инлайн-прогресс (progress bar) во время генерации |
| P3-02 | UX | Добавить превью результата перед отправкой пользователю |
| P3-03 | Аналитика | Добавить сбор метрик: conversion rate, среднее время генерации |
| P3-04 | i18n | Все тексты захардкожены на русском — добавить i18n |
| P3-05 | Мониторинг | Добавить healthcheck для каждого внешнего API |
| P3-06 | Документация | Добавить архитектурную схему (C4 model) |
| P3-07 | Type Hints | `Dict[str, Any]` используется повсеместно — заменить на TypedDict/Pydantic модели |
| P3-08 | Зависимости | `bot/services/admin_ai_service.py` импортирует `openai` но не указан в `requirements.txt` — проверить |

---

## 4. Таблица links / callbacks / routes

| UI / Button / URL | Где создано | Что передаёт | Что ожидает handler | Совпадает? | Проблема |
|-------------------|-------------|-------------|---------------------|------------|----------|
| `btn_generate` → `generate_model:kling` | `keyboards.py:model_selection_keyboard()` | `callback_data="generate_model:kling"` | `generation.py:process_model_selection()` → `callback.data.split(":")` | ✅ | Риск: model_name с `:` сломает split |
| `btn_back` → `main_menu` | `keyboards.py` | `callback_data="main_menu"` | `common.py:cmd_start()` | ✅ | |
| `btn_balance` → `check_balance` | `keyboards.py` | `callback_data="check_balance"` | `payments.py:check_balance_handler()` | ✅ | |
| `btn_payment` → `payment_method:X` | `keyboards.py` | `callback_data="payment_method:yookassa"` | `payments.py:payment_method_handler()` | ✅ | |
| `btn_admin` → `admin` | `keyboards.py` | `callback_data="admin"` | `admin.py:admin_panel()` + проверка is_admin | ✅ | |
| `btn_task_status` → `check_task:X` | `keyboards.py` | `callback_data="check_task:{task_id}"` | `generation.py:check_task_status()` | ⚠️ | P0-06: нет проверки `user_id` в handler |
| `btn_cancel` → `cancel_generation` | `keyboards.py` | `callback_data="cancel_generation"` | `generation.py:cancel_handler()` | ⚠️ | Не возвращает credits, оставляет orphan task |
| `btn_retry` → `retry_task:X` | `generation.py` (reply_markup) | `callback_data="retry_task:{task_id}"` | `generation.py:retry_handler()` | ⚠️ | Повторное списание без проверки статуса задачи |
| Mini-app link | `miniapp_links.py` | `https://t.me/.../app?startapp={user_id}` | `bot/main.py` webapp handler | ⚠️ | P0-07: нет проверки подписи |
| Admin AI кнопка | `keyboards.py` | `callback_data="admin_ai"` | `admin.py:admin_ai_open()` | ✅ | P1-13: любой в FSM `AdminStates` может вызвать |
| `btn_batch` | `keyboards.py` | `callback_data="batch_generation"` | `batch_generation.py:batch_handler()` | ⚠️ | Не проверяет доступность batch-функции в тарифе |
| `btn_history` → `task_history:X` | `keyboards.py` | `callback_data="task_history:page=1"` | `generation.py:history_handler()` | ✅ | P1-15: нет пагинации |
| YooKassa webhook | `yookassa_service.py` (URL конфигурация) | POST `/webhook/yookassa` | `yookassa_service.py:webhook_handler()` | ⚠️ | P0-02: нет идемпотентности |
| CryptoBot webhook | `cryptobot_service.py` | POST `/webhook/cryptobot` | `cryptobot_service.py:webhook_handler()` | ⚠️ | P0-03: нет идемпотентности |
| Lava webhook | `lava_service.py` | POST `/webhook/lava` | `lava_service.py:webhook_handler()` | ⚠️ | P0-09: нет проверки подписи |
| TBank webhook | `tbank_payment/webhooks.py` | POST `/webhook/tbank` | `webhooks.py:tbank_webhook_handler()` | ⚠️ | P0-10: нет проверки подписи |
| Kie.ai callback | `kling_service.py:create_task()` | POST `{callBackUrl}` | `bot/main.py` webhook endpoint | ⚠️ | P0-08: нет аутентификации webhook'а |
| Kie.ai file upload | `kie_file_upload_service.py` | POST `https://api.kie.ai/v1/files` | — | ⚠️ | P1-05: может передаваться локальный путь |

---

## 5. Таблица external API payload

| Provider | Method | Endpoint | Required fields | Current payload | Missing/Wrong | Risk |
|----------|--------|----------|-----------------|-----------------|---------------|------|
| Kie.ai Kling | POST | `/v1/videos/kling` | `model`, `prompt`, `callBackUrl` | ✅ | `callBackUrl` — camelCase в коде, надо проверить | P1-04 |
| Kie.ai Seedance | POST | `/v1/videos/seedance` | `model`, `prompt`, `duration`, `callBackUrl` | ⚠️ Не всегда передаётся `callBackUrl` | P1-06 | Задача теряется |
| Kie.ai Seedream | POST | `/v1/images/seedream` | `model`, `prompt`, `callBackUrl` | ✅ | — | Низкий |
| Kie.ai Veo | POST | `/v1/videos/veo` | `model`, `prompt`, `duration`, `callBackUrl` | ✅ | — | Низкий |
| Kie.ai Wan27 | POST | `/v1/videos/wan27` | `model`, `prompt`, `callBackUrl` | ✅ | — | Низкий |
| Kie.ai file upload | POST | `/v1/files` | `file`, `purpose` | ⚠️ `file` может быть локальным путём | P1-05 | API не может скачать локальный файл |
| Google Gemini | POST | `/v1beta/models/{model}:generateContent` | `contents`, `generation_config` | ✅ | Может не обрабатывать `finish_reason=SAFETY` | P1-07 |
| OpenAI GPT-Image | POST | `/v1/images/generations` | `prompt`, `model`, `n`, `size` | ✅ | — | Низкий |
| xAI Grok | POST | `/v1/chat/completions` | `messages`, `model` | ✅ | — | Низкий |
| YooKassa | POST | `/v3/payments` | `amount`, `confirmation`, `description` | ⚠️ Сумма в копейках vs рублях | P1-08 | Неверная сумма платежа |
| CryptoBot | GET | `/api/createInvoice` | `asset`, `amount`, `description` | ⚠️ Нет `expires_in` | P1-09 | Инвойс висит вечно |
| Lava | POST | `/api/invoice` | `amount`, `order_id`, `shop_id` | ⚠️ Нет HMAC подписи в webhook | P0-09 | Поддельный webhook |
| TBank | POST | `/v2/Init` | `Amount`, `OrderId`, `Description` | ⚠️ Нет проверки webhook подписи | P0-10 | Поддельный webhook |
| NanoBanana | POST | `/generate` | `prompt`, `api_key` | ✅ | — | Низкий |
| NanoBanana Pro | POST | `/pro/generate` | `prompt`, `api_key`, `negative_prompt` | ✅ | — | Низкий |

---

## 6. Бизнес-логика

| Entity / Flow | Invariant | Нарушается? | Доказательство | Fix | Test |
|---------------|-----------|-------------|----------------|-----|------|
| Balance | Не может быть отрицательным | ✅ Нарушается | `UPDATE credits = credits - :amount` без проверки `WHERE credits >= :amount` | Добавить `WHERE credits >= :amount` | `test_deduct_insufficient_balance` |
| Balance | Списание атомарно с созданием задачи | ✅ Нарушается | Нет транзакции между `deduct` и `insert task` | Обернуть в DB transaction | `test_deduct_and_create_task_atomic` |
| Payment | Один payment_id → одно начисление | ✅ Нарушается | Нет UNIQUE constraint на `provider_payment_id` | P0-02/P0-03 | `test_double_webhook_idempotent` |
| Payment | Webhook подпись валидна | ✅ Нарушается (Lava, TBank) | HMAC не проверяется | P0-09/P0-10 | `test_lava_webhook_invalid_signature` |
| Referral | Нельзя рефералить самого себя | ✅ Нарушается | Нет проверки `referrer_id != referred_user_id` | P1-10 | `test_self_referral_blocked` |
| Referral | Один платёж → один бонус | ✅ Нарушается | Нет UNIQUE(payment_id, bonus_type) | P1-11 | `test_referral_bonus_once_per_payment` |
| Generation | Статусы: pending → processing → completed/failed | ⚠️ Частично | `processing` может застрять без тайм-аута | P0-05 | `test_task_timeout_to_failed` |
| Generation | Пользователь видит только свои задачи | ✅ Нарушается | `task_id` не проверяется на `user_id` в handler'ах | P0-06 | `test_cannot_access_other_user_task` |
| Generation | Отмена задачи возвращает credits | ✅ Нарушается | `cancel_handler` не возвращает credits | P1(link) | `test_cancel_returns_credits` |
| Admin | Только admin вызывает admin-функции | ⚠️ Частично | `is_admin` проверяется не во всех admin handler'ах | P1-12 | `test_non_admin_blocked_from_admin_panel` |
| Admin | AI-ассистент админа: действия логируются | ❓ Требует проверки | `admin_ai_service.py` — нужно проверить audit log | — | `test_admin_ai_actions_logged` |
| Subscription | Тариф определяет лимиты генераций | ❓ Требует проверки | `subscription_service.py` — интеграция с генерацией неясна | Проверить связь subscription ↔ generation limits | `test_subscription_limits_enforced` |
| Price | Цена списывается согласно `pricing_final.py` | ❓ Требует проверки | `generation.py` берёт цену из `pricing_final.py`, но `data/price.json` тоже существует | Убедиться, что используется один источник | `test_price_consistency` |
| Credits | `credits_spent` сохраняется в `generation_tasks` | ❓ Требует проверки | Проверить, что при создании задачи поле заполняется | Проверить INSERT в `generation_tasks` | `test_generation_task_saves_credits_spent` |

---

## 7. Smoke Checklist

| # | Check | Command / Steps | Expected | Status | Fix |
|---|-------|----------------|----------|--------|-----|
| S1 | Установка зависимостей | `pip install -r requirements.txt` | Без ошибок | ❓ | — |
| S2 | Импорт всех модулей | `python -c "import bot; import bot.main; import bot.handlers"` | Без ошибок | ❓ | — |
| S3 | Чтение env | `python -c "from bot.env import load_env; load_env()"` | Все required переменные определены | ❓ | P0-12 |
| S4 | Подключение к БД | `python -c "from bot.database import init_db; import asyncio; asyncio.run(init_db())"` | Таблицы созданы | ❓ | — |
| S5 | Миграции | Проверить schema_postgres.sql vs init_db() | Схемы идентичны | ❓ | P2-12 |
| S6 | Старт бота (polling) | `python bot/main.py` | Бот запущен, polling активен | ❓ | — |
| S7 | Старт бота (webhook) | `WEBHOOK_HOST=... python bot/main.py` | Webhook установлен | ❓ | — |
| S8 | Healthcheck | `curl http://localhost:8080/healthcheck` | HTTP 200 | ❓ | — |
| S9 | /start команда | Отправить /start боту | Ответ с главным меню | ❓ | — |
| S10 | Главное меню | Нажать кнопки главного меню | Все кнопки работают | ❓ | — |
| S11 | Создание тестовой генерации | Выбрать модель → ввести prompt | Задача создана, credits списаны | ❓ | P0-01 |
| S12 | Webhook генерации | Отправить mock webhook success | Статус задачи → completed, пользователь уведомлён | ❓ | P0-08 |
| S13 | Тестовый платёж YooKassa | Создать платёж → оплатить → проверить баланс | Баланс увеличен | ❓ | P0-02 |
| S14 | Тестовый платёж CryptoBot | Аналогично | Баланс увеличен | ❓ | P0-03 |
| S15 | Админская команда | `/admin` от admin user | Админ-панель открыта | ❓ | P1-12 |
| S16 | Админская команда (не admin) | `/admin` от обычного пользователя | Отказ в доступе | ❓ | P1-12 |
| S17 | Mini-app открытие | Перейти по ссылке mini-app | Приложение загружается | ❓ | P0-07 |
| S18 | Mini-app история задач | Открыть историю в mini-app | Видны только свои задачи | ❓ | P0-06 |
| S19 | Перезагрузка во время генерации | Убить процесс → перезапустить | Задачи в `processing` не потеряны | ❓ | P0-05 |
| S20 | Graceful shutdown | SIGTERM → бот останавливается | Все pending операции завершены или сохранены | ❓ | P2-10 |

**Статус:** ❓ = требуется ручная проверка при живом запуске

---

## 8. Regression Matrix

| # | Flow | Covered? | Broken? | Missing Test | Risk | Priority |
|---|------|----------|---------|-------------|------|----------|
| R1 | Новый пользователь → /start → главное меню | ❓ | — | `test_new_user_start_flow` | P0 | 1 |
| R2 | Пополнение баланса → обновление → транзакция | ❓ | P0-02/03 | `test_payment_flow` | P0 | 1 |
| R3 | Генерация → списание → задача → API → результат | ❓ | P0-01/04/06 | `test_generation_flow_e2e` | P0 | 1 |
| R4 | API error → задача failed → возврат средств | ❓ | P0-04 | `test_generation_error_refund` | P0 | 1 |
| R5 | Повторное нажатие → нет двойного списания | ❓ | P0-01 | `test_no_double_deduct_on_double_click` | P0 | 1 |
| R6 | Двойной webhook → нет двойного начисления | ❓ | P0-02 | `test_webhook_idempotency` | P0 | 1 |
| R7 | История → только свои задачи | ❓ | P0-06 | `test_history_shows_only_own_tasks` | P0 | 1 |
| R8 | Админ → статистика → корректные агрегаты | ❓ | — | `test_admin_statistics` | P1 | 2 |
| R9 | Обычный пользователь → admin callback → отказ | ❓ | P1-12 | `test_non_admin_blocked` | P1 | 2 |
| R10 | Старый callback_data после обновления | ❓ | — | `test_old_callback_graceful_error` | P2 | 3 |
| R11 | Старые записи БД после миграции | ❓ | — | `test_old_db_records_compatible` | P2 | 3 |
| R12 | Отмена генерации → возврат credits | ❓ | P1 (link) | `test_cancel_returns_credits` | P1 | 2 |
| R13 | Реферал: регистрация по коду → бонус при первой оплате | ❓ | P1-10/11 | `test_referral_full_flow` | P1 | 2 |

---

## 9. Unit Test Gaps

| Function | Current Tests | Missing Cases | Suggested Tests |
|----------|--------------|---------------|-----------------|
| `get_user_credits(user_id)` | 0 | `user_id = 0`, `user_id = None`, несуществующий id | `test_get_credits_new_user`, `test_get_credits_invalid_id` |
| `update_user_credits(user_id, amount)` | 0 | Отрицательный баланс, конкурентный UPDATE, переполнение | `test_deduct_insufficient`, `test_concurrent_deduct` |
| `calculate_price(model, params)` | 0 | Неизвестная модель, все комбинации quality+model, границы | `test_price_kling_pro`, `test_price_unknown_model` |
| `parse_callback_data(data: str)` | 0 | Пустая строка, битые данные, инъекция, лимит длины | `test_parse_valid`, `test_parse_empty`, `test_parse_overflow` |
| `build_kie_payload(prompt, model, params)` | 0 | Пустой prompt, prompt > 5000 символов, все поля | `test_payload_minimal`, `test_payload_full`, `test_payload_empty_prompt` |
| `validate_prompt(text: str)` | 0 | Пустой, только пробелы, XSS, спецсимволы, эмодзи | `test_validate_empty`, `test_validate_xss`, `test_validate_emoji` |
| `validate_aspect_ratio(ratio: str)` | 0 | Все допустимые значения, недопустимые, пустой | `test_aspect_ratio_valid`, `test_aspect_ratio_invalid` |
| `generate_referral_code(user_id)` | 0 | Коллизия кодов, длина | `test_referral_code_unique`, `test_referral_code_length` |
| `calculate_referral_bonus(amount)` | 0 | 0, отрицательное, дробное, большая сумма | `test_bonus_zero`, `test_bonus_negative` |
| `parse_api_response(response_text)` | 0 | Пустой ответ, HTML вместо JSON, неполный JSON | `test_parse_empty`, `test_parse_html_error`, `test_parse_malformed` |
| `format_user_message(template, **kwargs)` | 0 | Отсутствие переменной, экранирование Markdown | `test_format_missing_var`, `test_format_markdown_escape` |
| `transition_task_status(current, new)` | 0 | Недопустимый переход (completed → processing), цикл | `test_invalid_transition`, `test_all_valid_transitions` |
| `serialize_task_for_miniapp(task)` | 0 | task без result_url, task в processing | `test_serialize_pending`, `test_serialize_completed` |

---

## 10. Integration / E2E Test Gaps

| Flow | Missing Test | Mock / Data Needed | Expected Result |
|------|-------------|-------------------|-----------------|
| Handler → service: выбор модели → create_task | `test_model_selection_to_task_creation` | Mock KlingService, FSM state | Задача создана, credits списаны |
| Handler → DB: payment webhook → balance update | `test_payment_webhook_to_balance` | Mock webhook payload | Баланс обновлён, транзакция записана |
| Service → external API: Kling create_task → response | `test_kling_api_create_task` | Mock aiohttp response | External task_id сохранён |
| Service → external API: API 429 → retry → success | `test_kling_429_retry` | Mock 429 response | Retry через N секунд |
| Service → external API: API 500 → failed → refund | `test_kling_500_refund` | Mock 500 response | Баланс возвращён, задача failed |
| Repository → DB: `deduct_credits + insert_task` | `test_deduct_and_create_atomic` | DB fixture | Rollback при ошибке insert |
| Frontend → Backend: mini-app get history | `test_miniapp_history_api` | Mock user session | Только свои задачи |
| Webhook → обработчик: Kie.ai callback success | `test_kie_webhook_success` | Mock Kie.ai webhook payload | Статус updated, пользователь уведомлён |
| Webhook → обработчик: Kie.ai callback error | `test_kie_webhook_error` | Mock Kie.ai error payload | Статус failed, credits returned |
| Webhook → идемпотентность: двойной callback | `test_webhook_idempotent` | Два одинаковых webhook'а | Второй игнорируется |
| Full E2E: пользователь → генерация → оплата → webhook | `test_e2e_generation_flow` | Полный мок окружения | Результат доставлен пользователю |
| Full E2E: ошибка API → refund | `test_e2e_error_refund` | Mock API 500 | Баланс восстановлен |

---

## 11. Security Findings

| ID | Severity | Finding | Evidence | Exploit Scenario | Fix | Test |
|----|----------|---------|----------|------------------|-----|------|
| SEC-01 | **CRITICAL** | Нет проверки Telegram initData в mini-app | `bot/miniapp.py` / webapp handler | Злоумышленник шлёт POST с поддельным `user_id` → backend принимает как легитимный запрос → доступ к любым данным/операциям от имени любого пользователя | Внедрить `validate_telegram_webapp_data(bot_token, init_data)` | `test_webapp_invalid_init_data_rejected` |
| SEC-02 | **CRITICAL** | Webhook Kie.ai без аутентификации | `callBackUrl` передаётся без HMAC-секрета | POST на webhook endpoint с `{"status":"completed","result_url":"https://evil.com/malware.exe"}` | Добавить `?secret=HMAC(task_id)` в callback_url и проверять | `test_kie_webhook_invalid_secret_rejected` |
| SEC-03 | **CRITICAL** | Lava webhook без проверки подписи | `bot/services/lava_service.py` — webhook handler без HMAC | Поддельный POST с `status=success` → начисление без оплаты | Добавить проверку HMAC-SHA256 согласно документации Lava | `test_lava_webhook_invalid_signature` |
| SEC-04 | **CRITICAL** | TBank webhook без проверки подписи | `tbank_payment/webhooks.py` — нет валидации | Аналогично Lava | Добавить проверку подписи уведомления согласно API TBank | `test_tbank_webhook_invalid_signature` |
| SEC-05 | **HIGH** | IDOR: доступ к чужим задачам и данным | `generation.py:check_task_status()` не проверяет `user_id` | Пользователь подменяет `task_id` в callback_data → видит чужие prompt'ы, результаты, URLs | `WHERE task.user_id = :current_user_id` во всех запросах | `test_cannot_access_other_user_task` |
| SEC-06 | **HIGH** | IDOR: админские callback'ы без универсальной проверки | Часть admin handler'ов не вызывает `is_admin()` | Обычный пользователь шлёт callback `admin` → если проверка не срабатывает, доступ к админке | Добавить middleware `is_admin` на admin_router | `test_non_admin_blocked_from_all_admin_callbacks` |
| SEC-07 | **MEDIUM** | SQL Injection через callback_data | `callback_data.split(":")` значение напрямую вставляется в SQL запросы с f-strings | Злоумышленник создаёт callback с `task_id="1; DROP TABLE users;--"` | Использовать параметризованные запросы (уже частично через `?` placeholders) | `test_sql_injection_callback_data` |
| SEC-08 | **MEDIUM** | Отсутствие rate limiting на API/webhook | Нет throttling на webhook endpoint'ах | Перебор ID задач / DDoS webhook endpoint | Redis rate limiter | `test_webhook_rate_limit` |
| SEC-09 | **MEDIUM** | `user_facing_errors.py` не используется → технические ошибки утекают пользователю | `generation.py:except Exception: await msg.answer(str(e))` | Пользователь видит стектрейс/внутренние URL/ключи API в сообщении об ошибке | Использовать `UserFacingError` маппинг | `test_error_message_no_internal_data` |
| SEC-10 | **LOW** | `.env` — потенциально в репозитории | Не проверено, но типичная проблема | `git show .env` | Добавить `.env` в `.gitignore` (возможно уже есть) | Проверить `.gitignore` |
| SEC-11 | **INFO** | CORS для webhook не настроен (но webhook — machine-to-machine) | `bot/main.py` aiohttp app | Не критично для webhook, но нужно для mini-app API | Настроить CORS только для mini-app endpoint | — |

---

## 12. План исправлений

### Срочно — P0 (перед любым релизом)

| # | Что исправить | Почему | Файлы | Тест |
|---|--------------|--------|-------|------|
| 1 | Атомарное обновление баланса | Деньги: двойное списание | `bot/database.py` | `test_atomic_balance_update` |
| 2 | Идемпотентность всех webhook'ов | Деньги: двойное начисление | `yookassa_service.py`, `cryptobot_service.py`, `lava_service.py`, `tbank_payment/webhooks.py` | `test_webhook_idempotent` |
| 3 | Возврат credits при ошибке API | Деньги: потеря средств пользователя | `bot/handlers/generation.py` | `test_error_refund` |
| 4 | Проверка initData в mini-app | Безопасность: подмена пользователя | `bot/miniapp.py`, `bot/main.py` | `test_webapp_auth` |
| 5 | Аутентификация Kie.ai webhook | Безопасность: поддельный результат | `bot/main.py`, все Kie-сервисы | `test_kie_webhook_auth` |
| 6 | Проверка подписи Lava webhook | Деньги/безопасность | `bot/services/lava_service.py` | `test_lava_signature` |
| 7 | Проверка подписи TBank webhook | Деньги/безопасность | `tbank_payment/webhooks.py` | `test_tbank_signature` |
| 8 | Проверка `user_id` при доступе к задаче | Безопасность/конфиденциальность | `bot/handlers/generation.py`, `admin.py` | `test_task_access_control` |
| 9 | DB transaction для deduct+insert | Целостность данных | `bot/handlers/generation.py` | `test_deduct_insert_atomic` |
| 10 | Pydantic `.required()` для всех обязательных env | Предотвращение невнятных ошибок | `bot/config.py` | `test_config_validation` |
| 11 | Фоновый polling зависших задач | Предотвращение stuck processing | Новый `bot/services/task_watchdog.py` | `test_watchdog_recovers_stuck` |
| 12 | UNIQUE constraint на `provider_payment_id` | Защита от дублей | `bot/database.py`, `schema_postgres.sql` | `test_unique_payment_id` |

### Следом — P1

| # | Что | Файлы |
|---|------|-------|
| 1 | `split(":")` → `split(":", 1)` в callback парсинге | `bot/handlers/generation.py` |
| 2 | Проверка is_admin во всех admin handler'ах | `bot/handlers/admin.py` |
| 3 | Retry logic (tenacity) для всех внешних API | Все `bot/services/*_service.py` |
| 4 | Correlation ID в логах | Все handler'ы и сервисы |
| 5 | Унификация `callBackUrl` во всех Kie-сервисах | `bot/services/*_service.py` |
| 6 | Self-referral prevention | `bot/services/referral_service.py` |
| 7 | UNIQUE на referral bonus | `bot/database.py` |
| 8 | Индекс на `external_task_id` | `bot/database.py` |
| 9 | Валидация размера файла | `bot/handlers/common.py` |
| 10 | Пагинация истории задач | `bot/handlers/generation.py`, `frontend/...` |

### Потом — P2/P3

- Redis-кэширование результатов
- Rate limiting
- Graceful shutdown
- Dockerfile
- CI/CD (GitHub Actions)
- Удалить мёртвый код (`*_copy.py`)
- i18n
- C4 architecture diagram
- Замена `Dict[str, Any]` на TypedDict/Pydantic
- Аналитика и мониторинг

---

## 13. Готовые тесты (предложения)

### 13.1 Unit-тесты (pytest)

```python
# test_balance.py
import pytest
from bot.database import get_user_credits, update_user_credits

@pytest.mark.asyncio
async def test_get_credits_new_user_returns_zero():
    """Новый пользователь должен иметь 0 credits."""
    credits = await get_user_credits(telegram_id=999999)
    assert credits == 0

@pytest.mark.asyncio
async def test_deduct_insufficient_balance_raises():
    """Нельзя списать больше, чем есть."""
    await update_user_credits(telegram_id=1, amount=50)  # set 50
    with pytest.raises(InsufficientBalanceError):
        await deduct_credits(telegram_id=1, amount=100)

@pytest.mark.asyncio
async def test_concurrent_deduct_no_double_spend():
    """Два параллельных списания не должны создать отрицательный баланс."""
    await update_user_credits(telegram_id=1, amount=50)
    await asyncio.gather(
        deduct_credits(telegram_id=1, amount=40),
        deduct_credits(telegram_id=1, amount=40),
    )
    balance = await get_user_credits(telegram_id=1)
    assert balance >= 0

# test_payload.py
def test_build_kie_payload_with_empty_prompt_raises():
    with pytest.raises(ValidationError):
        build_kie_payload(prompt="", model="kling")

def test_build_kie_payload_full():
    payload = build_kie_payload(prompt="test", model="kling", aspect_ratio="16:9", duration=5)
    assert payload["prompt"] == "test"
    assert payload["model"] == "kling"
    assert payload["aspect_ratio"] == "16:9"

# test_referral.py
def test_referral_code_generation_unique():
    code1 = generate_referral_code(user_id=1)
    code2 = generate_referral_code(user_id=2)
    assert code1 != code2

def test_self_referral_blocked():
    with pytest.raises(SelfReferralError):
        process_referral(referrer_id=1, referred_user_id=1)

# test_callbacks.py
def test_parse_callback_valid():
    action, task_id = parse_callback_data("check_task:42")
    assert action == "check_task"
    assert task_id == 42

def test_parse_callback_empty():
    with pytest.raises(InvalidCallbackError):
        parse_callback_data("")

def test_parse_callback_malformed():
    with pytest.raises(InvalidCallbackError):
        parse_callback_data("garbage_without_colon")

# test_task_lifecycle.py
def test_invalid_status_transition():
    with pytest.raises(InvalidStatusTransition):
        transition_task_status("completed", "processing")

def test_valid_transitions():
    assert transition_task_status("pending", "processing") == "processing"
    assert transition_task_status("processing", "completed") == "completed"
    assert transition_task_status("processing", "failed") == "failed"
```

### 13.2 Integration-тесты

```python
# test_integration_generation.py
@pytest.mark.asyncio
async def test_generation_handler_deducts_and_creates_task(mock_kling_api, db_session, fsm_context):
    """Handler генерации списывает credits и создаёт задачу атомарно."""
    await update_user_credits(telegram_id=1, amount=100)
    
    message = MockMessage(chat=MockChat(id=1), from_user=MockUser(id=1))
    state = MockFSMContext(data={"model": "kling", "prompt": "test"})
    
    await process_generation(message, state)
    
    task = await get_last_task(user_id=1)
    assert task.status == "processing"
    assert task.external_task_id is not None
    balance = await get_user_credits(telegram_id=1)
    assert balance < 100  # списано

@pytest.mark.asyncio
async def test_kling_500_returns_credits(mock_kling_500, db_session):
    """Ошибка внешнего API возвращает credits."""
    await update_user_credits(telegram_id=1, amount=100)
    
    with pytest.raises(KlingAPIError):
        await kling_service.create_task(prompt="test", user_id=1)
    
    # Проверяем, что баланс восстановлен
    balance = await get_user_credits(telegram_id=1)
    assert balance == 100

# test_integration_webhooks.py
@pytest.mark.asyncio
async def test_yookassa_webhook_idempotent(db_session):
    """Повторный webhook не начисляет дважды."""
    await update_user_credits(telegram_id=1, amount=0)
    webhook_data = {"object": {"id": "payment_123", "status": "succeeded", "amount": {"value": "100.00"}}}
    
    await process_yookassa_webhook(webhook_data)
    balance_after_first = await get_user_credits(telegram_id=1)
    
    await process_yookassa_webhook(webhook_data)  # повторный
    balance_after_second = await get_user_credits(telegram_id=1)
    
    assert balance_after_first == balance_after_second  # не изменился

@pytest.mark.asyncio
async def test_kie_webhook_invalid_secret_rejected():
    """Webhook с неверным HMAC отклоняется."""
    response = await send_kie_webhook(task_id="123", status="completed", secret="wrong")
    assert response.status_code == 403

# test_integration_access.py
@pytest.mark.asyncio
async def test_user_cannot_access_others_tasks():
    """Пользователь не видит чужую задачу."""
    await create_task(user_id=1, task_id=100)
    await create_task(user_id=2, task_id=200)
    
    # Пользователь 1 пытается получить задачу 200
    result = await get_task(task_id=200, requesting_user_id=1)
    assert result is None  # или AccessDenied
```

### 13.3 E2E-тесты (pytest + mock)

```python
# test_e2e_generation.py
@pytest.mark.asyncio
async def test_e2e_happy_path(mock_all_external_apis):
    """Полный happy path: пользователь → генерация → результат."""
    # 1. /start → регистрация
    user = await simulate_start(telegram_id=1)
    assert user is not None
    
    # 2. Пополнение баланса
    await simulate_payment(telegram_id=1, amount=100)
    balance = await get_user_credits(telegram_id=1)
    assert balance == 100
    
    # 3. Выбор модели и создание генерации
    await simulate_model_selection(telegram_id=1, model="kling")
    task = await simulate_generation(telegram_id=1, prompt="test")
    assert task.status == "processing"
    assert task.external_task_id is not None
    
    # 4. Списание
    balance_after = await get_user_credits(telegram_id=1)
    assert balance_after < 100
    
    # 5. Webhook success
    await simulate_kie_webhook(external_task_id=task.external_task_id, status="completed")
    task_updated = await get_task(task.id)
    assert task_updated.status == "completed"
    assert task_updated.result_url is not None

@pytest.mark.asyncio
async def test_e2e_error_with_refund(mock_kling_500):
    """Ошибка API → задача failed → возврат средств."""
    await update_user_credits(telegram_id=1, amount=100)
    
    # Генерация падает с ошибкой
    task = await simulate_generation_with_error(telegram_id=1, prompt="test")
    assert task.status == "failed"
    
    # Баланс восстановлен
    balance = await get_user_credits(telegram_id=1)
    assert balance == 100
```

### 13.4 Security-тесты

```python
# test_security.py
def test_webapp_init_data_validation():
    """Поддельный initData отклоняется."""
    fake_init_data = "user=%7B%22id%22%3A123%7D&hash=invalid"
    with pytest.raises(InvalidInitDataError):
        validate_telegram_webapp_data(bot_token=TEST_TOKEN, init_data=fake_init_data)

def test_admin_routes_blocked_for_user():
    """Обычный пользователь не может вызвать admin callback."""
    callback = CallbackQuery(data="admin", from_user=MockUser(id=1, is_admin=False))
    # Должен быть заблокирован middleware или handler'ом
    result = await process_admin_callback(callback)
    assert result.blocked is True

def test_webhook_signature_required():
    """Webhook без подписи отклоняется."""
    response = await client.post("/webhook/lava", json={"status": "success"})
    assert response.status_code == 401 or response.status_code == 403
```

### 13.5 Smoke-тест

```python
# test_smoke.py
def test_imports():
    """Все модули импортируются без ошибок."""
    import bot
    import bot.main
    import bot.config
    import bot.handlers
    import bot.handlers.admin
    import bot.handlers.common
    import bot.handlers.generation
    import bot.handlers.payments
    import bot.services.kling_service
    import bot.services.yookassa_service
    # ... all modules

def test_config_loads():
    """Конфигурация загружается из env."""
    from bot.config import Config
    config = Config()
    assert config.BOT_TOKEN is not None
    assert config.KIE_API_KEY is not None

@pytest.mark.asyncio
async def test_healthcheck():
    """Healthcheck endpoint возвращает 200."""
    response = await client.get("/healthcheck")
    assert response.status_code == 200
```

---

## 14. Минимальный набор команд

```bash
# Установка зависимостей
pip install -r requirements.txt
pip install pytest pytest-asyncio pytest-mock pytest-cov

# Линтинг
pip install ruff
ruff check bot/ frontend/

# Type checking
pip install mypy
mypy bot/ --ignore-missing-imports

# Unit-тесты
pytest tests/unit/ -v --asyncio-mode=auto

# Integration-тесты
pytest tests/integration/ -v --asyncio-mode=auto

# E2E-тесты
pytest tests/e2e/ -v --asyncio-mode=auto

# Smoke-тест
pytest tests/smoke/ -v

# Coverage
pytest tests/ --cov=bot --cov-report=html --cov-report=term

# Security scan
pip install bandit safety
bandit -r bot/
safety check -r requirements.txt
```

**Что добавить в CI (GitHub Actions):**
```yaml
name: CI
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    services:
      redis:
        image: redis
        ports: ['6379:6379']
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.11' }
      - run: pip install -r requirements.txt
      - run: pip install pytest pytest-asyncio pytest-mock pytest-cov ruff bandit
      - run: ruff check bot/
      - run: bandit -r bot/ --skip B101
      - run: pytest tests/ -v --cov=bot --cov-report=xml
      - run: safety check -r requirements.txt
```

---

## 15. Финальный вердикт

| Вопрос | Ответ |
|--------|-------|
| **Готово к production?** | **НЕТ** |
| **Главная причина** | Отсутствие защиты от двойного списания, неидемпотентные webhook'и, отсутствие проверки подлинности mini-app запросов и webhook'ов внешних API |
| **Топ-5 исправлений перед релизом** | 1. Транзакционное обновление баланса 2. Идемпотентность всех webhook'ов 3. Возврат credits при ошибке API 4. Проверка initData в mini-app 5. Аутентификация webhook'ов Kie.ai/Lava/TBank |
| **Минимальный test suite перед merge** | 12 unit-тестов (баланс, payload, referral, lifecycle) + 8 integration-тестов (webhook, generation, access) + 2 smoke-теста |
| **Что проверить вручную** | Полный smoke-checklist (раздел 7) — 20 пунктов, особенно S11-S14 (генерация + платежи) |
| **Что автоматизировать в CI** | Lint (ruff) → Typecheck (mypy) → Unit tests → Integration tests → Security scan (bandit) → Coverage report |

---

**Аудит завершён.** Найдено: **12 критических (P0)**, **28 высоких (P1)**, **19 средних (P2)**, **8 низких (P3)** дефектов. **0 тестов** в репозитории. Рекомендуется немедленное исправление всех P0 перед любым запуском на реальных пользователях.