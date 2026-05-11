# UX Guide

Last updated: 2026-05-11.

This guide defines how 2Loop bot and Mini App screens should talk to users.

## UX Principles

1. Every user-facing message must offer a next step.
2. Technical IDs belong in logs or admin-only details, not in normal user messages.
3. GOE is the single balance name. Use `50 GOE`, not `GOEов`, `credits`, or mixed wording.
4. Provider/model names should be translated into user value when possible.
5. Errors should be recovery screens, not dead ends.

## Core Buttons

### After Payment

Use:

```text
🧊 Создать AI-образ
🎬 Сделать видео
💎 Баланс
🛒 Магазин
🏠 Главное меню
```

### While Generation Is Running

Use:

```text
💎 Баланс
🏠 Главное меню
```

Message pattern:

```text
🚀 Генерация запущена

💎 Списано: 7 GOE
⏱ Обычно результат приходит за 1-3 минуты.
```

Do not show provider task IDs to regular users.

### After Generation Error

Use:

```text
🔁 Попробовать снова
⚙️ Сменить модель
💎 Баланс
💬 Поддержка
🏠 Главное меню
```

Message pattern:

```text
❌ Не получилось создать изображение

GOE вернулись на баланс. Попробуйте ещё раз или смените модель.
```

For provider-specific problems:

```text
❌ Не получилось создать результат

GOE вернулись на баланс. Попробуйте ещё раз, смените модель или загрузите другое фото.
```

### After Image Result

Use:

```text
Скачать оригинал
Исходник
Создать ещё
Сделать видео
Магазин
Главное меню
```

Good caption:

```text
✅ Изображение готово

Nano Banana 2 · 7 GOE · 1:1
Промпт: смени фон
```

Avoid:

```text
ID: f238a39...
task_id: ...
raw url: ...
```

## Model Naming

Technical model names may remain in admin screens and logs. User-facing screens should lead
with benefit:

```text
Быстрое фото
Лучше сохраняет лицо
Максимум качества
Видео для сторис
Видео с движением
```

If the exact model matters, show it as secondary text:

```text
Лучше сохраняет лицо
Nano Banana 2 · 7 GOE
```

## Error Translation

Translate provider errors into user actions.

```text
image format is not supported
```

User text:

```text
Фото не подошло по формату. GOE вернулись на баланс.
Загрузите другое фото или попробуйте другую модель.
```

```text
invalid input / E006 / 422
```

User text:

```text
Провайдер не принял входные данные. GOE вернулись на баланс.
Попробуйте упростить промпт или загрузить другое фото.
```

```text
no result from API
```

User text:

```text
Провайдер не вернул файл. GOE вернулись на баланс.
Попробуйте ещё раз чуть позже.
```

## Mini App UX

### Public User

Prioritize:

- product image;
- price;
- availability;
- add to cart;
- cart total fixed at the bottom.

Avoid exposing admin controls or empty technical fields.

### Admin

Prioritize operational speed:

- new orders;
- products without images;
- low stock;
- hidden/inactive products;
- failed uploads.

Admin screens should use dense lists and predictable controls rather than marketing-style
layouts.

## Admin-Only Technical Details

Technical details can be available behind an admin-only button:

```text
Тех. детали
```

Possible contents:

- local task id;
- provider task id;
- model;
- webhook route;
- payment id;
- raw provider error.

Do not show this by default to regular users.
