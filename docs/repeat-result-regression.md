# Completed result repeat compatibility

Completed image result messages must always expose `🔁 Повторить` when a task ID is known.

Two callback formats exist in already delivered messages:

- `repeat_image_{task_id}` — current safe repeat flow;
- `repeat_result_{task_id}` — legacy completed-result keyboard.

Both callback formats are supported and open the same confirmation screen. Do not remove either handler until all historical Telegram messages can be considered expired.

## Публикации фото/видео — контракт 2026-10-16

Независимо от callback-формата результат опубликованной работы повторяется **как собственный источник**: исходная генерация, результат тренда, ремикс или повтор чужого поста. Общее поведение и security: [PUBLISHED_REPEAT_CONTRACT.md](PUBLISHED_REPEAT_CONTRACT.md). Тестировать фото, Seedance/другое видео, Wan и устаревшие Telegram кнопки; отозванный post должен быть недоступен.

Отдельно покрывать: ImageN/VideoN слоты (`fixed`/`upload`), server-only refs/prompt, совместимость callback, preview → edited recipe → quote → одно списание → terminal status/Studio, temporary 5xx и корректный retry. Корневая родословная остаётся для статистики, **не** заменяет выбранный source. Не использовать платные провайдеры в автоматических тестах.
