# Interactive Scenarios

These scenarios describe product flows that should stay obvious in Telegram and
the mini app. Each flow maps to buttons that are covered by regression tests.

## 1. Brand Avatar Studio

Goal: turn one product/person photo into a branded avatar pack.

Flow:
- `Собрать AI-образ`
- Upload 1-3 references
- Choose `Seedream 5.0 Lite` for fast concepts or `Banana Pro` for polish
- Select `1:1`
- Prompt examples:
  - `аватар для бренда, чистый фон, premium fashion, мягкий свет`
  - `маскот бренда в стиле editorial portrait`

Expected UX:
- User always sees selected model, aspect ratio, reference count, and balance.
- Result screen has quick buttons: new image, create video, shop, menu.

## 2. Story From Product Photo

Goal: make a short vertical story from a product/reference photo.

Flow:
- `Сделать видео/сторис`
- `Фото + Текст → Видео`
- Upload start photo
- Choose `Seedance 2.0`
- Select `9:16`, duration
- Send motion prompt

Pricing:
- Video cost is calculated as `credits_per_second * duration`.
- The keyboard price and the charged amount must match.

Expected UX:
- Text sent after any model/ratio/duration click must start generation.
- No prompt should be silently swallowed by FSM state changes.

## 3. Motion Transfer

Goal: transfer movement from a user video onto a character/product image.

Flow:
- Open Motion Control
- Choose quality
- Upload character image
- Upload motion video

Pricing:
- Motion Control is calculated from the uploaded video duration.
- Example: `7 sec * 3 GOE/sec = 21 GOE`.
- If balance is too low, the bot explains required GOE and keeps the user in the
  upload step.

Expected UX:
- The user does not need to preselect duration.
- The launch confirmation shows detected duration and final GOE cost.

## 4. Shop Assisted Purchase

Goal: help users pick an accessory and open the mini app.

Flow:
- `Подобрать аксессуар`
- User describes occasion, color, or style
- Bot suggests matching items
- `Магазин 2Loop`

Expected UX:
- All shop buttons return to a working catalog/search screen.
- Admin product photo, price, stock, and primary image controls remain reachable.

## 5. Failed Generation Recovery

Goal: recover from provider/API failures without support chat.

Flow:
- Provider returns failed webhook or launch error
- Credits are refunded
- User sees retry/change model/support buttons

Expected UX:
- Error screen must include at least: main menu, balance, support, new generation.
- Internal task status is marked failed or completed with no dangling pending task.
