# v0.dev Prompt For Banano AI Mini App

Build a premium dark Telegram Mini App frontend for an AI generation product called `Banano AI Studio`.

This is a frontend-only task for `v0.dev`.
Do not generate backend code.
Do not generate fake lorem ipsum product copy.
Focus on a polished production-ready UI with realistic product structure, clear component boundaries, and thoughtful empty/loading/error states.

The app must feel like a high-end creative control room for photo and video generation.
Visual direction: cinematic, editorial, dark, glassy, warm-gold accents, subtle blue highlights, mobile-first, premium but not crypto-gimmicky.

Important:
- This UI must work both as a Telegram Mini App and as a standalone browser preview.
- In standalone/browser preview mode there is no Telegram `initData`, so the UI must support a `demo mode` with mocked user/model/task data and must not hard-crash on missing Telegram objects.
- Do not block rendering behind Telegram auth.
- The app should render immediately with demo content, then optionally hydrate from real API data if available.

## Product Context

This is a Telegram bot + Mini App for AI media generation.

Core user actions:
- generate images
- generate videos
- upload references
- track task statuses
- open completed results
- see credits balance in bananas
- open support / AI assistant / partner screens

Currency:
- credits are called `bananas`
- show as `🍌`
- new users get a welcome bonus of `25🍌`

Brand:
- Product name: `Banano AI Studio`
- Tone: premium, helpful, modern, creator-focused
- Language: Russian UI

## Main UX Problem To Solve

The current app is too tightly coupled to Telegram auth and can show:
- `Ошибка авторизации`
- empty model lists

Your generated frontend must avoid this by design:
- render in demo mode by default if auth/bootstrap is unavailable
- show a top banner like `Demo mode` in preview mode
- gracefully switch to live mode if API/bootstrap succeeds

## Required Tech / Output Shape

Generate a modern React frontend suitable for Next.js App Router with:
- reusable components
- clean state model
- mobile-first responsive layout
- strong visual hierarchy
- accessible buttons/inputs
- reusable cards, tabs, badges, drawers, segmented controls

Prefer:
- TypeScript
- shadcn/ui style patterns
- Tailwind CSS
- lucide-react icons

Do not use:
- generic purple SaaS theme
- boring default dashboard layout
- excessive gradients everywhere
- neon hacker aesthetic

## Screens To Build

Build the app as a tabbed single-screen mini app with these top-level tabs:

1. `Студия`
2. `Фото`
3. `Видео`
4. `Сервисы`

Also include a bottom-sheet, modal, or side panel for:
- `Детали задачи`

## Global Layout

Top section:
- premium hero/header card
- product title `Banano AI Studio`
- subtitle about photo/video generation
- pills: `Welcome 25🍌`, `Фото`, `Видео`, `История`
- user block showing:
  - user name
  - banana balance
  - live/demo mode badge
  - last sync time

Below that:
- tab bar with 4 tabs

## Tab 1: `Студия`

This is the dashboard / launchpad.

Block A: `Быстрый старт`
- grid of action cards
- actions:
  - `Создать фото`
  - `Создать видео`
  - `Баланс и пакеты`
  - `AI-помощник`
- each card has:
  - icon
  - title
  - short description
  - hover/tap state

Block B: `Последние задачи`
- list of recent tasks
- each task card shows:
  - model label
  - type: photo or video
  - status badge
  - aspect ratio
  - cost in bananas
  - prompt preview
  - created time
  - result link if ready
- clicking a task opens `Детали задачи`

Block C: `Детали задачи`
- either inline panel on desktop or drawer/modal on mobile
- shows:
  - model
  - status
  - task id
  - created time
  - cost
  - ratio
  - duration if video
  - references count
  - full prompt
  - preview media if result exists
  - button `Открыть оригинал`
- if task is pending:
  - show animated pending state
  - text like `Статус обновляется автоматически`

## Tab 2: `Фото`

Purpose: image generation and image editing.

Main form fields:
- model select
- ratio select
- quality select
- prompt textarea
- upload area for reference/source images
- summary panel
- launch button

Image models:
- `Nano Banana Pro`
- `Seedream 4.5 Edit`
- `GPT Image 2`
- `Grok Imagine`

Model-specific behavior:
- `Seedream 4.5 Edit` requires at least one source/reference image
- `Grok Imagine` requires at least one reference image
- `GPT Image 2` supports `auto` ratio

Ratio examples:
- `1:1`
- `9:16`
- `16:9`
- `3:4`
- `4:3`
- `2:3`
- `3:2`
- `auto` where supported

Photo tab layout:
- left: form
- right: summary + result panel
- on mobile stack vertically

Required UI pieces:
- uploaded asset chips/cards with remove button
- helper text under uploader
- cost pill
- submit button with loading state
- result card showing either:
  - generated image preview
  - queued state with task id
  - clear error state

## Tab 3: `Видео`

Purpose: video generation.

Main form fields:
- video model select
- scenario type segmented control or select:
  - `Текст → Видео`
  - `Фото + Текст → Видео`
  - `Видео + Текст → Видео`
- ratio select
- duration select
- prompt textarea
- upload start image for image-to-video
- upload extra photo references
- upload video references
- summary panel
- launch button

Video models:
- `Kling 3.0`
- `Kling v3`
- `Kling 2.5 Turbo Pro`
- `Grok Imagine`
- `Veo 3.1 Fast`

Behavior rules:
- `Фото + Текст → Видео` requires a start image
- `Видео + Текст → Видео` requires at least one video reference
- available durations depend on model
- some models do not support all scenario types, so unavailable options should be visibly disabled

Video tab should feel slightly more cinematic than photo tab.
Use motion-inspired visual accents but do not over-animate.

Result panel:
- queued state with task id
- completed video preview player if result exists
- error state if submission fails

## Tab 4: `Сервисы`

This tab is not generation itself.
It is a polished command center for adjacent bot functions.

Include cards/buttons for:
- `Промпт по фото`
- `Изменить фото`
- `Оживить`
- `Batch Edit`
- `Поддержка`
- `Партнёрам`
- `Ещё`

These cards can be mocked as action tiles with icons and short helper descriptions.

Also include a compact info block:
- tips about references
- note that result statuses sync from the bot backend
- note about 25 banana welcome bonus

## Visual Style

Design goals:
- dark editorial control room
- warm gold accent for premium energy
- muted cyan/blue accent for technical/live data
- layered glass cards
- big rounded corners
- subtle gradients
- strong typography contrast

Typography:
- use an expressive serif for major headings
- use a clean geometric sans for UI/body

Color palette guidance:
- background: deep blue-black / charcoal
- cards: translucent dark panels
- primary accent: gold / amber
- secondary accent: soft cyan / steel blue
- success: muted green
- error: warm red

Avoid:
- pure black everywhere
- flat gray enterprise admin visuals
- purple
- generic startup SaaS look

## Required States

Implement all of these states in the UI:

Global:
- live mode
- demo mode
- bootstrap loading
- bootstrap error with graceful fallback to demo mode

Tasks:
- empty history
- pending
- completed
- failed

Forms:
- pristine
- loading
- validation error
- submit success
- queued success
- immediate ready result

Uploads:
- empty
- uploading
- uploaded list
- remove item
- invalid file

## Important Product Copy

Use realistic Russian microcopy.
Examples:
- `Запустить фото`
- `Запустить видео`
- `Загружаю референсы…`
- `Задача принята`
- `Результат придёт в чат и появится в истории`
- `Статус обновляется автоматически`
- `Demo mode`
- `Live mode`
- `Welcome-бонус 25🍌`

## Data Shape To Assume

Design the UI around this likely API shape:

Bootstrap:
```ts
type BootstrapResponse = {
  ok: true
  first_name: string
  credits: number
  is_admin: boolean
  mini_app_url: string
  image_models: {
    id: string
    label: string
    description: string
    cost: number
    ratios: string[]
    requires_reference: boolean
    max_references: number
  }[]
  video_models: {
    id: string
    label: string
    description: string
    durations: number[]
    ratios: string[]
    supports: string[]
    costs: Record<string, number>
  }[]
  recent_tasks: {
    task_id: string
    type: "image" | "video"
    model: string
    model_label: string
    aspect_ratio: string
    status: "pending" | "completed" | "failed"
    result_url?: string | null
    created_at: string
    prompt_preview: string
    cost: number
  }[]
}
```

Task detail:
```ts
type TaskDetail = {
  task_id: string
  type: "image" | "video"
  model: string
  model_label: string
  duration?: number | null
  aspect_ratio: string
  prompt: string
  cost: number
  status: "pending" | "completed" | "failed"
  result_url?: string | null
  created_at: string
  request_data?: {
    reference_images?: string[]
    v_reference_videos?: string[]
  }
}
```

## Frontend Architecture Requirements

Generate clean components such as:
- `MiniAppShell`
- `HeroHeader`
- `StatusBar`
- `TabNav`
- `QuickActionGrid`
- `TaskHistoryList`
- `TaskDetailPanel`
- `ImageGeneratorForm`
- `VideoGeneratorForm`
- `UploadChips`
- `ResultCard`
- `ServiceGrid`
- `ModeBadge`

Use sensible local state and mock data adapters.
Include a small fake data layer so the UI looks complete even without backend.

## Animation Guidance

Use only a few tasteful animations:
- fade/slide on tab changes
- shimmer/loading skeletons
- subtle pulse for pending status
- smooth drawer/modal transitions

Do not overdo micro-interactions.

## Final Output Expectations

Generate a beautiful, production-feeling Mini App frontend that:
- looks expensive and intentional
- works in both Telegram and browser preview
- has realistic Russian product copy
- includes demo data fallback
- includes task detail auto-refresh UI states
- includes polished empty and error states
- is clearly structured for later API wiring

If something must be mocked, mock it elegantly rather than leaving holes.
