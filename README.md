# 🍌 Banano Kling — AI Image & Video Generation Telegram Bot

Telegram-бот для генерации изображений и видео с помощью AI. Поддерживает генерацию изображений (Gemini, Seedream, FLUX) и видео (Kling AI), пакетную обработку, систему кредитов и оплату через Т-Банк.

## 🚀 Возможности

### Генерация изображений
- 📸 **Фотореалистичные портреты** — профессиональные портреты людей
- 🎨 **Логотипы и дизайн** — создание логотипов с текстом
- 😊 **Стикеры** — милые персонажи в мультяшном стиле
- 🏞 **Пейзажи** — красивые природные и городские сцены
- 🌀 **Абстрактное искусство** — генерация абстрактных изображений
- 🎨 **Seedream AI** — ByteDance Seedream 5.0 Lite для быстрой генерации

### Редактирование изображений
- ➕ **Добавить объект** — добавление элементов на фото
- 🎭 **Сменить стиль** — преобразование в различные художественные стили
- 🔧 **Реставрация** — восстановление старых фотографий
- 🌄 **Сменить фон** — замена фона на изображении
- 🔄 **Seedream** — преобразование изображений

### Генерация видео
- 📝 **Текст → Видео** — создание видео из текстового описания (Kling V3 Pro/Std)
- 🖼 **Изображение → Видео** — анимация статичных изображений
- 📦 **Продуктовое видео** — демонстрация товаров для соцсетей
- 🎬 **Природные сцены** — красивые пейзажи с анимацией

### Видео-эффекты
- 🎨 **Стилизация видео** — применение художественных стилей
- ✨ **Улучшение качества** — повышение разрешения и качества

### Пакетная обработка
- 🎭 **4 стиля** — применение 4 разных стилей к одному фото
- ✨ **6 эффектов** — 6 различных визуальных эффектов
- 🎨 **3 сезона** — сезонные вариации изображения

### Система
- 💳 **Кредитная система** — оплата через Т-Банк
- 🔧 **Админ-панель** — статистика, управление пользователями, рассылки
- ⚙️ **Настройки** — выбор модели, сервиса, качества

## 📋 Требования

- Python 3.10+
- Telegram Bot Token
- API ключи (см. ниже)

## 🛠 Установка

### 1. Клонирование и создание виртуального окружения

```bash
cd /path/to/project
python -m venv venv
source venv/bin/activate  # Linux/Mac
# или
venv\Scripts\activate  # Windows
```

### 2. Установка зависимостей

```bash
pip install -r requirements.txt
```

### 3. Настройка переменных окружения

Создайте файл `.env` в корне проекта:

```env
# Telegram Bot
BOT_TOKEN=your_telegram_bot_token

# AI API Keys
GEMINI_API_KEY=your_gemini_api_key
KLING_API_KEY=your_kling_api_key
NOVITA_API_KEY=your_novita_api_key
SEEDREAM_API_KEY=your_seedream_api_key
OPENROUTER_API_KEY=your_openrouter_api_key

# AI Assistant (опционально)
AI_ASSISTANT_API_KEY=your_openrouter_api_key

# Т-Банк (опционально, для платежей)
TBANK_TERMINAL_KEY=your_terminal_key
TBANK_SECRET_KEY=your_secret_key
TBANK_API_URL=https://rest-api.tbankapi.com

# Webhook настройки (для production)
WEBHOOK_HOST=https://your-domain.com
WEBHOOK_PORT=8080
WEBHOOK_PATH=/webhook
```

### 4. Запуск

**Режим разработки (polling):**
```bash
python -m bot.main
```

**Production (webhook):**
```bash
export WEBHOOK_HOST=https://your-domain.com
export WEBHOOK_PORT=8080
python -m bot.main
```

## 📁 Структура проекта

```
banano_kling/
├── bot/                          # Основной код бота
│   ├── main.py                   # Точка входа, веб-сервер
│   ├── config.py                 # Конфигурация
│   ├── database.py               # SQLite база данных
│   ├── keyboards.py              # Inline клавиатуры
│   ├── states.py                 # FSM состояния
│   ├── handlers/                 # Обработчики команд
│   │   ├── admin.py              # Админ-команды
│   │   ├── common.py             # /start, /help, настройки
│   │   ├── generation.py         # Генерация изображений и видео
│   │   ├── payments.py            # Оплата и баланс
│   │   └── batch_generation.py   # Пакетная обработка
│   ├── services/                 # Интеграции с API
│   │   ├── gemini_service.py     # Google Gemini
│   │   ├── kling_service.py      # Kling AI
│   │   ├── novita_service.py     # Novita AI (FLUX)
│   │   ├── seedream_service.py   # ByteDance Seedream
│   │   ├── tbank_service.py      # Т-Банк платежи
│   │   ├── batch_service.py      # Пакетная обработка
│   │   └── preset_manager.py     # Управление пресетами
│   └── utils/                    # Утилиты
│       ├── validators.py         # Валидация
│       └── help_texts.py         # Справки
├── data/                         # Данные
│   ├── presets.json              # Пресеты генерации
│   └── price.json                # Прайс-лист и цены
├── static/                      # Статические файлы
│   └── uploads/                  # Загруженные файлы
├── logs/                        # Логи
│   └── bot.log
├── tests/                       # Тесты
├── .env                         # Переменные окружения
├── requirements.txt             # Python зависимости
├── start.sh                     # Скрипт запуска
└── stop.sh                      # Скрипт остановки
```

## 🎯 AI Сервисы

### Изображение
| Сервис | Модель | Особенности |
|--------|--------|-------------|
| Google Gemini | gemini-2.5-flash-image, gemini-3-pro-image-preview | Фотореалистичные изображения, редактирование |
| Novita AI | FLUX.2 Pro | Высококачественная генерация |
| Seedream | Seedream 5.0 Lite | ByteDance технология, быстрая генерация |

### Видео
| Сервис | Модель | Особенности |
|--------|--------|-------------|
| Kling AI | V3 Pro/Std | Текст→Видео, Изображение→Видео |
| Kling AI | V3 Omni Pro/Std | Расширенные возможности |
| Kling AI | V3 Omni R2V | Референсное видео |

## 💳 Система кредитов

### Пакеты

| Пакет | Кредиты | Цена (₽) |
|-------|---------|----------|
| 🍌 Мини | 15 | 150 |
| 🍌🍌 Стандарт | 30 | 250 |
| 🍌🍌🍌 Оптимальный | 50 | 400 |
| 🍌🍌🍌🍌 Про | 100 | 700 |
| 🍌🍌🍌🍌🍌 Студия | 200 | 1400 |

### Стоимость генерации

**Изображения:**
- Gemini 2.5 Flash: 3 кредита
- Gemini 3 Pro: 5 кредитов
- Seedream: 3 кредита

**Видео:**
- Kling V3 Std: 6-20 кредитов (зависит от длительности)
- Kling V3 Pro: 8-24 кредитов

## 🔧 Пресеты

Пресеты находятся в `data/presets.json`. Каждый пресет содержит:
- `id` — уникальный идентификатор
- `name` — отображаемое имя
- `prompt` — шаблон промпта с плейсхолдерами `{placeholder}`
- `model` — используемая модель
- `cost` — стоимость в кредитах
- `requires_input` — требуется ли ввод от пользователя
- `requires_upload` — требуется ли загрузка изображения

## 🖥 Администрирование

### Доступ к админ-панели
Используйте команду `/admin` или кнопку в меню.

### Возможности
- 📊 **Статистика** — количество пользователей, генераций, доход
- 👥 **Управление пользователями** — просмотр, изменение баланса
- 💰 **Начисление/списание кредитов**
- 📢 **Рассылка сообщений**
- 🔄 **Перезагрузка пресетов** без перезапуска бота

## 🌐 Webhook URLs

Для работы в production режиме настройте вебхуки:

```
Telegram:  https://your-domain.com/webhook
Т-Банк:    https://your-domain.com/tbank/webhook
Kling:     https://your-domain.com/webhook/kling
Seedream:  https://your-domain.com/webhook/seedream
Novita:    https://your-domain.com/webhook/novita
```

## 🚦 Системные команды

```bash
./start.sh      # Запуск бота
./stop.sh       # Остановка бота
python -m bot.main --help  # Справка
```

## 🧪 Тесты

```bash
pytest tests/
```

## 📝 Лицензия

MIT License

## 👤 Поддержка

По вопросам: @S_k7222
