# Banano Mini App v0

Экспорт фронтенда из `v0.dev`, интегрированный в основной репозиторий как отдельный Next.js модуль.

## Что это

Это не ломает текущий Python Mini App из `static/miniapp`, а добавляет отдельный современный frontend-модуль, который можно:

- дорабатывать отдельно
- подключать к текущему backend API `/mini-app/api/*`
- использовать как основу для нового Mini App frontend

## Где лежит

- исходники: `frontend/miniapp-v0`
- текущий рабочий Python Mini App: `static/miniapp`
- backend маршруты Mini App: `bot/miniapp.py`

## Что уже сделано

Чтобы модуль был ближе к реальному backend, внутри фронта уже обновлены:

- id image-моделей:
  - `banana_pro`
  - `seedream_edit`
  - `flux_pro`
  - `grok_imagine_i2i`
- id video-моделей:
  - `v3_pro`
  - `v3_std`
  - `v26_pro`
  - `grok_imagine`
  - `veo3_fast`
- id video-сценариев:
  - `text`
  - `imgtxt`
  - `video`

Также фронт уже переведён с mock-only логики на живой API layer:

- bootstrap через `POST /mini-app/api/bootstrap`
- upload через `POST /mini-app/api/upload`
- image generation через `POST /mini-app/api/generate-image`
- video generation через `POST /mini-app/api/generate-video`
- task detail через `POST /mini-app/api/task-detail`
- авто-fallback в demo mode, если нет Telegram `initData`

## Что уже можно использовать в проде прямо сейчас

Прямо сейчас в проде остаётся рабочим текущий frontend из:

- `static/miniapp`

Он уже подключён в backend и обслуживается ботом.

Новый `miniapp-v0` уже интегрирован в репозиторий и подключён к живым API на уровне исходников, но для реального использования как основной UI его нужно один раз собрать в node-среде.

## Как запускать

В этом окружении сейчас нет `npm`/`pnpm`, поэтому локально здесь сборку не прогонял.

Когда у вас будет node-среда:

```bash
cd frontend/miniapp-v0
pnpm install
pnpm dev
```

или

```bash
cd frontend/miniapp-v0
npm install
npm run dev
```

## К чему подключать

Текущий backend уже отдаёт нужные endpoints:

- `POST /mini-app/api/bootstrap`
- `POST /mini-app/api/upload`
- `POST /mini-app/api/generate-image`
- `POST /mini-app/api/generate-video`
- `POST /mini-app/api/task-detail`

Во фронте `miniapp-v0` это уже учтено.

## Важная заметка

Сейчас этот Next.js модуль интегрирован в репозиторий как исходники.
После сборки его можно подключить почти без дополнительной переделки backend.

## Как довести до нового основного прод-фронта

1. Соберите frontend:

```bash
cd frontend/miniapp-v0
pnpm install
NEXT_EXPORT=1 pnpm build
```

2. Если будете делать static export, сложите собранный результат в один из путей:

- `frontend/miniapp-v0/out`
- или `frontend/miniapp-v0/dist`

3. Backend уже подготовлен так, что `bot/miniapp.py` сначала ищет:

- `frontend/miniapp-v0/out/index.html`
- `frontend/miniapp-v0/dist/index.html`
- и только потом делает fallback на `static/miniapp/index.html`

То есть после появления built static export backend сможет автоматически начать отдавать новый frontend вместо старого fallback.

Для `npm`-среды команда такая:

```bash
cd frontend/miniapp-v0
npm install
NEXT_EXPORT=1 npm run build
```

## Следующий логичный шаг

Если захотите, дальше можно сделать один из двух путей:

1. Подключить этот Next frontend как отдельный deployable app.
2. Собрать static export и переключить текущий `/mini-app` на него как основной production UI.
