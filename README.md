# NEUROMIX

`NEUROMIX` — Telegram-бот и Telegram Mini App для генерации изображений и видео, работы с референсами, публикации контента, платежей, партнёрской программы и внутренних административных инструментов.

> Репозиторий исторически называется `banano_kling`, а в коде встречаются технические идентификаторы `banano-*`, `banana_*` и названия моделей семейства Nano Banana. Это внутренние и provider-идентификаторы. Пользовательский бренд продукта — **NEUROMIX**.

Документация в этой ветке относится только к `tanyapi` и актуальной production-схеме.

## Production-схема

| Компонент | Адрес | Сервер | Назначение |
| --- | --- | --- | --- |
| Telegram Mini App | `https://cdn.chillcreative.ru/mini-app/` | `91.200.84.187` | Статический Next.js export и reverse proxy к API |
| Backend API | `https://tanyapi.chillcreative.ru` | `144.76.188.75` | Telegram webhook, Mini App API, webhooks провайдеров и платежей |
| Media origin/CDN | `https://media.chillcreative.ru/uploads/...` | `144.76.188.75` через Cloudflare | Nginx-раздача существующей папки `static/uploads` |
| Backend checkout | — | `144.76.188.75` | `/root/tanya/banano_kling`, строго ветка `tanyapi` |
| Backend service | — | `144.76.188.75` | `banano-kling.service` |

Поток запросов:

```text
Telegram WebView
    ├── HTML / CSS / JS ──> cdn.chillcreative.ru ──> Nginx static export
    ├── /mini-app/api/* ──> cdn.chillcreative.ru ──HTTPS─> tanyapi.chillcreative.ru
    └── /uploads/feed/* ──> media.chillcreative.ru ──Cloudflare─> Nginx ──> static/uploads
```

Публичный backend проходит через HTTPS-домен. Открывать внешний доступ к `aiohttp :1888` для frontend-сервера не требуется.

## Основные возможности

### Telegram-бот

- webhook runtime на `aiogram 3` + `aiohttp`;
- FSM-сценарии генерации фото, видео и motion control;
- отправка фото/видео/референса в любой момент поддерживаемого сценария;
- история задач и повтор генерации;
- публикация в общую ленту и профиль либо только в профиль;
- платежи, баланс, промокоды, партнёрские начисления;
- административные и диагностические маршруты.

### Mini App

- единый бренд **NEUROMIX** в заголовках, metadata, загрузчике и основных экранах;
- отдельный полноэкранный загрузчик во время получения Telegram `initData` и bootstrap;
- браузерный вход через Telegram Login Widget как fallback вне WebView;
- создание фото, видео и motion generation;
- загрузка пользовательских файлов и сохранённых референсов;
- лента, тренды, профили, remix/repeat/share;
- синхронизация статуса задач с backend;
- статическая production-сборка без Node.js runtime на frontend-сервере.

### Media delivery

- файлы продолжают храниться в `/root/tanya/banano_kling/static/uploads`;
- Nginx получает к ним доступ через постоянный bind mount;
- публичная лента и WebP-превью кешируются Cloudflare;
- приватные и временные uploads не получают годовой публичный кеш;
- отдельное объектное хранилище или платный CDN сейчас не требуются.

## Стек

- Python 3;
- `aiogram 3`, `aiohttp`;
- SQLite/PostgreSQL compatibility layer;
- Redis для FSM/cache с fallback;
- Next.js 16, React 19, Tailwind CSS 4;
- Nginx, systemd, Certbot;
- Cloudflare Free для media proxy/cache;
- provider integrations для генерации изображений и видео.

## Структура репозитория

```text
.
├── bot/                         # Backend, Telegram handlers, Mini App API
├── data/                        # Цены и runtime data
├── docs/                        # Основная документация
├── frontend/miniapp-v0/         # Next.js Mini App frontend
├── ops/media/                   # Nginx/media-конфигурация и инструкция
├── scripts/                     # Deploy, migration, diagnostics, repair
├── static/uploads/              # Фактическое локальное media-хранилище
├── tests/                       # Regression и integration tests
├── cdn.sh                       # Менеджер frontend-host и удалённого deploy
└── requirements.txt
```

## Быстрые команды

### Backend

```bash
cd /root/tanya/banano_kling
git switch tanyapi
git pull --ff-only origin tanyapi
sudo systemctl restart banano-kling.service
sudo systemctl status banano-kling.service --no-pager
curl -fsS http://127.0.0.1:1888/health
```

### Frontend deploy на удалённый сервер

```bash
cd /root/tanya/banano_kling
git switch tanyapi
git pull --ff-only origin tanyapi

sudo bash cdn.sh --remote-deploy tanyafrontend
sudo bash cdn.sh --remote-status tanyafrontend
```

Команды нужно запускать последовательно: сначала дождаться полного завершения deploy, затем отдельно проверять status.

### Media origin

```bash
cd /root/tanya/banano_kling
git switch tanyapi
git pull --ff-only origin tanyapi

LETSENCRYPT_EMAIL='admin@example.com' \
ORIGIN_IPV4='144.76.188.75' \
sudo -E bash scripts/deploy_media_origin.sh
```

### Тесты backend

```bash
cd /root/tanya/banano_kling
. venv/bin/activate
python -m pytest
python -m py_compile $(find bot tests scripts -name '*.py')
```

### Локальная проверка frontend

```bash
cd frontend/miniapp-v0
npm ci
npm run lint
npm test
npm run build
test -f out/index.html
```

## Источники истины

При расхождении документации и реализации использовать следующий приоритет:

1. `bot/main.py` — runtime wiring и HTTP server;
2. `bot/miniapp.py` — Mini App API и auth contracts;
3. `bot/config.py` — env surface;
4. `frontend/miniapp-v0/lib/api.ts` и `lib/app-context.tsx` — frontend runtime contract;
5. `data/price.json` и `bot/services/preset_manager.py` — модели и цены;
6. `tests/` — ожидаемое поведение;
7. документация.

## Документация

- [docs/README.md](docs/README.md) — карта документации;
- [docs/architecture.md](docs/architecture.md) — архитектура и потоки данных;
- [docs/production-deployment.md](docs/production-deployment.md) — полный production deploy от DNS до smoke tests;
- [docs/miniapp-frontend-deployment.md](docs/miniapp-frontend-deployment.md) — frontend/CDN и `cdn.sh`;
- [ops/media/README.md](ops/media/README.md) — media-домен, Nginx, SSL и Cloudflare;
- [docs/environment.md](docs/environment.md) — переменные окружения;
- [docs/runbook.md](docs/runbook.md) — ежедневная эксплуатация;
- [docs/troubleshooting.md](docs/troubleshooting.md) — диагностика и аварийные сценарии;
- [docs/branding.md](docs/branding.md) — правила бренда NEUROMIX;
- [frontend/miniapp-v0/README.md](frontend/miniapp-v0/README.md) — frontend development и build.

## Безопасность

- не коммитить `.env`, токены, private keys и Cloudflare credentials;
- не передавать секреты в аргументах команд, если они попадут в shell history;
- хранить Cloudflare token в root-only файле;
- не публиковать порт backend runtime наружу без необходимости;
- перед deploy создавать backup и проверять `nginx -t`;
- HTML не кешировать надолго, hashed assets кешировать как immutable;
- не использовать `rsync --delete` при обычном frontend deploy из-за кеша Telegram WebView.
