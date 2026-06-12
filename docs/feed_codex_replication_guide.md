# Аудит ленты и инструкция для Codex

Дата аудита: 2026-06-12

## Краткий аудит проекта

Проект - Telegram-бот и Telegram Mini App для image/video генераций. Основной стек: Python, Aiogram 3, aiohttp API для TMA, SQLite runtime с подготовленной PostgreSQL-миграцией, React/Vite TMA.

Лента реализована как легкий слой поверх существующих задач генерации. Отдельной таблицы `feed_posts` нет: публичность, лайки и повторы хранятся прямо в `generation_tasks`.

Сильные стороны:

- Минимальная модель данных: публикация не дублирует результат генерации.
- Есть единые DB-функции для публикации, снятия, выборки, лайков и шаринга.
- Есть защита от публикации чужой производной работы через `source_feed_task_id`.
- Бот умеет показывать фото по URL и имеет fallback: скачивает, ужимает и загружает файл в Telegram.
- TMA и бот используют одни и те же базовые операции ленты.
- Покрыты ключевые сценарии базы и клавиатур тестами.

Риски и ограничения:

- В ленте публично раскрываются `prompt`, модель и параметры генерации. Для публичного продукта лучше добавить явное согласие перед публикацией.
- Лайки и шаринги привязаны к пользователю через `feed_interactions`; повторный клик возвращает текущий счетчик без накрутки.
- Нет модерационного статуса. Сейчас публикация сразу делает работу публичной.
- Лента ограничена только изображениями: `type = 'image'`. Видео в TMA умеет отображаться компонентом, но серверная выборка ленты его отфильтровывает.
- TMA `_feed()` возвращает только публичные работы; непубличный fallback удален.
- Есть таблица `feed_interactions`, но пока нет расширенной аналитики по просмотрам и источникам переходов.
- Сортировка основана на простой формуле `likes + shares * 3`, без временного затухания и антиспама.

Проверки, выполненные во время аудита:

```bash
pytest tests/test_database.py::test_feed_publish_filters_and_metrics \
  tests/test_database.py::test_feed_publish_blocks_foreign_source \
  tests/test_keyboards.py::test_get_image_result_keyboard_has_feed_publish \
  tests/test_reliability_runtime.py::test_register_user_bot_commands_excludes_admin_commands -q

npm run build
```

Результат после фиксов: 43 DB/TMA теста прошли, TMA production build собрался.

## Как устроена лента

### Модель данных

Основной объект - `GenerationTask` в `bot/database.py`.

Поля ленты:

- `is_public_feed` - опубликована ли генерация в публичной ленте.
- `likes_count` - счетчик лайков.
- `shares_count` - счетчик шарингов/повторов.
- `source_feed_task_id` - исходная работа, если генерация сделана повтором из ленты.
- `published_at` - время первой публикации.
- `feed_status` - модерационный статус, сейчас используется `approved`.

Уникальные пользовательские действия хранятся в `feed_interactions` с `UNIQUE(task_id, telegram_id, action)`.

В SQLite эти поля добавляются в `init_db()` через `ALTER TABLE`, а в PostgreSQL описаны в `migrations/postgres_schema_v2.sql`.

### Публикация

Публикация выполняется функцией `share_task_to_feed(task_id, telegram_id)`:

- задача должна существовать;
- `telegram_id` задачи должен совпадать с пользователем;
- задача должна быть `type = 'image'`;
- статус должен быть `completed`;
- должен быть `result_url`;
- если есть `source_feed_task_id`, исходная работа должна принадлежать тому же пользователю, иначе возвращается `foreign_source`;
- при успехе ставится `is_public_feed = 1`.

Точки входа:

- Бот: кнопка `feed_publish_{task_id}` в `get_image_result_keyboard()`.
- TMA user API: `POST /api/tma/app/feed/{task_id}/action` с `{"action": "publish"}`.
- TMA admin API: action `publish_feed` у генерации.

### Выборка

Бот использует `get_feed_tasks(limit=30)`.

Фильтр:

- `is_public_feed = 1`;
- `feed_status = 'approved'`;
- `type = 'image'`;
- `status = 'completed'`;
- `result_url` не пустой.

Сортировка:

```sql
(COALESCE(likes_count, 0) + COALESCE(shares_count, 0) * 3) DESC,
COALESCE(published_at, completed_at, created_at) DESC
```

TMA использует `_feed(limit=40)` и возвращает только публичные approved-задачи из `get_feed_tasks()`.

### Бот-интерфейс

Файл: `bot/handlers/feed.py`.

Команды и callbacks:

- `/feed` - открыть ленту;
- `menu_feed` - открыть из главного меню;
- `feed_next_{index}` - следующая карточка;
- `feed_like_{task_id}_{index}` - лайк;
- `feed_share_{task_id}` - создать deep link;
- `feed_publish_{task_id}` - опубликовать свою генерацию;
- `feed_remove_{task_id}_{index}` - снять свою публикацию;
- `feed_repeat_{task_id}` - повторить чужую/свою работу через промпт.

Показ карточки:

- сначала Telegram получает фото напрямую по `result_url`;
- если Telegram не принимает URL, бот скачивает изображение;
- если файл больше лимита, сжимает через Pillow;
- затем отправляет или редактирует сообщение через `BufferedInputFile`.

### TMA-интерфейс

Файл: `tma/src/App.tsx`.

Компоненты:

- `FeedPreview` - показывает image/video preview;
- `FeedLightbox` - полноэкранный просмотр;
- `UserFeedPage` - публичная лента для пользователя;
- `FeedPage` - админская лента;
- `HistoryPage` - история генераций с кнопкой публикации.

Пользовательские действия:

- публикация из истории;
- лайк из ленты;
- повтор генерации через черновик `createDraftFromFeedRow()`.

## Инструкция для Codex: повторить ленту в другом проекте

Скопируй этот блок как задачу для Codex в новом проекте.

```markdown
Нужно реализовать публичную ленту генераций по образцу проекта Banano Kling.

Контекст:
- В проекте уже есть сущность задачи генерации (`generation_tasks` или аналог).
- У задачи есть пользователь, `task_id`, тип (`image`/`video`), статус, `result_url`, промпт, модель, параметры и время создания/завершения.
- Лента должна работать в Telegram-боте и, если есть Mini App, в TMA API/UI.

Сделай реализацию в стиле текущего проекта, без лишнего рефакторинга.

1. База данных
- Добавь к задаче генерации поля:
  - `is_public_feed boolean/integer default false`
  - `likes_count integer default 0`
  - `shares_count integer default 0`
  - `source_feed_task_id text nullable`
- Добавь индекс для публичной ленты:
  - PostgreSQL: `(is_public_feed, created_at DESC)` или лучше частичный индекс по публичным completed работам.
  - SQLite: обычный индекс по `is_public_feed, created_at`.
- Обнови dataclass/model задачи.
- Обнови миграции и runtime init/migration код.

2. DB/service функции
Реализуй единый слой функций:
- `share_task_to_feed(task_id, user_id_or_telegram_id) -> tuple[bool, str]`
  - проверяет существование;
  - проверяет владение;
  - разрешает только completed задачу с непустым `result_url`;
  - если нужна только image-лента, проверяет `type == "image"`;
  - запрещает публикацию производной от чужой ленты через `source_feed_task_id`;
  - выставляет `is_public_feed = true`.
- `remove_task_from_feed(task_id, owner_id) -> bool`
  - снимает флаг, не удаляет задачу.
- `get_feed_tasks(limit=30) -> list[GenerationTask]`
  - возвращает только публичные completed задачи с result_url;
  - сортирует по `(likes_count + shares_count * 3) DESC`, затем по `completed_at/created_at DESC`.
- `get_public_feed_task(task_id) -> GenerationTask | None`
  - возвращает задачу только если она сейчас публична.
- `like_feed_task(task_id) -> int | None`
  - атомарно увеличивает лайки только у публичной задачи.
- `increment_feed_share(task_id) -> int | None`
  - атомарно увеличивает счетчик шаринга только у публичной задачи.

3. Telegram bot UX
- Добавь `/feed` и кнопку открытия ленты в главное меню.
- В клавиатуру результата генерации добавь кнопку `В ленту` с callback `feed_publish_{task_id}`.
- Для карточки ленты сделай inline-клавиатуру:
  - лайк;
  - поделиться/deep link;
  - следующая карточка;
  - повторить;
  - удалить из ленты только для владельца;
  - главное меню.
- Хендлеры:
  - `open_feed`
  - `next_feed_card`
  - `like_feed_card`
  - `share_feed_card`
  - `publish_task_to_feed`
  - `remove_feed_card`
  - `repeat_feed_card`
- Для отправки изображения:
  - пробуй `answer_photo(photo=result_url)`;
  - при ошибке скачай preview с лимитом размера;
  - ужми через Pillow до Telegram-friendly размера;
  - отправь через `BufferedInputFile`.

4. Repeat flow
- При `feed_repeat_{task_id}` получи публичную задачу.
- Сохрани в FSM/черновик:
  - `source_feed_task_id`;
  - исходный prompt;
  - модель;
  - aspect ratio;
  - режим image generation.
- Дай пользователю загрузить свои референсы или сразу запустить повтор.
- При создании новой задачи передай `source_feed_task_id`.
- Не разрешай публиковать derivative от чужой работы как свою публичную работу, если это требование продукта.

5. TMA API, если в проекте есть Mini App
- В bootstrap добавь:
  - `tasks` - история пользователя;
  - `feed` - публичная лента.
- Добавь endpoint:
  - `POST /api/tma/app/feed/{task_id}/action`
  - actions: `like`, `share`, `publish`.
- Добавь admin endpoint:
  - `POST /api/tma/admin/feed/{task_id}/action`
  - actions: `like`, `share`, `remove`.
- Не добавляй в публичную TMA-ленту непубличные работы fallback-ом, если приватность важнее заполненности интерфейса.

6. TMA UI, если есть React Mini App
- В истории генераций добавь кнопку `Опубликовать`.
- Сделай страницу ленты:
  - сетка карточек;
  - preview изображения/видео;
  - автор;
  - prompt preview;
  - лайки/повторы;
  - кнопки лайка и повтора.
- Сделай lightbox:
  - открыть оригинал;
  - повторить;
  - закрыть.
- Повтор должен переносить prompt/model/aspect_ratio/duration в форму создания.

7. Приватность и модерация
- Перед публикацией явно покажи пользователю, что prompt/result могут стать публичными.
- Не показывай сырой `telegram_id`, если есть username/display_name.
- Желательно добавить:
  - `feed_status = pending/approved/rejected`;
  - `published_at`;
  - `moderated_by`;
  - `feed_likes(user_id, task_id)` для уникальных лайков;
  - rate limit на лайки/шары.

8. Тесты
Добавь тесты:
- нельзя публиковать pending/failed задачу;
- нельзя публиковать чужую задачу;
- можно публиковать completed задачу с result_url;
- публичная задача попадает в `get_feed_tasks`;
- лайк и share увеличивают счетчики;
- снятие с ленты скрывает задачу;
- derivative от чужого `source_feed_task_id` нельзя публиковать;
- клавиатура результата содержит кнопку публикации;
- команда `/feed` зарегистрирована.

9. Проверка
Запусти:
- backend тесты по базе и клавиатурам;
- typecheck/build Mini App, если она есть;
- ручной сценарий: сгенерировать изображение -> опубликовать -> открыть `/feed` -> лайк -> share -> повтор -> снять с ленты.
```

## Рекомендованные улучшения для текущего проекта

1. Добавить явный consent-экран перед публикацией: что именно станет публичным.
2. Добавить полноценную модерацию: `pending/approved/rejected`, очередь админа и причину отклонения.
3. Добавить rate limit на `like` и `share` поверх уникальности, чтобы снизить шум запросов.
4. Добавить временное затухание в ranking, чтобы старые популярные работы не держали верх бесконечно.
5. Вынести feed-логику из большого `bot/database.py` в отдельный репозиторий/сервисный модуль при следующей архитектурной чистке.
