# Mini App Frontend

`frontend/miniapp-v0` — текущий Next.js frontend для Telegram Mini App. Это не отдельный backend: production contracts определяются Python-сервером в `bot/miniapp.py`.

## Что здесь реально есть

- `Next.js 16`
- `React 19`
- `Tailwind 4`
- tabs/sheets/forms для:
  - studio
  - photo
  - video
  - motion
  - feed
  - prompts
  - services
  - profile
- API client в `lib/api.ts`
- app state/context в `lib/app-context.tsx`

## Источник истины по API

Frontend должен ориентироваться на backend routes из `bot/miniapp.py`, прежде всего:

- `POST /mini-app/api/bootstrap`
- `POST /mini-app/api/upload`
- `POST /mini-app/api/generate-image`
- `POST /mini-app/api/generate-video`
- `POST /mini-app/api/generate-motion`
- `POST /mini-app/api/task-detail`
- `POST /mini-app/api/create-payment`
- prompt/feed/profile endpoints

## Режимы использования

### 1. Локальная разработка фронтенда

```bash
cd frontend/miniapp-v0
npm install
npm run dev
```

### 2. Static export для Python runtime

```bash
cd frontend/miniapp-v0
npm run build
```

Backend затем может раздавать build как Mini App UI.

## Ограничение

Если frontend и backend расходятся по:

- model ids
- payload shape
- task detail response
- feed/prompt contracts

то источником истины считается backend и его тесты, а frontend нужно адаптировать под них.
