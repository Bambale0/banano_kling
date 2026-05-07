# 2Loop

`2Loop` — это Telegram-бот и набор связанных веб-интерфейсов для двух задач:

1. AI-генерация изображений и видео для фигурного катания и смежных сценариев.
2. Мини-магазин аксессуаров 2Loop с каталогом, промокодами, заказами и Telegram Mini App.

По коду видно, что проект уже вырос из "одного бота" в гибридную платформу: здесь есть `aiogram`, `aiohttp`, SQLite, Excel-каталог, React mini app, webhook-интеграции и платёжные провайдеры.

## Что умеет проект

- Генерация изображений через Gemini / Nano Banana / Seedream / Flux-подобные провайдеры.
- Генерация видео и motion control через Kling / Kie.ai / Replicate / Grok / Aleph.
- Работа с референсами:
  - до 14 референсных изображений;
  - до 5 референсных видео для части video-flow.
- Анализ фото в промпт.
- Batch-редактирование изображений.
- Пополнение баланса через YooKassa и Robokassa.
- Партнёрская и реферальная логика.
- Telegram Mini App c простым storefront/API.
- Веб-каталог `/shop` на основе `data/catalog.xlsx`.
- Админские инструменты для статистики и управления магазином.

## Архитектура

```text
Telegram user
   |
   v
aiogram routers
   |
   +--> generation / payments / admin / catalog / image analyzer
   |
   v
aiohttp server in bot/main.py
   |
   +--> Telegram webhook
   +--> payment webhooks
   +--> AI provider webhooks
   +--> /shop catalog webapp
   +--> /api/miniapp/*
   +--> static files / uploads
   |
   v
Storage layer
   +--> SQLite (users, payments, tasks, analytics, shop orders)
   +--> JSON files for miniapp storage
   +--> Excel catalog for storefront source data
   +--> static/uploads and static/shop assets
```

## Ключевой вывод по проекту

Сейчас в репозитории одновременно живут две магазинные линии:

- `bot/catalog_webapp.py` + `static/shop/` + `data/catalog.xlsx`  
  Веб-каталог на базе Excel, с оверрайдами и заказами в SQLite.

- `bot/miniapp_api.py` + `miniapp/`  
  Telegram Mini App с отдельным JSON-хранилищем (`data/products.json`, `data/orders.json`, `data/settings.json`).

Это важно учитывать при доработках: магазин в проекте не один, а два частично пересекающихся слоя.

## Структура репозитория

```text
.
├── bot/
│   ├── main.py                  # Точка входа: bot + aiohttp + webhook routes
│   ├── config.py                # Конфигурация из env
│   ├── database.py              # SQLite, миграции и доступ к данным
│   ├── states.py                # FSM состояния aiogram
│   ├── keyboards.py             # Inline keyboards
│   ├── catalog_webapp.py        # Веб-каталог /shop и API каталога
│   ├── miniapp_api.py           # API для Telegram Mini App
│   ├── handlers/                # Пользовательские сценарии
│   ├── middleware/              # Middleware для подписки и др.
│   ├── services/                # AI, платежи, доставка, batch и т.д.
│   └── utils/                   # Валидаторы, тексты, инструкции
├── data/
│   ├── price.json               # Пакеты GOE и справочник стоимости
│   ├── catalog.xlsx             # Исходник каталога магазина
│   ├── runway_characters.json   # Справочные данные для video flows
│   ├── orders.json              # JSON-хранилище miniapp
│   ├── products.json            # JSON-хранилище miniapp
│   └── settings.json            # JSON-хранилище miniapp
├── miniapp/                     # React/Vite исходники Telegram Mini App
├── static/
│   ├── shop/                    # Статический storefront и фото товаров
│   └── uploads/                 # Пользовательские загрузки и временные файлы
├── tests/                       # Unit/integration/standalone tests
├── docs/                        # Документация по интеграциям и миграциям
├── start.sh / stop.sh           # Локальный запуск и остановка
└── setup_*.sh                   # Инфраструктурные и миграционные helper scripts
```

## Основные модули

### `bot/main.py`

Главная точка входа проекта:

- загружает `.env`;
- инициализирует БД;
- собирает `Dispatcher`;
- поднимает `aiohttp`-сервер;
- регистрирует webhook routes;
- раздаёт `/static/` и `/uploads/`;
- запускает периодическую очистку `static/uploads` раз в 6 часов.

### `bot/database.py`

Фактически это и слой доступа к данным, и слой миграций. Здесь:

- создаются таблицы;
- выполняются `ALTER TABLE` для старых БД;
- хранятся пользовательские кредиты и транзакции;
- пишутся generation tasks;
- живут рефералка, партнёрка, аналитика и магазинные заказы.

### `bot/handlers/`

- `common.py` — `/start`, возврат после оплаты, меню, партнёрка, deep links.
- `generation.py` — основной AI UX для image/video/motion flows.
- `payments.py` — выбор пакета, создание платежа, webhook-обработка.
- `admin.py` — статистика и редактирование магазинных данных.
- `catalog.py` — пользовательский поток каталога и WebApp-заказов.
- `batch_generation.py` — пакетное редактирование по референсам.
- `image_analyzer.py` — фото -> промпт.

### `bot/services/`

Основные интеграции:

- `gemini_service.py` — Gemini/Nano Banana image flows.
- `kling_service.py` — Kling/Kie.ai/Replicate video flows.
- `seedream_service.py` — Seedream image generation.
- `grok_service.py` — часть video/image сценариев.
- `yookassa_service.py`, `robokassa_service.py` — платежи.
- `preset_manager.py` — чтение пакетов и стоимости из `data/price.json`.
- `delivery_service.py` — пока заглушка под будущие интеграции доставки.

### `bot/catalog_webapp.py`

Поднимает storefront `/shop` и API каталога:

- читает товары из `data/catalog.xlsx`;
- накладывает DB-оверрайды по фото, цене, остаткам;
- сохраняет shop-заказы в SQLite;
- может уведомлять админов о заказе через бота.

### `bot/miniapp_api.py`

API для Mini App:

- верифицирует `X-Telegram-Init-Data`;
- управляет товарами и настройками;
- принимает заказы;
- пишет данные в JSON-файлы;
- различает admin/non-admin пользователей.

## HTTP routes

### Системные и webhook routes

| Route | Назначение |
| --- | --- |
| `POST {WEBHOOK_PATH}` | webhook Telegram |
| `POST /yookassa/webhook` | webhook YooKassa |
| `POST /robokassa/result` | webhook Robokassa |
| `GET /robokassa/result` | fallback/result check |
| `GET /robokassa/success` | success redirect |
| `POST /webhook/kling` | webhook AI/video задач |
| `POST {KIE_AI_WEBHOOK_PATH}` | webhook Kie.ai |
| `GET /health` | health check |

### Storefront routes

| Route | Назначение |
| --- | --- |
| `GET /shop` | storefront магазина |
| `GET /api/catalog` | JSON каталога |
| `POST /api/shop/order` | заказ из web-каталога |

### Mini App routes

| Route | Назначение |
| --- | --- |
| `GET /api/miniapp/health` | health |
| `GET /api/miniapp/me` | Telegram user + admin status |
| `GET /api/miniapp/products` | список товаров |
| `POST /api/miniapp/products` | создание товара |
| `PUT /api/miniapp/products/{id}` | обновление товара |
| `DELETE /api/miniapp/products/{id}` | удаление товара |
| `POST /api/miniapp/products/{id}/images` | загрузка изображения |
| `GET /api/miniapp/settings` | настройки miniapp |
| `PUT /api/miniapp/settings` | обновление настроек |
| `POST /api/miniapp/promo` | применение промокода |
| `POST /api/miniapp/orders` | создание заказа |
| `GET /api/miniapp/orders` | список заказов |

## Данные и хранение

### SQLite

Ключевые таблицы, которые создаёт `bot/database.py`:

- `users`
- `transactions`
- `generation_tasks`
- `generation_history`
- `user_settings`
- `referrals`
- `partner_withdrawals`
- `batch_jobs`
- `analytics_events`
- `shop_product_overrides`
- `shop_product_images`
- `shop_orders`
- `shop_order_items`

### JSON-файлы

Используются mini app API:

- `data/products.json`
- `data/orders.json`
- `data/settings.json`

### Excel

`data/catalog.xlsx` — источник товарной матрицы для `/shop`.

### Static storage

- `static/shop/` — витрина и картинки товаров.
- `static/uploads/` — пользовательские загрузки, временные input/output файлы.

## Платёжная модель

Баланс внутри бота измеряется в `GOE`. Пакеты и стоимость лежат в `data/price.json`.

Сейчас в коде поддерживаются:

- `YooKassa`
- `Robokassa`

Выбор провайдера зависит от env-конфига и реально заполненных ключей.

## Реферальная и партнёрская логика

В проекте уже есть:

- реферальные deep links через `/start ref_*`;
- бонус за регистрацию;
- бонус за первую оплату реферала;
- партнёрские уровни и баланс;
- заявки на вывод.

Отдельный нюанс: в `bot/database.py` есть концепция `MASTER_PARTNER_TELEGRAM_ID`, и часть логики завязана на центрального партнёра.

## Конфигурация через env

Ниже перечислены основные переменные. В репозитории сейчас **нет** готового `.env.example`, поэтому `.env` нужно создать вручную.

### Обязательные для базового запуска

```env
BOT_TOKEN=
WEBHOOK_HOST=
WEBHOOK_PATH=/webhook
WEBHOOK_PORT=8443
ADMIN_IDS=
DATABASE_PATH=bot.db
```

### Платежи

```env
PAYMENT_PROVIDER=yookassa

YOOKASSA_SHOP_ID=
YOOKASSA_SECRET_KEY=
YOOKASSA_RETURN_URL=
YOOKASSA_WEBHOOK_SECRET=

ROBOKASSA_MERCHANT_LOGIN=
ROBOKASSA_PASSWORD1=
ROBOKASSA_PASSWORD2=
ROBOKASSA_TEST=0
BOT_USERNAME=
```

### AI провайдеры

```env
NANOBANANA_API_KEY=
GEMINI_API_KEY=
FREEPIK_API_KEY=
NOVITA_API_KEY=
KIE_AI_API_KEY=
KIE_AI_WEBHOOK_PATH=/webhook/kie_ai
KIE_BASE_URL=https://api.kie.ai
REPLICATE_API_TOKEN=
REPLICATE_WEBHOOK_SECRET=
KLING_API_KEY=
PIAPI_API_KEY=
ALLOW_NSFW=0
```

### Партнёрка

```env
MASTER_PARTNER_TELEGRAM_ID=339795159
PARTNER_OFFER_URL=
PARTNER_RULES_URL=
PARTNER_MIN_WITHDRAWAL_RUB=2000
```

### Mini App

```env
TWOLOOP_DATA_DIR=/root/2loop/data
TWOLOOP_UPLOAD_DIR=static/uploads/2loop
TWOLOOP_VERIFY_INIT_DATA=1
TWOLOOP_ADMIN_IDS=${ADMIN_IDS}
TWOLOOP_ORDER_NOTIFY_CHAT_IDS=${ADMIN_IDS}
```

## Важное замечание по конфигу

В коде одновременно фигурируют `DATABASE_URL` и `DATABASE_PATH`, но реальная SQLite-логика в `bot/database.py` использует именно `DATABASE_PATH`. Для практической настройки проекта ориентироваться нужно на него.

## Локальный запуск

### 1. Python-зависимости

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Создать `.env`

Минимально:

```env
BOT_TOKEN=...
WEBHOOK_HOST=https://your-domain.example
WEBHOOK_PATH=/webhook
WEBHOOK_PORT=8443
ADMIN_IDS=123456789
DATABASE_PATH=bot.db
```

### 3. Запустить бот

Вариант через helper script:

```bash
./start.sh
```

Или напрямую:

```bash
python -m bot.main
```

### 4. Остановить

```bash
./stop.sh
```

## Mini App разработка

Исходники лежат в `miniapp/`.

```bash
cd miniapp
npm install
npm run dev
```

Сборка:

```bash
cd miniapp
npm run build
```

Деплой этого фронтенда в текущем репозитории частично автоматизируется helper-скриптами `setup_2loop_miniapp.sh` и `setup_2loop_go2.sh`.

## Каталог магазина

Поток магазина сейчас устроен так:

1. Excel-каталог хранится в `data/catalog.xlsx`.
2. `bot/catalog_webapp.py` читает его и строит JSON-каталог.
3. Таблицы `shop_product_overrides` и `shop_product_images` дополняют Excel:
   - свои фото;
   - override по цене;
   - override по остаткам;
   - скрытие товара.
4. Заказы попадают в `shop_orders` и `shop_order_items`.

Это хороший компромисс для быстрого бизнеса, но при развитии проекта почти наверняка захочется единый источник истины по товарам.

## Полезные скрипты

| Файл | Назначение |
| --- | --- |
| `start.sh` | локальный запуск бота |
| `stop.sh` | остановка локального процесса |
| `set_webhook.py` | ручная установка Telegram webhook |
| `setup_2loop_miniapp.sh` | разворачивание miniapp-связки |
| `setup_2loop_go2.sh` | донастройка miniapp/go2-потока |
| `fix_2loop_nginx_8444.sh` | nginx/webhook helper |
| `fix_webhook_route.sh` | исправление webhook route |
| `scripts/poll_yookassa_pending.py` | опрос зависших платежей |
| `scripts/update_cloudflare_conf.sh` | генерация Cloudflare real IP conf |

## Тесты

В репозитории есть набор unit/integration тестов:

- `tests/test_config.py`
- `tests/test_database.py`
- `tests/test_keyboards.py`
- `tests/test_referral_system.py`
- `tests/test_webhook_handler.py`
- и несколько standalone-тестов для отдельных сервисов

Запуск:

```bash
pytest
```

Или точечно:

```bash
pytest tests/test_config.py tests/test_database.py
```

## Что важно знать перед доработками

### 1. Проект находится в переходном состоянии

Есть старые и новые магазинные сценарии, backup-файлы, setup-скрипты миграций и несколько слоёв документации. Перед крупным рефакторингом лучше сначала решить, какой storefront остаётся основным.

### 2. Хранилище раздвоено

- AI, платежи, аналитика и заказы web-каталога — в SQLite.
- Mini app товары/настройки/заказы — в JSON.
- Каталог товаров — в Excel.

Для быстрой разработки это работает, но усложняет консистентность данных.

### 3. Документация и инфраструктура частично устарели

По текущему коду видно несколько признаков drift:

- старый `README` не соответствовал реальной структуре;
- `start.sh` ожидает `.env.example`, которого нет в репозитории;
- `nginx.conf.example` стоит перепроверить перед продом;
- часть setup-скриптов патчит код, а не только инфраструктуру.

### 4. `database.py` очень нагружен ответственностью

Там одновременно:

- схемы таблиц;
- миграции;
- бизнес-логика;
- аналитика;
- магазин;
- партнёрка.

Это один из главных кандидатов на декомпозицию при следующем этапе развития.

## Файлы, которые стоит смотреть в первую очередь

- `bot/main.py`
- `bot/config.py`
- `bot/database.py`
- `bot/handlers/generation.py`
- `bot/handlers/payments.py`
- `bot/catalog_webapp.py`
- `bot/miniapp_api.py`
- `data/price.json`
- `tests/`

## Лицензия

См. файл `LICENSE`.
