# 🍌 UI Architecture Documentation

Документация по пользовательскому интерфейсу бота. Всё о том, как устроены меню, кнопки и переходы между ними.

## 📱 Главное меню

**Файл:** `bot/keyboards.py` → `get_main_menu_keyboard()`

```
┌─────────────────────────────────────┐
│        ГЛАВНОЕ МЕНЮ                 │
├─────────────────────────────────────┤
│ 🖼 Генерация фото                   │ → generate_image
│ ✏️ Редактировать фото               │ → edit_image
│ 🎬 Генерация видео                   │ → generate_video
│ 🖼 Фото в видео                     │ → image_to_video
│ 🎬 Motion Control                   │ → menu_motion_control
│ ✂️ Видео-эффекты                    │ → edit_video
├─────────────────────────────────────┤
│ ⚡ ПАКЕТНОЕ РЕДАКТИРОВАНИЕ (20+ 🍌) │ → menu_batch_edit
├─────────────────────────────────────┤
│ ⚙️ Настройки                         │ → menu_settings
│ 💳 Пополнить баланс                 │ → menu_buy_credits
│ 📊 Мой баланс                       │ → menu_balance
│ ❓ Помощь                           │ → menu_help
└─────────────────────────────────────┘
```

### Callback Data Mapping

| Кнопка | callback_data | Обработчик |
|--------|---------------|------------|
| Генерация фото | `generate_image` | `generation.py` |
| Редактировать фото | `edit_image` | `generation.py` |
| Генерация видео | `generate_video` | `generation.py` |
| Фото в видео | `image_to_video` | `generation.py` |
| Motion Control | `menu_motion_control` | `common.py` |
| Видео-эффекты | `edit_video` | `generation.py` |
| Пакетное редактирование | `menu_batch_edit` | `batch_generation.py` |
| Настройки | `menu_settings` | `common.py` |
| Пополнить баланс | `menu_buy_credits` | `payments.py` |
| Мой баланс | `menu_balance` | `common.py` |
| Помощь | `menu_help` | `common.py` |

---

## 📂 Навигация по категориям

После выбора типа генерации (фото/видео) пользователь попадает в категорию:

### Генерация изображений
**callback:** `generate_image` → Показывает `get_category_keyboard("image_generation")`

```
📂 ГЕНЕРАЦИЯ ИЗОБРАЖЕНИЙ
├─ 📸 Фотореалистичный портрет (10🍌)
├─ 🎨 Логотип с текстом (15🍌)
├─ 😊 Стикер персонаж (5🍌)
├─ 🏞 Пейзаж (8🍌)
└─ 🌀 Абстрактное искусство (5🍌)
```

### Редактирование изображений
**callback:** `edit_image` → Показывает `get_category_keyboard("image_editing")`

```
📂 РЕДАКТИРОВАНИЕ ФОТО
├─ ➕ Добавить объект (8🍌)
├─ 🎭 Сменить стиль (8🍌)
├─ 🔧 Реставрация фото (12🍌)
└─ 🌄 Сменить фон (10🍌)
```

### Генерация видео
**callback:** `generate_video` → Показывает `get_category_keyboard("video_generation")`

```
📂 ГЕНЕРАЦИЯ ВИДЕО
├─ 📝 Текст → Видео PRO (30🍌)
├─ 📝 Текст → Видео (20🍌)
├─ 🖼 Изображение → Видео PRO (35🍌)
├─ 🖼 Изображение → Видео (25🍌)
└─ ...
```

---

## ⚙️ Настройки

**Файл:** `bot/keyboards.py` → `get_settings_keyboard()`

```
┌─────────────────────────────────────────────────┐
│           🖼 ИЗОБРАЖЕНИЯ                        │
├─────────────────────────────────────────────────┤
│ ✅ Текущий: ✨ FLUX.2 Pro (Novita)             │
├─────────────────────────────────────────────────┤
│ 🟢 ✨ FLUX.2 Pro (Novita)                      │ → settings_service_novita
│     До 1536px • Лучшее качество • 3🍌          │
│ ⚪ 🍌 Nano Banana                               │ → settings_service_nanobanana
│     До 4K • Быстрая • 3🍌                      │
│ ⚪ 💎 Banana Pro                                │ → settings_service_banana_pro
│     Профи качество • 4K • 5🍌                  │
│ ⚪ 🎨 Seedream                                  │ → settings_service_seedream
│     Стили • Арты • 3🍌                         │
│ ⚪ 🚀 Z-Image Turbo LoRA                       │ → settings_service_z_image_turbo
│     Быстрая • Свои LoRA • 3🍌                  │
└─────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────┐
│           🎬 ТЕКСТ → ВИДЕО                     │
├─────────────────────────────────────────────────┤
│ ✅ Текущий: ⚡ Kling 2.6                       │
├─────────────────────────────────────────────────┤
│ 🟢 ⚡ Kling 2.6 (8🍌/5сек) ✨ НОВИНКА        │ → settings_video_v26_pro
│ ⚪ ⚡ Kling 3 Standard (6🍌/5сек)              │ → settings_video_v3_std
│ ⚪ 💎 Kling 3 Pro (8🍌/5сек)                   │ → settings_video_v3_pro
│ ⚪ 🔄 Kling 3 Omni Std (8🍌/5сек)              │ → settings_video_v3_omni_std
│ ⚪ 💎 Kling 3 Omni Pro (8🍌/5сек)              │ → settings_video_v3_omni_pro
│ ⚪ ✂️ V2V Std (стилизация) (8🍌/5сек)           │ → settings_video_v3_omni_std_r2v
│ ⚪ 💎 V2V Pro (8🍌/5сек)                       │ → settings_video_v3_omni_pro_r2v
└─────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────┐
│           📺 ФОТО → ВИДЕО                       │
├─────────────────────────────────────────────────┤
│ ✅ Текущий: ⚡ Std                              │
├─────────────────────────────────────────────────┤
│ 🟢 ⚡ Image-to-Video Std                       │ → settings_i2v_v3_std
│ ⚪ 💎 Image-to-Video Pro                       │ → settings_i2v_v3_pro
│ ⚪ 🔄 Omni Std                                  │ → settings_i2v_v3_omni_std
│ ⚪ 💎 Omni Pro                                  │ → settings_i2v_v3_omni_pro
└─────────────────────────────────────────────────┘
```

### Callback Data для настроек

| Категория | callback_data | Действие |
|-----------|---------------|----------|
| Изображение | `settings_service_novita` | Сохраняет `image_service = "novita"` |
| Изображение | `settings_service_nanobanana` | Сохраняет `image_service = "nanobanana"` |
| Изображение | `settings_service_banana_pro` | Сохраняет `image_service = "banana_pro"` |
| Изображение | `settings_service_seedream` | Сохраняет `image_service = "seedream"` |
| Изображение | `settings_service_z_image_turbo` | Сохраняет `image_service = "z_image_turbo"` |
| Видео | `settings_video_v26_pro` | Сохраняет `preferred_video_model = "v26_pro"` |
| Видео | `settings_video_v3_std` | Сохраняет `preferred_video_model = "v3_std"` |
| Видео | `settings_video_v3_pro` | Сохраняет `preferred_video_model = "v3_pro"` |
| Видео | `settings_video_v3_omni_std` | Сохраняет `preferred_video_model = "v3_omni_std"` |
| Видео | `settings_video_v3_omni_pro` | Сохраняет `preferred_video_model = "v3_omni_pro"` |
| Видео | `settings_video_*_r2v` | Сохраняет `preferred_video_model = "..."` |
| Фото→Видео | `settings_i2v_v3_std` | Сохраняет `preferred_i2v_model = "v3_std"` |
| Фото→Видео | `settings_i2v_v3_pro` | Сохраняет `preferred_i2v_model = "v3_pro"` |
| Фото→Видео | `settings_i2v_v3_omni_std` | Сохраняет `preferred_i2v_model = "v3_omni_std"` |
| Фото→Видео | `settings_i2v_v3_omni_pro` | Сохраняет `preferred_i2v_model = "v3_omni_pro"` |

---

## 🎯 Выбор пресета и запуск

После выбора пресета (`callback_data="preset_{preset_id}"`):

```
┌─────────────────────────────────────────────────┐
│           {Название пресета}                    │
├─────────────────────────────────────────────────┤
│ {Описание пресета}                               │
│                                                 │
│ 💰 Стоимость: {cost}🍌                          │
│                                                 │
│ [{Если требует ввод:}]                           │
│ ✏️ Ввести свой вариант  → custom_{preset_id}    │
│ 🎲 Использовать пример  → default_{preset_id}   │
│                                                 │
│ [{Если видео:}]                                  │
│ ⏱ Длительность          → opt_duration_{id}     │
│ 📐 Формат               → opt_ratio_{id}        │
│                                                 │
│ ▶️ Запустить генерацию    → run_{preset_id}     │
│ 🔙 Назад                  → back_cat_{prefix}   │
└─────────────────────────────────────────────────┘
```

### Callback Data для пресетов

| Действие | callback_data | Обработчик |
|----------|---------------|------------|
| Выбор пресета | `preset_{id}` | `generation.py` → `show_preset_details()` |
| Свой ввод | `custom_{id}` | Переход в FSM `waiting_for_input` |
| Пример | `default_{id}` | Запуск с дефолтными значениями |
| Длительность | `opt_duration_{id}` | Показ `get_duration_keyboard()` |
| Формат | `opt_ratio_{id}` | Показ `get_aspect_ratio_keyboard()` |
| Запуск | `run_{id}` | Запуск генерации |
| Назад | `back_cat_{prefix}` | Возврат в категорию |

---

## 💳 Оплата

**callback:** `menu_buy_credits` → `payments.py`

```
┌─────────────────────────────────────────────────┐
│           💳 ПОПОЛНЕНИЕ БАЛАНСА                │
├─────────────────────────────────────────────────┤
│ 🍌 Мини: 15🍌 за 150₽                         │ → buy_mini
│ 🍌🍌 Стандарт: 30🍌 за 250₽                   │ → buy_standard
│ 🍌🍌🍌 Оптимальный: 50🍌 за 400₽ 🔥           │ → buy_optimal
│ 🍌🍌🍌🍌 Про: 100🍌 за 700₽                   │ → buy_pro
│ 🍌🍌🍌🍌🍌 Студия: 200🍌 за 1400₽            │ → buy_studio
├─────────────────────────────────────────────────┤
│ 🔙 Назад                                        │ → back_main
└─────────────────────────────────────────────────┘
```

---

## 🎬 Motion Control

**callback:** `menu_motion_control` → Показывает `get_motion_control_keyboard()`

```
┌─────────────────────────────────────────────────┐
│           🎬 MOTION CONTROL                      │
├─────────────────────────────────────────────────┤
│ Перенос движения с референсного видео           │
│ на твоё фото!                                  │
│                                                 │
│ 📝 Как это работает:                            │
│ 1. Загрузи фото персонажа                       │
│ 2. Загрузи видео с движением                   │
│ 3. Получи анимированное фото!                  │
│                                                 │
├─────────────────────────────────────────────────┤
│ ⚡ Motion Control Standard                      │ → motion_control_std
│     8🍌 за 5 сек • Быстрее                    │
│                                                 │
│ 💎 Motion Control Pro                          │ → motion_control_pro
│     10🍌 за 5 сек • Лучше качество            │
│                                                 │
├─────────────────────────────────────────────────┤
│ 🔙 Назад                                        │ → back_main
└─────────────────────────────────────────────────┘
```

### Callback Data для Motion Control

| Кнопка | callback_data | Обработчик |
|--------|---------------|------------|
| Motion Control Std | `motion_control_std` | `common.py` → `start_motion_control_std()` |
| Motion Control Pro | `motion_control_pro` | `common.py` → `start_motion_control_pro()` |

### Процесс Motion Control

```
menu_motion_control
    ↓ [выбор Std/Pro]
callback: motion_control_std / motion_control_pro
    ↓
Проверка баланса (8/10 🍌)
    ↓ [достаточно]
FSM: waiting_for_image
    ↓ [загрузка фото]
Запрос видео с движением
    ↓ [загрузка видео]
Запуск генерации (Kling 2.6 Motion)
    ↓
Отправка результата
```

---

## 🎬 Опции видео

**callback:** `opt_duration_{id}` или `opt_ratio_{id}`

### Длительность
```
┌─────────────────────────────────────────────────┐
│           ⏱ ВЫБЕРИТЕ ДЛИТЕЛЬНОСТЬ              │
├─────────────────────────────────────────────────┤
│ ✅ 5 сек          │ 10 сек                    │
│ 15 сек                                         │
├─────────────────────────────────────────────────┤
│ 🔙 Назад                                        │
└─────────────────────────────────────────────────┘
```

### Формат
```
┌─────────────────────────────────────────────────┐
│           📐 ВЫБЕРИТЕ ФОРМАТ                   │
├─────────────────────────────────────────────────┤
│ 📺 Landscape (YouTube) 16:9 ✅                 │
│ 📱 Vertical (TikTok/Reels) 9:16                │
│ ⬜ Square (Instagram) 1:1                       │
├─────────────────────────────────────────────────┤
│ 🔙 Назад                                        │
└─────────────────────────────────────────────────┘
```

---

## 🔄 FSM Состояния

**Файл:** `bot/states.py`

### GenerationStates

```
GenerationStates
│
├── waiting_for_input          # Ожидание текстового ввода от пользователя
├── waiting_for_image          # Ожидание загрузки фото
├── waiting_for_video          # Ожидание загрузки видео
├── confirming_generation       # Подтверждение перед запуском
├── selecting_batch_count      # Выбор кол-ва изображений
│
├── uploading_reference_images      # Загрузка референсных (до 14)
├── confirming_reference_images     # Подтверждение референсов
│
├── waiting_for_batch_image    # Ожидание фото для пакетной обработки
├── waiting_for_batch_prompt   # Ожидание промпта для пакетной
├── waiting_for_batch_aspect_ratio  # Выбор формата для пакета
│
├── selecting_duration         # Выбор длительности видео
├── selecting_aspect_ratio     # Выбор формата видео
└── selecting_quality          # Выбор качества видео
```

### PaymentStates

```
PaymentStates
│
├── selecting_package          # Выбор пакета
├── confirming_payment        # Подтверждение оплаты
└── waiting_payment           # Ожидание оплаты (проверка статуса)
```

### AdminStates

```
AdminStates
│
├── waiting_broadcast_text    # Ввод текста рассылки
├── confirming_broadcast      # Подтверждение рассылки
├── waiting_user_id           # Ввод ID пользователя
└── waiting_credits_amount    # Ввод кол-ва кредитов
```

### BatchGenerationStates

```
BatchGenerationStates
│
├── selecting_mode            # Выбор режима (pro/standard)
├── selecting_preset          # Выбор пресета
├── entering_prompts          # Ввод промптов
├── uploading_references      # Загрузка референсов
├── confirming_batch         # Подтверждение
└── selecting_batch_count    # Кол-во изображений
```

---

## 🔗 Полный путь пользователя

### Путь 1: Генерация изображения

```
/start
    ↓
get_main_menu_keyboard()
    ↓ [нажатие "Генерация фото"]
callback: generate_image
    ↓
show_category("image_generation")
    ↓
get_category_keyboard()
    ↓ [выбор пресета]
callback: preset_{id}
    ↓
show_preset_details()
    ↓
get_preset_action_keyboard()
    ↓ [свой ввод]
callback: custom_{id}
    ↓
FSM: waiting_for_input
    ↓ [ввод текста]
    ↓
execute_generation()
    ↓ [списание кредитов]
    ↓
Отправка результата
```

### Путь 2: Настройки

```
/start
    ↓
get_main_menu_keyboard()
    ↓ [нажатие "Настройки"]
callback: menu_settings
    ↓
show_settings()
    ↓
get_settings_keyboard()
    ↓ [выбор сервиса]
callback: settings_service_novita
    ↓
handle_settings_service()
    ↓ [сохранение в БД]
    ↓
Обновление клавиатуры
```

---

## 📁 Структура файлов UI

### bot/keyboards.py
Все клавиатуры бота. Каждая функция создаёт `InlineKeyboardBuilder` и возвращает `InlineKeyboardMarkup`.

### bot/handlers/
| Файл | Ответственность |
|------|-----------------|
| `common.py` | /start, /help, настройки, баланс, возврат в меню |
| `generation.py` | Генерация изображений/видео, редактирование |
| `payments.py` | Оплата, пополнение баланса |
| `admin.py` | Админ-панель, статистика |
| `batch_generation.py` | Пакетная обработка |

### bot/states.py
Определение всех FSM состояний через `StatesGroup`.

---

## 🎨 Как изменить UI

### 1. Изменить главное меню
Отредактируйте `get_main_menu_keyboard()` в `bot/keyboards.py`:

```python
def get_main_menu_keyboard(user_credits: int = 0):
    builder = InlineKeyboardBuilder()
    
    # Добавьте/измените кнопки
    builder.button(text="🆕 НОВАЯ ФУНКЦИЯ", callback_data="new_feature")
    
    # Настройте раскладку
    builder.adjust(2, 2, 1, 2, 1)
    return builder.as_markup()
```

### 2. Добавить новый раздел в настройки
1. Добавьте кнопку в `get_settings_keyboard()`
2. Добавьте обработчик в `common.py`:

```python
@router.callback_query(F.data == "new_setting")
async def handle_new_setting(callback: types.CallbackQuery, state: FSMContext):
    # Ваша логика
    await callback.answer()
```

### 3. Изменить категорию пресетов
Отредактируйте `data/presets.json`:

```json
{
  "categories": {
    "my_category": {
      "name": "📂 Моя категория",
      "description": "Описание",
      "presets": [
        {
          "id": "my_preset",
          "name": "✨ Мой пресет",
          "cost": 5
        }
      ]
    }
  }
}
```

### 4. Добавить новое FSM состояние
1. Добавьте в `bot/states.py`:

```python
class MyStates(StatesGroup):
    new_state = State()
```

2. Добавьте обработчик:

```python
@router.callback_query(F.data == "start_action", StateFilter(None))
async def start_action(callback: CallbackQuery, state: FSMContext):
    await state.set_state(MyStates.new_state)
    # Покажите клавиатуру ожидания ввода
```

---

## 🔍 Поиск проблем

### Кнопка не работает
1. Проверьте `callback_data` в keyboards.py
2. Проверьте есть ли обработчик в handlers/{module}.py
3. Убедитесь что роутер зарегистрирован в `handlers/__init__.py`

### Состояние не сбрасывается
Добавьте `await state.clear()` в обработчик кнопки "Назад"

### Сообщение не редактируется
Используйте `callback.message.answer()` вместо `edit_text()` если сообщение нельзя редактировать

---

## 📊 Диаграмма роутеров

```
dp.include_router() порядок (приоритет):
│
1. generation_router     # FSM состояния - самые специфичные
2. admin_router           # Админ команды
3. payments_router        # Платежи
4. batch_generation_router # Пакетная генерация
5. common_router          # Общие команды - самые общие
```

**Важно:** Порядок важен! Сообщение передаётся всем роутерам, но обрабатывается тем, у кого более специфичный фильтр.
