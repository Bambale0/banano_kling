# Архитектура NEUROMIX

## 1. Назначение системы

NEUROMIX объединяет Telegram-бота, Telegram Mini App, сервисы генерации, платежные интеграции, публикацию контента и административные маршруты.

Backend работает как единый Python runtime на `aiohttp` и подключает `aiogram`. Frontend Mini App собирается отдельно как статический Next.js export и не требует Node.js runtime в production.

## 2. Production topology

Сверено 2026-10-07; DNS и TLS проверены без изменения инфраструктуры.

```text
Пользователь Telegram
  -> https://tanyapp.xn--e1aikcel5c5a.online/mini-app/
     Nginx на 144.76.188.75
       /mini-app/       -> /var/www/tanyapp.xn--e1aikcel5c5a.online/mini-app
       /mini-app/api/*  -> backend 127.0.0.1:1888
       /uploads/*       -> backend static/uploads
       /genjutsu/*      -> подписанные media/callback handlers backend

https://tanyapi.chillcreative.ru
  -> тот же backend; Telegram/provider/payment webhooks сохраняют этот origin
  -> Docker banano-kling-bot, compose service bot
```

Новый frontend и публичные media используют общий origin. Локальный backend port не требуется открывать в интернет. `cdn.chillcreative.ru` и `media.chillcreative.ru` относятся к прежней separate-host/Cloudflare схеме; старые upload URL поддерживаются как входы и нормализуются к `STATIC_BASE_URL`. Это не означает удаления старых DNS records или переписывания истории в БД.

## 3. Backend runtime

Ключевой entrypoint: `bot/main.py`.

Runtime отвечает за:

- Telegram webhook;
- Mini App API;
- payment webhooks;
- provider webhooks;
- health endpoints;
- internal API;
- регистрацию routers;
- запуск background loops;
- graceful startup/shutdown.

Production service:

```text
banano-kling.service
```

Production checkout:

```text
/root/tanya/banano_kling
```

Рабочая ветка:

```text
tanyapi
```

## 4. Telegram-бот и FSM

Ключевые каталоги и файлы:

- `bot/states.py` — FSM states;
- `bot/keyboards.py` — inline/reply keyboards;
- `bot/handlers/common.py` — общие команды и стартовые сценарии;
- `bot/handlers/generation.py` — генерация;
- `bot/handlers/payments.py` — платежные сценарии;
- `bot/handlers/admin.py` — администрирование;
- `bot/handlers/image_analyzer.py` — анализ изображений;
- `bot/handlers/batch_generation.py` — пакетные сценарии;
- `bot/handlers/support.py` — поддержка.

Общий поток:

```text
Telegram update
  -> router/handler
  -> FSM state и FSM data
  -> validation
  -> database/service call
  -> provider/payment side effect
  -> user response
```

Redis используется для FSM/cache, когда доступен. При отказе Redis runtime может перейти на in-memory storage, что допустимо как аварийный fallback, но не обеспечивает сохранение FSM после restart.

## 5. Mini App backend

Ключевой файл: `bot/miniapp.py`.

Backend Mini App отвечает за:

- проверку Telegram `initData`;
- bootstrap пользователя, моделей, баланса и истории;
- загрузку файлов;
- запуск image/video/motion generation;
- task detail и историю;
- feed, trends, prompt library и profile routes;
- публикацию и удаление публикаций;
- создание платежей;
- AI assistant;
- media gateway для отдельных временных provider URL;
- browser auth fallback.

### Авторизация внутри Telegram

1. Telegram WebView открывает Mini App.
2. Telegram Web App JS предоставляет `initData`.
3. Frontend ждёт `initData` ограниченное время и показывает загрузчик.
4. `POST /mini-app/api/bootstrap` отправляет авторизационные данные backend.
5. Backend проверяет подпись и пользователя.
6. После успешного bootstrap приложение переходит в live mode.

Отсутствие `initData` при ручном `curl` должно приводить к `400/401/403`. Это ожидаемая граница авторизации.

### Browser auth fallback

При открытии не внутри Telegram frontend может показать Telegram Login Widget. Backend browser-auth route проверяет подпись Telegram Login, создаёт короткоживущий auth payload и перезагружает клиент с данными входа.

Browser fallback не должен заменять нормальный Telegram WebView flow.

## 6. Frontend Mini App

Каталог:

```text
frontend/miniapp-v0
```

Стек:

- Next.js 16;
- React 19;
- Tailwind CSS 4;
- static export;
- client-side state/context;
- dynamic imports для тяжёлых вкладок.

Основные файлы:

- `app/layout.tsx` — metadata, Telegram early-ready script;
- `components/mini-app-shell.tsx` — оболочка, loader/gate/live state;
- `components/mini-app-loader.tsx` — загрузчик до bootstrap;
- `components/telegram-open-gate.tsx` — browser/Telegram login fallback;
- `components/hero-header.tsx` — постоянный бренд NEUROMIX и статус;
- `lib/app-context.tsx` — bootstrap, state, sync и task polling;
- `lib/api.ts` — API client;
- `lib/brand.ts` — единый пользовательский бренд;
- `next.config.mjs` — export/basePath/assetPrefix.

### Frontend state machine

Упрощённо:

```text
initial locked + isLoading=true
          │
          ▼
MiniAppLoader
          │
          ├── Telegram initData получены -> bootstrap -> live UI
          │
          └── данные входа не получены -> TelegramOpenGate
```

Загрузчик имеет приоритет над gate, чтобы при медленном Telegram WebView пользователь не видел ложное сообщение об отсутствии авторизации.

### Branding

Пользовательский бренд задаётся через:

```text
frontend/miniapp-v0/lib/brand.ts
```

Названия моделей (`Nano Banana`, `Kling`, `Veo`, `Grok` и другие) остаются названиями внешних моделей. Они не заменяются на NEUROMIX.

## 7. Data layer

Ключевые файлы:

- `bot/database.py` — high-level async operations;
- `bot/db.py` — compatibility facade;
- `schema_postgres.sql` — PostgreSQL schema reference.

Основные сущности:

- users;
- transactions;
- generation tasks/history;
- settings;
- referrals and partner withdrawals;
- promo codes/redemptions;
- saved references;
- prompts and likes;
- feed items, likes, comments, remix/repeat events;
- batch jobs;
- Mini App notifications.

Доменные инварианты:

- одна задача не списывает баланс дважды;
- completed payment не начисляется повторно;
- task detail доступен только владельцу или разрешённому admin flow;
- webhook retry должен быть идемпотентным;
- публикация обновляет существующую запись, а не плодит дубли;
- приватные uploads не должны случайно получать публичный immutable cache.

## 8. Services layer

Каталог:

```text
bot/services/
```

Группы сервисов:

### Generation providers

- Kling family;
- Nano Banana family;
- Seedream/Seedance;
- GPT Image;
- Grok;
- Veo;
- Gemini/Omni;
- Wan и другие подключённые providers.

### Supporting services

- storage референсов;
- media validation;
- prompt generation;
- image/video analysis;
- rate limiting;
- task watchdog;
- Redis helpers;
- memory and backup helpers.

### Payments

В репозитории могут сохраняться активные и legacy integrations. Фактически используемый provider определяется конфигурацией и текущим кодом. Наличие модуля не означает, что provider включён в production.

## 9. Media architecture

### Фактическое хранилище

```text
/root/tanya/banano_kling/static/uploads
```

Backend уже сохраняет туда файлы и формирует URL `/uploads/...`.

Текущий vhost `tanyapp.xn--e1aikcel5c5a.online` проксирует `/uploads/` в backend, который читает это хранилище. Дополнительный Nginx bind mount не требуется для текущего пути. Исторический `/var/www/media.chillcreative.ru/uploads` и standalone installer сохраняются как legacy инфраструктура.

Genjutsu использует собственное приватное media storage и подписанные `/genjutsu/media/*` URL; callback routes имеют ту же `GENJUTSU_PUBLIC_BASE_URL`. Они не являются публично кешируемыми upload-файлами.

### Cache classes

#### Публичная лента

```text
/uploads/feed/*
```

Можно кешировать как immutable, если имена файлов уникальны и не перезаписываются.

#### WebP-превью

```text
/uploads/feed/thumbs/*.webp
```

Целевой размер превью: примерно 50–200 КБ. Превью используются в сетке вместо тяжёлых оригиналов.

#### Остальные uploads

По умолчанию `no-store`, если файлы могут быть приватными, временными или пользовательскими референсами.

### Legacy Cloudflare origin

`media.chillcreative.ru` ранее использовал Cloudflare и bind mount к тому же `static/uploads`. Он остаётся совместимым именем для сохранённых ссылок. Текущий canonical origin — `https://tanyapp.xn--e1aikcel5c5a.online`; его DNS был проверен как `144.76.188.75`, без утверждений о Cloudflare proxy/TTL. Старые Cloudflare headers и правила не являются критерием приёмки нового origin.

## 10. Deployment architecture

Production branch — `tanyapi`. Release проходит CI для точного SHA, затем production deployment и проверку фактически запущенной версии.

- Backend: Docker `banano-kling-bot`, compose service `bot`; checkout SHA сам по себе не доказывает running revision
- Frontend: статический Next.js export на `tanyapp.xn--e1aikcel5c5a.online`; старые hashed chunks сохраняются для Telegram WebView
- Media: выбранные public config fields `STATIC_BASE_URL` и `GENJUTSU_PUBLIC_BASE_URL` указывают на shared origin; обычные webhook origins не меняются
- Nginx: `/uploads/` и `/genjutsu/` уже присутствуют в live vhost; installer содержит такие же routes, но его выполнение и изменение сетевой конфигурации требуют отдельной проверки
- `cdn.sh --remote-deploy tanyafrontend` и `scripts/deploy_media_origin.sh` описывают legacy separate-host workflow, а не текущий обязательный production release step

## 11. Security boundaries

- Telegram `initData` проверяется на backend;
- Telegram Login Widget payload проверяется на backend;
- provider/payment webhooks проверяют signature/HMAC там, где это поддерживается;
- internal API не должен быть публичным без auth;
- secrets не логируются и не попадают в Git;
- backend runtime желательно слушает loopback;
- frontend proxy проверяет TLS upstream;
- media cache разрешён только для явно публичных путей;
- Nginx config применяется только после `nginx -t`.

## 12. Observability

Основные точки диагностики:

- Docker status/health и OCI revision контейнера `banano-kling-bot`;
- `logs/bot.log`, если file logging включён;
- frontend `/mini-app/` и существующий public asset `/mini-app/icon.svg`; `/frontend-health` на текущем vhost не настроен;
- backend `/health`;
- Nginx access/error logs активного vhost;
- legacy Cloudflare headers проверяются только при диагностике legacy host;
- frontend deploy log `/var/log/banano-miniapp-cdn.log`;
- npm logs в `/root/.npm/_logs` на frontend host.

## 13. Источники истины

- runtime wiring: `bot/main.py`;
- Mini App routes/contracts: `bot/miniapp.py`;
- configuration: `bot/config.py`;
- frontend API/state: `frontend/miniapp-v0/lib/api.ts`, `lib/app-context.tsx`;
- frontend deployment: `cdn.sh`, `scripts/install_miniapp_frontend_host.sh`, `scripts/install_miniapp_frontend_https_host.sh`;
- media deployment: `scripts/deploy_media_origin.sh`, `ops/media/nginx-media.conf`;
- pricing/models: `data/price.json`, `bot/services/preset_manager.py`;
- verified behavior: `tests/`.
