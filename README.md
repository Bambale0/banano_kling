# Banano Kling AI Bot

## 🎯 Описание

Telegram-бот для генерации изображений и видео с использованием передовых AI-моделей (Gemini/NanoBanana, Kling 3.0/2.6, FLUX.2 Pro, Seedream, Grok). Поддерживает:
- Text-to-Image/Video
- Image-to-Image/Video (редактирование)
- Motion Control (перенос движения)
- Пакетная генерация (batch editing)
- Референсные изображения (до 14 шт)
- Платежи: CryptoBot (Crypto Pay API)
- Партнёрская программа
- Админ-панель

## 🏗️ Архитектура

```
banano_kling/
├── bot/
│   ├── main.py              # aiohttp сервер + webhook handlers (Telegram, Kling, Kie.ai, CryptoBot)
│   ├── config.py            # Конфиг из .env (API ключи, webhook URLs)
│   ├── database.py          # SQLite модели: User, Transaction, GenerationTask
│   ├── states.py            # FSM состояния (aiogram)
│   ├── keyboards.py         # Inline/RK клавиатуры (меню, настройки, генерация)
│   ├── handlers/            # User flows
│   │   ├── admin.py         # Админ-панель (статистика, рассылка, управление пользователями)
│   │   ├── batch_generation.py # Пакетная генерация (до 10 изображений)
│   │   ├── common.py        # /start, /help, баланс, партнёрка, настройки, ИИ-ассистент
│   │   ├── generation.py    # Основная генерация (image/video/motion/edit)
│   │   ├── image_analyzer.py # Анализ фото → промпт
│   │   └── payments.py      # Платежи (CryptoBot)
│   ├── services/            # AI/платёжные интеграции
│   │   ├── gemini_service.py     # NanoBanana/Gemini (text2img, edit, refs до 14)
│   │   ├── kling_service.py      # Kling 3.0/2.6 (PiAPI/Kie.ai/Replicate) - video gen/motion
│   │   ├── nano_banana_2/pro_service.py # Banana 2/Pro (Gemini 3.1 Flash/Pro)
│   │   ├── seedream_service.py    # Seedream (Novita AI)
│   │   ├── grok_service.py        # Grok Imagine (image-to-video)
│   │   ├── cryptobot_service.py # Платежи
│   │   ├── preset_manager.py      # Цены/пресеты из JSON
│   │   └── ai_assistant_service.py # ИИ-ассистент (Grok/Claude)
│   └── utils/               # Help texts, validators
├── data/                    # price.json (пакеты/цены), presets.json
├── static/uploads/          # Загруженные файлы (nginx static)
├── logs/                    # Логи
└── requirements.txt
```

### Детальная структура модулей

#### Handlers (User Flows)
| Handler | Ключевые функции |
|---------|------------------|
| **admin.py** | `cmd_admin()`, `admin_show_stats()`, `admin_add_credits_prompt()`, `admin_broadcast_prompt()` |
| **batch_generation.py** | `show_batch_edit_start()`, `process_batch_image()`, `execute_batch()`, `show_batch_results()` |
| **common.py** | `cmd_start()`, `cmd_help()`, `back_to_main()`, `show_settings()`, `handle_ai_assistant_message()` |
| **generation.py** | `show_create_video_menu()`, `handle_v_model()`, `handle_img_ref_upload_new()`, `handle_video_prompt_text()` |
| **image_analyzer.py** | `photo_to_prompt_handler()`, `analyze_photo()` |
| **payments.py** | `show_topup_menu()`, `initiate_payment()`, `handle_cryptobot_webhook()` |

#### Services (Интеграции)
| Service | Ключевые методы |
|---------|-----------------|
| **gemini_service.py** | `generate_image()`, `edit_image()`, `generate_with_references()`, `generate_with_search()` |
| **kling_service.py** | `generate_video()`, `generate_motion_control()`, `generate_omni_video_generation()`, `get_task_status()` |
| **nano_banana_2/pro_service.py** | `generate_image()`, `create_task()`, `get_task_status()` |
| **seedream_service.py** | `generate_image()`, `wait_for_completion()` |
| **cryptobot_service.py** | `create_invoice()`, `get_invoice()`, `verify_webhook_signature()` |
| **preset_manager.py** | `get_generation_cost()`, `get_video_cost()`, `get_packages()` |

#### Database (database.py)
**Модели:** `User`, `Transaction`, `GenerationTask`, `BatchJob`

**Ключевые queries:**
- `get_or_create_user(telegram_id)`
- `add_credits/deduct_credits(telegram_id, amount)`
- `add_generation_task(...)`
- `complete_video_task(task_id, result_url)`
- `get_admin_stats()` → {users, generations, revenue}

#### Keyboards (keyboards.py)
- `get_main_menu_keyboard()`, `get_create_video/image_keyboard()`
- `get_model_selection_keyboard()`, `get_reference_images_keyboard()`
- `get_payment_packages_keyboard()`

### FSM States (states.py) - Полный список
```
GenerationStates:
- waiting_for_input/image/video/prompt/ref_video/motion_character/video_start_image/confirming_generation/selecting_batch_count
- uploading_reference_images/videos/confirming_reference_images
- waiting_for_batch_image/prompt/aspect_ratio/selecting_duration/aspect_ratio/quality

PaymentStates: selecting_package/confirming_payment/waiting_payment

AdminStates: waiting_broadcast_text/confirming_broadcast/waiting_user_id/waiting_credits_amount

BatchGenerationStates: selecting_mode/preset/entering_prompts/uploading_references/confirming_batch/selecting_batch_count

ImageAnalyzerStates: waiting_for_photo

AIAssistantStates: main_menu/settings/waiting_for_message
```

### User Flows (Диаграммы)
```
Главное меню → Создать фото/видео → Refs (опц.) → Модель/Формат → Промпт → Генерация → Результат

Платежи: Меню → Пополнить → Пакет → Оплата → Webhook → Credits

Motion Control: Меню → Motion → Std/Pro → Фото персонажа → Видео движения → Kling API

Batch: Меню → Batch → Фото → Промпт → Aspect → Запуск → Галерея/Упскейл
```

### Webhook Flows
```
Telegram → /webhook → Dispatcher (aiogram)

Kling/Kie/Replicate → /webhook/kling → complete_video_task() → Send to user

CryptoBot → /cryptobot/webhook → add_credits() → Notify user
```

## 🚀 Установка и запуск

```bash
git clone <repo>
cd banano_kling
pip install -r requirements.txt
cp .env.example .env  # Настройте ключи!
./start.sh  # Запуск (docker-compose или systemd)
```

**Запуск разработки:**
```bash
isort . && black . && ./stop.sh && ./start.sh && tail -f logs/vk_bot.log
```

## ⚙️ Конфигурация (.env)

```
# Telegram
BOT_TOKEN=your_bot_token

# Webhook (production)
WEBHOOK_HOST=https://your-domain.com
WEBHOOK_PATH=/webhook
WEBHOOK_PORT=8443

# AI API Keys
NANOBANANA_API_KEY=...
KIE_AI_API_KEY=...      # Kling 3.0 / Motion Control
REPLICATE_API_TOKEN=... # Kling fallback
NOVITA_API_KEY=...      # Seedream/FLUX
GEMINI_API_KEY=...      # Legacy

# Payments (CryptoBot)
PAYMENT_PROVIDER=cryptobot
CRYPTOBOT_API_TOKEN=...
CRYPTOBOT_USE_TESTNET=0
CRYPTOBOT_WEBHOOK_PATH=/cryptobot/webhook

# Admins
ADMIN_IDS=123,456
```

## 🗄️ База данных (SQLite: bot.db)

### Таблицы
- **users**: telegram_id, credits, referral_code, referred_by, referral_earned, has_paid, partner_agreed_at, partner_total_revenue_rub, partner_balance_rub, partner_withdrawn_rub, partner_tier (basic/gold/pro)
- **transactions**: order_id, user_id, credits, amount_rub, status (pending/completed), provider (cryptobot)
- **generation_tasks**: task_id, user_id, type (image/video), preset_id, model, duration, aspect_ratio, prompt, cost, result_url
- **batch_jobs**: job_id, user_id, mode, total_cost, results_count
- **user_settings**: preferred_model/video_model/i2v_model/image_service
- **partner_withdrawals**: user_id, amount_rub, method, requisites, status (requested/completed)
- **referrals**: referrer_id, referred_id, bonus_credits

### Ключевые функции
```python
get_or_create_user(telegram_id) → User
add_credits/deduct_credits(telegram_id, amount)
add_generation_task(...) → bool
complete_video_task(task_id, result_url)
get_admin_stats() → dict (users, revenue, generations)
process_referral(referred_id, code) → bool
credit_first_payment_referral_bonus(...) → dict (mode: partner/banana, value, %)
get_partner_overview(id) → dict (balance_rub, tier, referrals_count)
create_partner_withdrawal(id, amount, method, requisites) → bool
```

## 👥 Реферальная/Партнёрская система

### Как работает
1. **Регистрация:** Новый пользователь получает уникальный `referral_code` (8 символов).
2. **Приглашение:** `t.me/bot?start=ref_XXXXXX` → `process_referral()` закрепляет за мастер-партнёром (ID: 339795159).
3. **Бонус за регистрацию:** 5🍌 новому (signup_bonus).
4. **Первая оплата реферала:** `credit_first_payment_referral_bonus()` начисляет мастеру:
   - **Banana бонус:** 10% от credits (если не партнёр).
   - **Partner %:** basic=30%, gold=35% (≥100k ₽), pro=50% (≥1M ₽) от RUB.
5. **Уровни:** `get_partner_tier_by_total(total_revenue_rub)`.
6. **Вывод:** `create_partner_withdrawal()` (мин. 2000₽), статус: requested → completed.

### Flows (common.py)
- `/ref` или "Партнёрка" → `render_partner_program()` → stats, link.
- "Принять оферту" → `accept_partner_agreement()` → tier= basic.
- "Статистика" → `get_partner_overview()` (balance, tier, revenue).
- "Вывод" → `create_partner_withdrawal()`.

### DB интеграция
- `generate_referral_code()`: уникальный код (race-safe).
- `set_user_referrer()`: one-time bind.
- Partner fields: `partner_balance_rub += bonus_rub`, `tier` auto-update.

**Централизованно:** Все бонусы → мастер-партнёр (339795159).


## 🎛️ FSM Состояния (aiogram StatesGroup)

### GenerationStates
- waiting_for_input/image/video/prompt/ref_video/motion_character/video_start_image
- confirming_generation / selecting_batch_count
- uploading_reference_images/videos / confirming_reference_images
- waiting_for_batch_image/prompt/aspect_ratio

### PaymentStates
- selecting_package / confirming_payment / waiting_payment

### AdminStates
- waiting_broadcast_text / confirming_broadcast / waiting_user_id / waiting_credits_amount

### BatchGenerationStates
- selecting_mode/preset / entering_prompts / uploading_references / confirming_batch

### ImageAnalyzerStates
- waiting_for_photo

### AIAssistantStates
- main_menu / settings / waiting_for_message

## 📱 Handlers (User Flows)

### common.py (/start, меню)
- Главное меню, баланс, партнёрка, настройки, ИИ-ассистент
- Motion Control (Kling 2.6): фото персонажа + видео движения

### generation.py (основная логика)
- create_image/video (новый UX: refs → params → prompt)
- Модели: FLUX, NanoBanana(2/Pro), Seedream(4.5/5/Lite/Edit), Z-Image Turbo
- Видео: text/imgtxt/video modes (Kling 3/2.6, Grok)
- Refs: до 14 img / 5 video
- Edit: image/video input types

### payments.py
- Пакеты (mini/standard/optimal/pro/studio)
- CryptoBot (webhook)
- Ручная проверка /check_payment_

### admin.py
- /admin: stats, users (add/deduct credits), broadcast

### batch_generation.py
- Batch edit (img + prompt + refs → multiple outputs)
- Upscale (2K/4K)

## 🔌 Services (Интеграции)

| Service | Функции | Webhook |
|---------|---------|---------|
| **Gemini/NanoBanana** | t2i/i2i/edit/refs(14)/search/4K | `/webhook/kie_ai` |
| **Kling (Kie.ai/PiAPI/Replicate)** | t2v/i2v/v2v/motion(2.6)/omni | `/webhook/kling` |
| **Seedream/Novita** | t2i (4.5/5/Lite/Edit) | `/webhook/seedream` |
| **Grok** | i2v (Imagine) | - |
| **CryptoBot** | Платежи (Crypto Pay API) | `/cryptobot/webhook` |
| **PresetManager** | Цены из price.json, пакеты | - |

### Webhooks (main.py)
- Telegram: `/webhook`
- Kling/Kie/Replicate: `/webhook/kling` (signature verify)
- Health: `/health`

## 💰 Цены (data/price.json)

### Пакеты бананов
| Пакет | Бананы | ₽ | Популярный |
|-------|--------|----|------------|
| Mini | 15 | 150 | - |
| Стандарт | 30 | 250 | - |
| Оптимальный | 50 | 400 | ⭐ |
| Pro | 100 | 700 | - |
| Студия | 200 | 1400 | - |

### Модели изображений
| Модель | Цена |
|--------|------|
| FLUX.2 Pro | 5🍌 |
| Nano Banana Pro | 5🍌 |
| Gemini 3 Pro | 5🍌 |
| Banana 2 | 7🍌 |
| Seedream Edit | 7🍌 |

### Видео (Kling)
| Модель/Duration | 5s | 10s | 15s |
|-----------------|----|-----|-----|
| v3_std | 15 | 30 | 45 |
| v3_pro | 15 | 30 | 45 |

## 👑 Админ-панель (/admin)

- Статистика (users, generations, revenue)
- Управление пользователями (credits +/-)
- Рассылка (broadcast)

## 🔧 Разработка

- **Линтинг/Форматирование:** `isort . && black .`
- **Тесты:** `pytest tests/`
- **Логи:** `tail -f logs/bot.log`
- **Static cleanup:** Авто каждые 6ч (static/uploads)
