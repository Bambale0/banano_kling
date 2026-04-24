# Banano Kling AI Bot

Telegram-бот для генерации фото и видео с понятным пошаговым интерфейсом. Проект рассчитан не только на опытных пользователей: внутри есть отдельные сценарии для новичков, простые подсказки на экранах и аккуратные мастера для фото, видео и аватаров.

## Что умеет бот

- Создавать фото по текстовому описанию
- Редактировать фото по референсам
- Создавать видео по тексту, фото или видео-референсам
- Делать talking avatar из фото и аудио
- Переносить движение через Motion Control
- Подсказывать промпт по фото
- Вести баланс, оплаты и историю задач
- Поддерживать партнерскую программу и админ-инструменты

## Как это выглядит для пользователя

Главный экран специально упрощен:

- `Создать фото`
- `Создать видео`
- `Промпт по фото`
- `Промпт-канал`
- `AI-помощник`
- `Баланс`
- `Поддержка`
- `Партнерам`

Почти все генерации теперь идут по понятной схеме:

1. Выбрать модель
2. Загрузить исходники, если они нужны
3. Настроить параметры
4. Написать промпт простыми словами
5. Получить результат или понятное сообщение об ошибке

## Основные сценарии

### Создать фото

Поток для фото построен как мастер из трех шагов:

1. Выбор модели
2. Загрузка референсов, если они нужны
3. Настройки и текстовый промпт

Подходит для:

- нового изображения с нуля
- сохранения внешности человека
- стилизации по референсам
- аккуратного редактирования фото

### Создать видео

Поток для видео тоже разбит на шаги:

1. Выбор модели
2. Выбор типа генерации и нужного медиа
3. Настройки и промпт

Поддерживаемые типы:

- `Текст -> Видео`
- `Фото + Текст -> Видео`
- `Видео + Текст -> Видео`
- `Аватар + Аудио -> Видео`

### Talking avatar

Для `Kling AI Avatar Standard` и `Kling AI Avatar Pro` пользователь проходит отдельный сценарий:

1. Выбрать модель аватара
2. Загрузить одно фото аватара
3. Загрузить одно аудио
4. Написать короткий текст-подсказку
5. Запустить генерацию

### Motion Control

Сценарий для переноса движения:

1. Загрузить фото персонажа
2. Загрузить видео движения
3. Запустить анимацию

### Промпт по фото

Помогает новичкам, которые не умеют писать промпты. Пользователь отправляет фото, бот помогает описать сцену, стиль и детали.

## Модели

### Фото

| Кнопка в боте | Внутренний ключ | Что делает |
|---|---|---|
| Nano Banana Pro | `banana_pro` | Генерация и edit через Gemini/Nano Banana Pro |
| Nano Banana 2 | `banana_2` | Более легкий вариант Nano Banana |
| Seedream 4.5 | `seedream_edit` | Image edit по документации Kie.ai |
| GPT Image 2 | `flux_pro` | GPT Image 2 text-to-image и image-to-image |
| Grok Imagine | `grok_imagine_i2i` | Генерация/редактирование через Grok |

### Видео

| Кнопка в боте | Внутренний ключ | Что делает |
|---|---|---|
| Kling 3.0 | `v3_pro` | Основная генерация Kling 3.0 |
| Kling v3 | `v3_std` | Более доступная версия Kling |
| Kling 2.5 Turbo Pro | `v26_pro` | Реализован по `kl.md`, с `negative_prompt` и `cfg_scale` |
| Kling AI Avatar Standard | `avatar_std` | Talking avatar по `kl2.md` |
| Kling AI Avatar Pro | `avatar_pro` | Продвинутый talking avatar по `kl2.md` |
| Veo 3.1 Quality | `veo3` | Видео через Veo |
| Veo 3.1 Fast | `veo3_fast` | Быстрый Veo |
| Veo 3.1 Lite | `veo3_lite` | Легкий Veo |
| Kling Glow | `glow` | Упрощенный видео-сценарий |

## Что реализовано по документации моделей

### GPT Image 2

Реализовано:

- text-to-image
- image-to-image
- `aspect_ratio`
- `nsfw_checker`
- автоматический переход в i2i, если пользователь загрузил исходники

### Seedream 4.5 Edit

Реализовано:

- обязательный image input
- `aspect_ratio`
- `quality`
- `nsfw_checker`
- создание задач через Kie.ai task API

### Kling 2.5 Turbo Pro

Реализовано:

- text-to-video
- image-to-video
- `duration` только `5` и `10`
- `aspect_ratio`
- `negative_prompt`
- `cfg_scale`

### Kling AI Avatar Standard / Pro

Реализовано:

- `image_url`
- `audio_url`
- `prompt`
- отдельный пользовательский сценарий
- валидация, что без фото и аудио задача не стартует

## Важные UX-принципы проекта

Бот ориентирован на людей без опыта. Поэтому в интерфейсе соблюдаются такие правила:

- сначала действие, потом настройки
- короткие и простые тексты на экранах
- минимум технических терминов
- понятные статусы загрузки файлов
- ошибки объясняются человеческим языком
- если модель требует медиа, бот не дает случайно пропустить критический шаг

## Архитектура проекта

```text
banano_kling/
├── bot/
│   ├── config.py
│   ├── database.py
│   ├── keyboards.py
│   ├── main.py
│   ├── states.py
│   ├── handlers/
│   │   ├── admin.py
│   │   ├── batch_generation.py
│   │   ├── common.py
│   │   ├── generation.py
│   │   ├── image_analyzer.py
│   │   └── payments.py
│   ├── services/
│   │   ├── ai_assistant_service.py
│   │   ├── cryptobot_service.py
│   │   ├── gemini_service.py
│   │   ├── gpt_image_service.py
│   │   ├── grok_service.py
│   │   ├── kling_service.py
│   │   ├── nano_banana_2_service.py
│   │   ├── nano_banana_pro_service.py
│   │   ├── preset_manager.py
│   │   └── seedream_service.py
│   └── utils/
├── data/
├── logs/
├── static/uploads/
├── tests/
├── start.sh
└── stop.sh
```

### Ключевые файлы

- [bot/handlers/common.py](/root/banano_kling/bot/handlers/common.py) отвечает за стартовые экраны, помощь, баланс и вторичные меню
- [bot/handlers/generation.py](/root/banano_kling/bot/handlers/generation.py) содержит основные пользовательские сценарии фото и видео
- [bot/keyboards.py](/root/banano_kling/bot/keyboards.py) хранит все клавиатуры и подписи моделей
- [bot/services/kling_service.py](/root/banano_kling/bot/services/kling_service.py) инкапсулирует работу с Kling и Kie.ai
- [bot/services/gpt_image_service.py](/root/banano_kling/bot/services/gpt_image_service.py) отвечает за GPT Image 2
- [bot/services/seedream_service.py](/root/banano_kling/bot/services/seedream_service.py) отвечает за Seedream 4.5 Edit
- [bot/database.py](/root/banano_kling/bot/database.py) содержит SQLite-слой, статусы задач и операции с балансом
- [bot/main.py](/root/banano_kling/bot/main.py) поднимает приложение и принимает webhooks

## База данных

Используется SQLite.

Основные таблицы:

- `users`
- `transactions`
- `generation_tasks`
- `generation_history`
- `user_settings`
- `referrals`
- `partner_withdrawals`
- `batch_jobs`

Важный момент:

- если у задачи есть `result_url`, `complete_video_task()` ставит статус `completed`
- если результата нет, задача помечается как `failed`

Это важно и для интерфейса, и для корректной аналитики.

## Webhooks

Проект принимает несколько типов webhook-событий:

- Telegram updates
- Kling / Kie.ai callbacks
- CryptoBot callbacks

Типовой сценарий видео-задачи:

1. Бот создает задачу у внешнего провайдера
2. Сохраняет внутренний `task_id`
3. Ждет webhook
4. Получает ссылку на результат
5. Закрывает задачу и отправляет видео пользователю

## Конфигурация

Минимально нужно настроить `.env`.

Основные переменные:

```env
BOT_TOKEN=
WEBHOOK_HOST=
WEBHOOK_PATH=/webhook
WEBHOOK_PORT=8443

ADMIN_IDS=

KIE_AI_API_KEY=
GEMINI_API_KEY=
NANOBANANA_API_KEY=
REPLICATE_API_TOKEN=

CRYPTOBOT_API_TOKEN=
CRYPTOBOT_USE_TESTNET=0
CRYPTOBOT_WEBHOOK_PATH=/cryptobot/webhook
```

Если в проекте используются дополнительные сервисы, смотрите [bot/config.py](/root/banano_kling/bot/config.py) и `.env.example`.

## Установка и запуск

### Локальный запуск

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

После настройки `.env`:

```bash
./start.sh
```

Остановка:

```bash
./stop.sh
```

Скрипт `stop.sh` настроен так, чтобы останавливать только этот бот, а не все процессы `python -m bot.main` в системе.

## Тесты

В проекте есть unit и integration-style тесты.

Основные группы:

- `tests/test_keyboards.py` — клавиатуры и доступные действия
- `tests/test_database.py` — база данных, пользователи, транзакции, статусы задач
- `tests/test_kling_service.py` — новые интеграции Kling 2.5 Turbo и AI Avatar
- `tests/test_generation_helpers.py` — легкие helper-функции генерации
- `tests/test_webhook_handler.py` — webhook-обработчики

Запуск всех тестов:

```bash
pytest
```

Запуск только ключевых свежих тестов:

```bash
pytest tests/test_keyboards.py tests/test_database.py tests/test_kling_service.py tests/test_generation_helpers.py
```

Если нужен отдельный набор зависимостей для тестов, смотрите [tests/requirements.txt](/root/banano_kling/tests/requirements.txt).

## Что стоит проверять после изменений

После любого заметного изменения в генерации полезно проверить:

1. Открывается ли нужный экран мастера
2. Можно ли пройти сценарий без пропуска обязательных шагов
3. Правильно ли отображаются подписи моделей
4. Совпадают ли настройки в UI с документацией провайдера
5. Корректно ли завершается задача через webhook
6. Возвращаются ли кредиты при внешней ошибке провайдера

## Особенности безопасности и устойчивости

- Жесткие внешние фильтры провайдеров не считаются внутренней ошибкой бота
- Для чувствительных fashion/edit запросов добавлен мягкий fallback, если строгая модель может отфильтровать безопасный запрос
- Критические сценарии аватаров и edit-flow не стартуют без обязательных файлов
- Новые интеграции строятся через task-based API и webhook completion

## Для разработчика

Если вы добавляете новую модель, полезный порядок такой:

1. Добавить сервисный вызов в `bot/services/`
2. Подключить модель в `bot/keyboards.py`
3. Добавить ветку в `bot/handlers/generation.py`
4. Обновить friendly label в `bot/main.py`, если модель приходит через webhook
5. Добавить цену в `data/price.json`
6. Написать unit-тесты на payload и UI
7. Обновить README

## Текущее направление проекта

Сейчас проект уже умеет:

- понятные пошаговые фото- и видео-сценарии
- GPT Image 2 с t2i и i2i
- Seedream 4.5 Edit по документации
- Kling 2.5 Turbo Pro по документации
- Kling AI Avatar Standard и Pro по документации
- более дружелюбные тексты для новичков

Следующий естественный шаг развития: держать таким же понятным весь остальной интерфейс, включая историю, пополнение, поддержку и партнерские экраны.
