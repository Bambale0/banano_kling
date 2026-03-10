# UX Дизайн и Логика Интерфейса Bot API

Документ описывает все экраны, меню, callback-и и потоки пользователя в боте Banana Kling.

---

## Содержание

1. [Главное меню](#1-главное-меню)
2. [Меню создания видео](#2-меню-создания-видео)
3. [Меню создания фото](#3-меню-создания-фото)
4. [Motion Control](#4-motion-control)
5. [Пополнение баланса](#5-пополнение-баланса)
6. [Техническая поддержка](#6-техническая-поддержка)
7. [Помощь бота](#7-помощь-бота)
8. [ИИ-ассистент](#8-ии-ассистент)
9. [Настройки](#9-настройки)
10. [История и баланс](#10-история-и-баланс)
11. [Callback-и состояний](#11-callback-и-состояний)
12. [FSM States](#12-fsm-states)
13. [Таблица всех callback-ов](#13-таблица-всех-callback-ов)

---

## 1. Главное меню

**Триггер:** Команда `/start` или нажатие `back_main`

### Визуальная структура:

```
┌─────────────────────────────────────┐
│  🍌 Banana Kling                     │
│                                     │
│  Хватит просто смотреть —           │
│  создавай с AI! 🔥                  │
│                                     │
│  ✅ Генерация артов...               │
│  ✅ Фото-магия...                   │
│  ✅ Видео-продакшн...              │
│  ✅ FX-эффекты...                  │
│                                     │
│  🍌 Ваш баланс: X бананов          │
│                                     │
│  [🎬 Создать видео] [🎬 Motion]    │
│  [🖼 Создать фото]   [💰 Пополнить]│
│  [🆘 Тех. поддержка] [❓ Помощь]   │
└─────────────────────────────────────┘
```

### Кнопки главного меню:

| Кнопка | Callback | Описание |
|--------|----------|----------|
| 🎬 Создать видео | `create_video_new` | Переход в меню создания видео |
| 🎬 Motion Control | `menu_motion_control` | Переход в меню Motion Control |
| 🖼 Создать фото | `create_image_refs_new` | Переход в меню создания фото |
| 💰 Пополнить | `menu_topup` | Переход в меню пополнения |
| 🆘 Тех. поддержка | `menu_support` | Переход в поддержку |
| ❓ Помощь бота | `menu_help` | Показать справку |

### Расположение кнопок:
- `adjust(2, 2, 2)` — три ряда по 2 кнопки

---

## 2. Меню создания видео

**Триггер:** `create_video_new`

### Визуальная структура:

```
┌─────────────────────────────────────┐
│  🎬 Создание видео                   │
│                                     │
│  📎 Референсов: 2                   │
│                                     │
│  ⚙️ Текущие настройки:              │
│     📝 Тип: Текст → Видео          │
│     🤖 Модель: v26_pro             │
│     ⏱ Длительность: 5 сек         │
│     📐 Формат: 16:9                │
│                                     │
│  [📝 Текст → Видео] [🖼 Фото+текст]│
│                                     │
│  [⚡ Kling 2.6 • 8🍌]              │
│  [⚡ Kling 3 Std • 6🍌]            │
│  [💎 Kling 3 Pro • 8🍌]           │
│  [🔄 Kling 3 Omni • 8🍌]          │
│  [🎬 Kling 2.6 Motion • 10🍌]     │
│                                     │
│  [1:1] [16:9] [9:16] [4:3] [3:2] │
│                                     │
│  [5 сек] [10 сек] [15 сек]         │
│                                     │
│  [🏠 Главное меню]                  │
└─────────────────────────────────────┘
```

### Секции меню:

#### 2.1 Тип генерации (2 кнопки в ряд)

| Кнопка | Callback | Описание |
|--------|----------|----------|
| 📝 Текст → Видео | `v_type_text` | Генерация видео из текста |
| 🖼 Фото + Текст → Видео | `v_type_imgtxt` | Генерация из фото + текста |

#### 2.2 Выбор модели видео (5 кнопок, каждая на отдельной строке)

| Кнопка | Callback | Цена |
|--------|----------|------|
| ⚡ Kling 2.6 • 8🍌 | `v_model_v26_pro` | 8-14🍌 (зависит от длительности) |
| ⚡ Kling 3 Std • 6🍌 | `v_model_v3_std` | 6-10🍌 |
| 💎 Kling 3 Pro • 8🍌 | `v_model_v3_pro` | 8-16🍌 |
| 🔄 Kling 3 Omni • 8🍌 | `v_model_omni` | 8-16🍌 |
| 🎬 Kling 2.6 Motion • 10🍌 | `v_model_v26_motion_pro` | 10-18🍌 |

#### 2.3 Формат/Размер (5 кнопок в ряд)

| Кнопка | Callback |
|--------|----------|
| 1:1 | `ratio_1_1` |
| 16:9 | `ratio_16_9` |
| 9:16 | `ratio_9_16` |
| 4:3 | `ratio_4_3` |
| 3:2 | `ratio_3_2` |

#### 2.4 Длительность (3 кнопки в ряд)

| Кнопка | Callback | Описание |
|--------|----------|----------|
| 5 сек | `video_dur_5` | 5 секунд |
| 10 сек | `video_dur_10` | 10 секунд |
| 15 сек | `video_dur_15` | 15 секунд (не доступно для Kling 2.6) |

#### 2.5 Нижние кнопки

| Кнопка | Callback |
|--------|----------|
| 🏠 Главное меню | `back_main` |

### Поток пользователя:

```
create_video_new
    │
    ├─► Выбор типа (v_type_text / v_type_imgtxt)
    │       │
    │       └─► Обновление клавиатуры с отметкой выбранного типа
    │
    ├─► Выбор модели (v_model_*)
    │       │
    │       └─► Обновление цены на клавиатуре
    │
    ├─► Выбор формата (ratio_*)
    │       │
    │       └─► Обновление клавиатуры с отметкой
    │
    ├─► Выбор длительности (video_dur_*)
    │       │
    │       └─► Обновление цены (зависит от длительности)
    │
    └─► Ввод промпта (состояние waiting_for_video_prompt)
            │
            ├─► Если v_type = imgtxt → загрузка фото
            │       (состояние waiting_for_image)
            │
            └─► Запуск генерации
```

### Параметры состояния (FSM):

```python
{
    "generation_type": "video",
    "v_type": "text",           # или "imgtxt"
    "v_model": "v26_pro",      # модель видео
    "v_duration": 5,           # длительность в секундах
    "v_ratio": "16:9",         # формат
    "reference_images": [],     # массив URL референсов
    "v_image_url": None,       # стартовое изображение для imgtxt
    "user_prompt": ""          # текстовый промпт
}
```

---

## 3. Меню создания фото

**Триггер:** `create_image_refs_new`

### Поток:

```
create_image_refs_new
    │
    ├─► Шаг 1: Загрузка референсов (опционально)
    │       │
    │       ├─► Загрузка фото (до 14 штук)
    │       │       (состояние uploading_reference_images)
    │       │
    │       ├─► img_ref_skip_new → Пропустить
    │       │
    │       └─► img_ref_continue_new → Продолжить
    │
    └─► Шаг 2: Выбор модели и формата
            │
            ├─► Выбор модели (model_*)
            │
            ├─► Выбор формата (img_ratio_*)
            │
            └─► Ввод промпта
                    │
                    └─► Запуск генерации
```

### Секция выбора модели (5 кнопок, каждая на отдельной строке):

| Кнопка | Callback | Цена |
|--------|----------|------|
| ✨ FLUX.2 Pro • 3🍌 | `model_flux_pro` | 3🍌 |
| 🍌 Nano Banana • 3🍌 | `model_nanobanana` | 3🍌 |
| 💎 Banana Pro • 5🍌 | `model_banana_pro` | 5🍌 |
| 🎨 Seedream • 3🍌 | `model_seedream` | 3🍌 |
| 🚀 Z5 Lora • 3🍌 | `model_z_image_turbo_lora` | 3🍌 |

### Секция выбора формата (5 кнопок в ряд):

| Кнопка | Callback |
|--------|----------|
| 1:1 | `img_ratio_1_1` |
| 16:9 | `img_ratio_16_9` |
| 9:16 | `img_ratio_9_16` |
| 4:3 | `img_ratio_4_3` |
| 3:2 | `img_ratio_3_2` |

### Callback-и для работы с референсами:

| Callback | Описание |
|----------|----------|
| `img_ref_upload_new` | Начать загрузку референсов |
| `img_ref_skip_new` | Пропустить загрузку референсов |
| `img_ref_continue_new` | Продолжить после загрузки |
| `ref_reload_new` | Перезагрузить референсы |
| `ref_confirm_new` | Подтвердить референсы |

### Параметры состояния:

```python
{
    "generation_type": "image",
    "img_service": "flux_pro",      # сервис генерации
    "img_ratio": "1:1",            # формат изображения
    "reference_images": [],         # массив байтов референсов
    "preset_id": "new",            # режим "new" для нового UX
    "user_prompt": ""              # текстовый промпт
}
```

---

## 4. Motion Control

**Триггер:** `menu_motion_control`

### Меню выбора качества:

```
┌─────────────────────────────────────┐
│  🎬 Motion Control                   │
│                                     │
│  Перенос движения с референсного      │
│  видео на твоё фото!               │
│                                     │
│  Как это работает:                  │
│  1. Загрузи фото персонажа          │
│  2. Загрузи видео с движением      │
│  3. Получи анимированное фото!     │
│                                     │
│  💰 Баланс: X🍌                    │
│                                     │
│  Выбери качество:                   │
│                                     │
│  [⚡ Motion Control Standard • 8🍌] │
│  [💎 Motion Control Pro • 10🍌]    │
│  [🔙 Назад]                        │
└─────────────────────────────────────┘
```

### Кнопки:

| Кнопка | Callback | Цена |
|--------|----------|------|
| ⚡ Motion Control Standard • 8🍌 | `motion_control_std` | 8🍌 |
| 💎 Motion Control Pro • 10🍌 | `motion_control_pro` | 10🍌 |
| 🔙 Назад | `back_main` | — |

### Поток:

```
menu_motion_control
    │
    ├─► motion_control_std
    │       │
    │       └─► waiting_for_image → Загрузка фото персонажа
    │               │
    │               └─► waiting_for_video → Загрузка видео-референса
    │                       │
    │                       └─► waiting_for_input → Ввод промпта
    │                               │
    │                               └─► Запуск генерации
    │
    └─► motion_control_pro (аналогично, но другая модель)
```

### Параметры состояния:

```python
{
    "generation_type": "motion_control",
    "video_model": "v26_motion_std" | "v26_motion_pro",
    "cost": 8 | 10,
    "uploaded_image": bytes,           # фото персонажа
    "uploaded_image_url": str,        # URL фото
    "motion_video_url": str,          # URL видео-референса
    "user_prompt": str                # описание движения
}
```

---

## 5. Пополнение баланса

**Триггер:** `menu_topup`

### Меню выбора пакета:

```
┌─────────────────────────────────────┐
│  🍌 Пополнение баланса               │
│                                     │
│  Выберите пакет бананов:            │
│  (Чем больше — тем выгоднее)         │
│                                     │
│  [Mini: 15🍌 за 150₽]              │
│  [Standard: 30🍌 за 250₽]           │
│  [Optimal: 50🍌 за 400₽ 🔥]         │
│  [Pro: 100🍌 за 700₽]              │
└─────────────────────────────────────┘
```

### Кнопки пакетов:

| Callback | Пакет | Бананы | Цена (₽) |
|----------|-------|--------|-----------|
| `buy_mini` | Mini | 15 | 150 |
| `buy_standard` | Standard | 30 | 250 |
| `buy_optimal` | Optimal | 50 | 400 (🔥 популярный) |
| `buy_pro` | Pro | 100 | 700 |

### Процесс оплаты:

```
menu_topup
    │
    └─► buy_{package_id}
            │
            ├─► Создание order_id: {user_id}_{timestamp}_{package_id}
            │
            ├─► Инициация платежа в Т-Банке
            │       amount = price_rub * 100 (в копейках)
            │
            └─► Показ подтверждения:
                    │
                    ├─► Кнопка оплаты (URL из Т-Банка)
                    │       callback: игнорируется
                    │
                    └─► Кнопка "Назад" → menu_topup
```

### Callback подтверждения оплаты:

| Callback | Описание |
|----------|----------|
| Оплата через Т-Банк | Редирект на `success_{order_id}` |
| `check_payment_{order_id}` | Ручная проверка статуса |
| `cancel_payment` | Отмена платежа |

### Deep linking после оплаты:

```
T-Bank → https://t.me/{bot}?start=success_{order_id}
    │
    └─► Обработка в cmd_start()
            │
            ├─► Проверка транзакции в БД
            │
            ├─► Если уже completed → показ баланса
            │
            ├─► Если pending → проверка статуса в Т-Банке
            │       │
            │       └─► CONFIRMED → начисление бананов
            │
            └─► Показ результата
```

---

## 6. Техническая поддержка

**Триггер:** `menu_support`

### Меню:

```
┌─────────────────────────────────────┐
│  🆘 Техническая поддержка            │
│                                     │
│  💬 Напиши свой вопрос ИИ-ассистенту │
│  Он поможет с:                      │
│  • Генерацией изображений и видео    │
│  • Настройками и моделями            │
│  • Оплатой и балансом               │
│  • Любыми другими вопросами         │
│                                     │
│  📱 Или свяжись с нами: @s_k7222   │
│                                     │
│  [💬 ИИ-ассистент]                  │
│  [🔙 Главное меню]                  │
└─────────────────────────────────────┘
```

### Кнопки:

| Кнопка | Callback |
|--------|----------|
| 💬 ИИ-ассистент | `menu_ai_assistant` |
| 🔙 Главное меню | `back_main` |

---

## 7. Помощь бота

**Триггер:** `menu_help`

### Содержимое:

- Общая справка по использованию
- Как составлять промпты
- Описание моделей
- Стоимость операций
- Контакты поддержки

### Кнопки:

| Кнопка | Callback |
|--------|----------|
| 🔙 Главное меню | `back_main` |

---

## 8. ИИ-ассистент

**Триггер:** `menu_ai_assistant` или `menu_ai_settings`

### Вход в режим:

```
menu_ai_assistant / menu_ai_settings
    │
    └─► Установка состояния AIAssistantStates.waiting_for_message
            │
            └─► Показ приветственного сообщения от ИИ
```

### Клавиатура:

```
┌─────────────────────────────────────┐
│  [🔙 В главное меню]                │
└─────────────────────────────────────┘
```

### Поток общения:

```
waiting_for_message (FSM state)
    │
    ├─► Пользователь отправляет сообщение
    │       │
    │       ├─► Отправка "typing" action
    │       │
    │       ├─► Формирование контекста:
    │       │       - user_credits
    │       │       - preferred_model
    │       │       - preferred_video_model
    │       │       - image_service
    │       │       - menu_location
    │       │
    │       └─► Запрос к AI-сервису
    │               │
    │               └─► Ответ пользователю
    │
    └─► Кнопка "В главное меню" → back_main
```

### Контекст для ИИ:

```python
{
    "user_credits": int,
    "preferred_model": str,           # "flash" | "pro"
    "preferred_video_model": str,      # "v3_std" | "v3_pro" | и т.д.
    "image_service": str,              # "nanobanana" | "novita" | и т.д.
    "menu_location": str               # "главное меню" | "настройки"
}
```

---

## 9. Настройки

**Триггер:** `menu_settings`

### Меню настроек:

```
┌─────────────────────────────────────┐
│  ⚙️ Настройки                        │
│                                     │
│  🖼 Изображения:                    │
│  • FLUX.2 Pro / Nano Banana         │
│  • Все модели: 3🍌                  │
│                                     │
│  🎬 Текст→Видео:                    │
│  • Kling 2.6 (8🍌) / Std (6🍌)     │
│  • Pro (8🍌) / Omni / V2V          │
│                                     │
│  🖼→🎬 Фото→Видео:                  │
│  • Std (6🍌) / Pro (8🍌) / Omni    │
│                                     │
│  [Кнопки выбора моделей...]         │
│  [🔙 Назад в главное меню]         │
└─────────────────────────────────────┘
```

### Callback-и настроек:

| Callback | Описание |
|----------|----------|
| `settings_model_flash` | Модель изображений: Flash |
| `settings_model_pro` | Модель изображений: Pro |
| `settings_video_v3_std` | Модель видео: Kling 3 Std |
| `settings_video_v3_pro` | Модель видео: Kling 3 Pro |
| `settings_video_v3_omni_std` | Модель видео: Kling 3 Omni Std |
| `settings_video_v3_omni_pro` | Модель видео: Kling 3 Omni Pro |
| `settings_i2v_v3_std` | Модель фото→видео: Std |
| `settings_i2v_v3_pro` | Модель фото→видео: Pro |
| `settings_service_nanobanana` | Сервис: Nano Banana |
| `settings_service_novita` | Сервис: Novita (FLUX.2) |
| `settings_service_seedream` | Сервис: Seedream |

---

## 10. История и баланс

### Меню баланса

**Триггер:** `menu_balance`

```
┌─────────────────────────────────────┐
│  💎 Ваш баланс                      │
│                                     │
│  🍌 Доступно бананов: X             │
│  📊 Всего генераций: X              │
│  💸 Потрачено бананов: X            │
│  📅 Дата регистрации: XX.XX.XXXX    │
│                                     │
│  [💰 Пополнить] [📋 История]        │
│  [🔙 Главное меню]                  │
└─────────────────────────────────────┘
```

### Кнопки:

| Кнопка | Callback |
|--------|----------|
| 💰 Пополнить | `menu_topup` |
| 📋 История | `menu_history` |
| 🔙 Главное меню | `back_main` |

### Меню истории

**Триггер:** `menu_history`

```
┌─────────────────────────────────────┐
│  📋 История                          │
│                                     │
│  📊 Всего генераций: X              │
│  💸 Потрачено бананов: X            │
│  💎 Текущий баланс: X🍌             │
│  📅 Дата регистрации: XX.XX.XXXX    │
│                                     │
│  (Детальная история в разработке)    │
│                                     │
│  [🔙 Главное меню]                  │
└─────────────────────────────────────┘
```

---

## 11. Callback-и состояний

### Основные навигационные callback-и:

| Callback | Описание | Действие |
|----------|----------|----------|
| `back_main` | Назад в главное меню | Очистка FSM state, показ главного меню |
| `ignore` | Заглушка | Игнорирует нажатие (для неактивных кнопок) |

### Callback-и видео-опций:

| Callback | Параметры | Описание |
|----------|-----------|----------|
| `v_type_text` | — | Текст → Видео |
| `v_type_imgtxt` | — | Фото + Текст → Видео |
| `v_model_v26_pro` | — | Kling 2.6 Pro |
| `v_model_v3_std` | — | Kling 3 Std |
| `v_model_v3_pro` | — | Kling 3 Pro |
| `v_model_omni` | — | Kling 3 Omni |
| `v_model_v26_motion_pro` | — | Kling 2.6 Motion Pro |
| `ratio_{format}` | 1_1, 16_9, 9_16, 4_3, 3_2 | Формат видео |
| `video_dur_{seconds}` | 5, 10, 15 | Длительность видео |

### Callback-и изображений:

| Callback | Описание |
|----------|----------|
| `model_flux_pro` | FLUX.2 Pro |
| `model_nanobanana` | Nano Banana |
| `model_banana_pro` | Banana Pro |
| `model_seedream` | Seedream |
| `model_z_image_turbo_lora` | Z5 Lora |
| `img_ratio_{format}` | Формат изображения |

### Callback-и референсов:

| Callback | Описание |
|----------|----------|
| `img_ref_upload_new` | Загрузка референсов (новый UX) |
| `img_ref_skip_new` | Пропустить референсы |
| `img_ref_continue_new` | Продолжить после референсов |
| `ref_reload_new` | Перезагрузить референсы |
| `ref_confirm_new` | Подтвердить референсы |

### Callback-и Motion Control:

| Callback | Описание |
|----------|----------|
| `motion_control_std` | Motion Control Standard |
| `motion_control_pro` | Motion Control Pro |

### Callback-и оплаты:

| Callback | Описание |
|----------|----------|
| `menu_topup` | Меню пополнения |
| `buy_{package}` | Купить пакет (mini, standard, optimal, pro) |
| `check_payment_{order_id}` | Проверить статус платежа |
| `cancel_payment` | Отмена платежа |

### Callback-и поддержки:

| Callback | Описание |
|----------|----------|
| `menu_support` | Меню поддержки |
| `menu_ai_assistant` | ИИ-ассистент |
| `menu_ai_settings` | ИИ-ассистент из настроек |
| `menu_help` | Помощь |

### Callback-и настроек:

| Callback | Описание |
|----------|----------|
| `menu_settings` | Меню настроек |
| `settings_model_{type}` | Выбор модели изображений |
| `settings_video_{model}` | Выбор модели видео |
| `settings_i2v_{model}` | Выбор модели фото→видео |
| `settings_service_{service}` | Выбор сервиса |

### Callback-и категорий и пресетов:

| Callback | Описание |
|----------|----------|
| `cat_{category}` | Показать категорию |
| `preset_{id}` | Показать пресет |
| `back_cat_{category}` | Назад к категории |

---

## 12. FSM States

### GenerationStates

```python
class GenerationStates(StatesGroup):
    # Основные состояния
    waiting_for_input = State()           # Ожидание текстового ввода
    waiting_for_image = State()           # Ожидание загрузки фото
    waiting_for_video = State()           # Ожидание загрузки видео
    waiting_for_video_prompt = State()    # Ожидание промпта для видео
    confirming_generation = State()       # Подтверждение перед запуском
    
    # Референсы
    uploading_reference_images = State()   # Загрузка референсов (до 14)
    confirming_reference_images = State()  # Подтверждение референсов
    
    # Пакетная генерация
    waiting_for_batch_image = State()      # Ожидание фото для batch
    waiting_for_batch_prompt = State()     # Ожидание промпта для batch
    waiting_for_batch_aspect_ratio = State()  # Ожидание формата для batch
    selecting_batch_count = State()         # Выбор количества
    
    # Опции видео
    selecting_duration = State()            # Выбор длительности
    selecting_aspect_ratio = State()       # Выбор формата
    selecting_quality = State()             # Выбор качества
```

### PaymentStates

```python
class PaymentStates(StatesGroup):
    selecting_package = State()      # Выбор пакета
    confirming_payment = State()    # Подтверждение оплаты
    waiting_payment = State()       # Ожидание оплаты
```

### AdminStates

```python
class AdminStates(StatesGroup):
    waiting_broadcast_text = State()      # Ввод текста рассылки
    confirming_broadcast = State()        # Подтверждение рассылки
    waiting_user_id = State()             # Ввод ID пользователя
    waiting_credits_amount = State()      # Ввод количества кредитов
```

### AIAssistantStates

```python
class AIAssistantStates(StatesGroup):
    main_menu = State()              # Пользователь в главном меню
    settings = State()               # Пользователь в настройках
    waiting_for_message = State()    # Ожидание сообщения для ИИ
```

---

## 13. Таблица всех Callback-ов

### Навигация

| Callback | Функция | Описание |
|----------|---------|----------|
| `back_main` | `back_to_main()` | Возврат в главное меню |
| `ignore` | `handle_ignore_callback()` | Заглушка |

### Главное меню

| Callback | Функция | Описание |
|----------|---------|----------|
| `create_video_new` | `show_create_video_menu()` | Меню создания видео |
| `create_image_refs_new` | `show_create_image_menu()` | Меню создания фото |
| `menu_topup` | `show_topup_menu()` | Пополнение баланса |
| `menu_support` | `show_support()` | Тех. поддержка |
| `menu_help` | `show_help()` | Помощь |
| `menu_motion_control` | `show_motion_control_menu()` | Motion Control |
| `menu_balance` | `show_balance()` | Баланс |
| `menu_history` | `show_history()` | История |
| `menu_settings` | `show_settings()` | Настройки |
| `menu_ai_assistant` | `open_ai_assistant_main()` | ИИ-ассистент |

### Видео - тип генерации

| Callback | Функция | Описание |
|----------|---------|----------|
| `v_type_text` | `handle_v_type_text()` | Текст → Видео |
| `v_type_imgtxt` | `handle_v_type_imgtxt()` | Фото + Текст → Видео |

### Видео - модель

| Callback | Функция | Описание |
|----------|---------|----------|
| `v_model_v26_pro` | `handle_v_model_v26_pro()` | Kling 2.6 |
| `v_model_v3_std` | `handle_v_model_v3_std()` | Kling 3 Std |
| `v_model_v3_pro` | `handle_v_model_v3_pro()` | Kling 3 Pro |
| `v_model_omni` | `handle_v_model_omni()` | Kling 3 Omni |
| `v_model_v26_motion_pro` | `handle_v_model_v26_motion_pro()` | Kling 2.6 Motion |

### Видео - формат

| Callback | Функция | Описание |
|----------|---------|----------|
| `ratio_1_1` | `handle_video_ratio_1_1()` | Формат 1:1 |
| `ratio_16_9` | `handle_video_ratio_16_9()` | Формат 16:9 |
| `ratio_9_16` | `handle_video_ratio_9_16()` | Формат 9:16 |
| `ratio_4_3` | `handle_video_ratio_4_3()` | Формат 4:3 |
| `ratio_3_2` | `handle_video_ratio_3_2()` | Формат 3:2 |

### Видео - длительность

| Callback | Функция | Описание |
|----------|---------|----------|
| `video_dur_5` | `handle_video_dur_5()` | 5 секунд |
| `video_dur_10` | `handle_video_dur_10()` | 10 секунд |
| `video_dur_15` | `handle_video_dur_15()` | 15 секунд |

### Изображение - модель

| Callback | Функция | Описание |
|----------|---------|----------|
| `model_flux_pro` | `handle_model_flux_pro()` | FLUX.2 Pro |
| `model_nanobanana` | `handle_model_nanobanana()` | Nano Banana |
| `model_banana_pro` | `handle_model_banana_pro()` | Banana Pro |
| `model_seedream` | `handle_model_seedream()` | Seedream |
| `model_z_image_turbo_lora` | `handle_model_z_image_turbo_lora()` | Z5 Lora |

### Изображение - формат

| Callback | Функция | Описание |
|----------|---------|----------|
| `img_ratio_1_1` | `handle_img_ratio_1_1()` | Формат 1:1 |
| `img_ratio_16_9` | `handle_img_ratio_16_9()` | Формат 16:9 |
| `img_ratio_9_16` | `handle_img_ratio_9_16()` | Формат 9:16 |
| `img_ratio_4_3` | `handle_img_ratio_4_3()` | Формат 4:3 |
| `img_ratio_3_2` | `handle_img_ratio_3_2()` | Формат 3:2 |

### Референсы

| Callback | Функция | Описание |
|----------|---------|----------|
| `img_ref_upload_new` | `handle_img_ref_upload_new()` | Загрузка референсов |
| `img_ref_skip_new` | `handle_img_ref_skip_new()` | Пропустить |
| `img_ref_continue_new` | `handle_img_ref_continue_new()` | Продолжить |
| `ref_reload_new` | `handle_ref_reload_new()` | Перезагрузить |
| `ref_confirm_new` | `handle_ref_confirm_new()` | Подтвердить |

### Motion Control

| Callback | Функция | Описание |
|----------|---------|----------|
| `motion_control_std` | `start_motion_control_std()` | Standard |
| `motion_control_pro` | `start_motion_control_pro()` | Pro |

### Оплата

| Callback | Функция | Описание |
|----------|---------|----------|
| `buy_mini` | `initiate_payment()` | Mini пакет |
| `buy_standard` | `initiate_payment()` | Standard пакет |
| `buy_optimal` | `initiate_payment()` | Optimal пакет |
| `buy_pro` | `initiate_payment()` | Pro пакет |
| `check_payment_{order_id}` | `check_payment_status()` | Проверить платёж |
| `cancel_payment` | `cancel_payment()` | Отмена |

### Настройки

| Callback | Функция | Описание |
|----------|---------|----------|
| `settings_model_flash` | `handle_settings_model()` | Модель Flash |
| `settings_model_pro` | `handle_settings_model()` | Модель Pro |
| `settings_video_v3_std` | `handle_settings_video_model()` | Видео Std |
| `settings_video_v3_pro` | `handle_settings_video_model()` | Видео Pro |
| `settings_video_v3_omni_std` | `handle_settings_video_model()` | Видео Omni Std |
| `settings_video_v3_omni_pro` | `handle_settings_video_model()` | Видео Omni Pro |
| `settings_i2v_v3_std` | `handle_settings_i2v_model()` | I2V Std |
| `settings_i2v_v3_pro` | `handle_settings_i2v_model()` | I2V Pro |
| `settings_service_nanobanana` | `handle_settings_service()` | Сервис Nano |
| `settings_service_novita` | `handle_settings_service()` | Сервис Novita |
| `settings_service_seedream` | `handle_settings_service()` | Сервис Seedream |

### Категории и пресеты

| Callback | Функция | Описание |
|----------|---------|----------|
| `cat_{category}` | `show_category()` | Показать категорию |
| `preset_{id}` | `show_preset_details()` | Показать пресет |
| `back_cat_{category}` | `back_to_category()` | Назад к категории |
| `custom_{preset_id}` | `request_custom_input()` | Свой ввод |
| `default_{preset_id}` | `use_default_values()` | Значения по умолчанию |
| `duration_{preset_id}_{dur}` | `handle_duration_selection()` | Длительность |
| `ratio_{preset_id}_{ratio}` | `handle_aspect_ratio_selection()` | Формат |
| `quality_{preset_id}_{quality}` | `handle_quality_selection()` | Качество |
| `model_{preset_id}_{model}` | `handle_model_selection()` | Модель |
| `resolution_{preset_id}_{res}` | `handle_resolution_selection()` | Разрешение |
| `grounding_{preset_id}` | `handle_search_grounding()` | Поиск |

### Референсы (старый UX)

| Callback | Функция | Описание |
|----------|---------|----------|
| `ref_upload_{preset_id}` | `handle_reference_images()` | Загрузка |
| `ref_clear_{preset_id}` | `handle_reference_images()` | Очистить |
| `ref_confirm_{preset_id}` | `handle_reference_images()` | Подтвердить |
| `ref_reload_{preset_id}` | `handle_reference_images()` | Перезагрузить |
| `ref_accept_{preset_id}` | `handle_reference_images()` | Принять |

### Запуск генерации

| Callback | Функция | Описание |
|----------|---------|----------|
| `run_{preset_id}` | `execute_generation()` | Запустить пресет |
| `run_no_preset` | `run_no_preset_editing()` | Без пресета |
| `run_no_preset_image` | `handle_run_no_preset_image()` | Запустить фото |
| `run_no_preset_video` | `run_no_preset_video()` | Запустить видео |
| `run_no_preset_edit_image` | `handle_run_no_preset_edit_image()` | Редактировать фото |
| `run_video_edit` | `run_video_edit_handler()` | Видео-эффекты |
| `run_video_edit_image` | `run_video_edit_image_handler()` | Фото → видео |

### Видео-опции без пресета

| Callback | Функция | Описание |
|----------|---------|----------|
| `no_preset_duration_{dur}` | `set_no_preset_duration()` | Длительность |
| `no_preset_ratio_{ratio}` | `set_no_preset_ratio()` | Формат |
| `no_preset_audio_{on/off}` | `set_no_preset_audio()` | Звук |
| `img_ratio_no_preset_{ratio}` | `handle_no_preset_ratio()` | Формат фото |
| `img_ratio_no_preset_edit_{ratio}` | `handle_no_preset_edit_ratio()` | Формат редактирования |

### Многоходовое редактирование

| Callback | Функция | Описание |
|----------|---------|----------|
| `multiturn_{preset_id}` | `handle_multiturn()` | Продолжить редактирование |

### Админ

| Callback | Функция | Описание |
|----------|---------|----------|
| `admin_reload` | — | Перезагрузить пресеты |
| `admin_stats` | — | Статистика |
| `admin_users` | — | Пользователи |
| `admin_broadcast` | — | Рассылка |

---

## Диаграмма потоков

### Главный поток

```
┌─────────────┐
│    START    │
└──────┬──────┘
       │
       ▼
┌─────────────────────────────────────────┐
│            ГЛАВНОЕ МЕНЮ                  │
│  (cmd_start / back_main)                │
└──────┬──────────────────────────────────┘
       │
       ├─────────────────────────────────────┐
       │                                      │
       ▼                                      ▼
┌─────────────┐                      ┌──────────────┐
│ 🎬 Видео    │                      │ 🖼 Фото      │
│ create_     │                      │ create_      │
│ video_new   │                      │ image_       │
└──────┬──────┘                      │ refs_new     │
       │                             └──────┬───────┘
       │                                    │
       ▼                                    ▼
┌─────────────────────────────────────────────────────┐
│            ПАРАМЕТРЫ + ПРОМПТ                        │
│  • Тип (text/imgtxt)                                │
│  • Модель (v26/v3/omni)                             │
│  • Формат (16:9/9:16/...)                          │
│  • Длительность (5/10/15)                          │
│  • Промпт (текст)                                  │
│  • Изображение (для imgtxt)                        │
└──────┬─────────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────┐
│      ПРОВЕРКА БАЛАНС               │
│      (check_can_afford)             │
└──────┬──────────────────────────────┘
       │
       ├──────────────────────────────┐
       │                              │
       ▼                              ▼
┌─────────────┐              ┌───────────────┐
│  ДОСТАТОЧНО │              │  НЕДОСТАТОЧНО│
│             │              │               │
│  deduct_    │              │  menu_topup   │
│  credits()  │              │  (пополнить)  │
│             │              └───────────────┘
└──────┬──────┘
       │
       ▼
┌─────────────────────────────────────┐
│        ЗАПУСК ГЕНЕРАЦИИ            │
│                                     │
│  • Синхронная (Gemini)             │
│    → ждём результат                 │
│    → отправляем фото                │
│                                     │
│  • Асинхронная (Kling/Novita)      │
│    → создаём task_id                │
│    → опрашиваем статус              │
│    → отправляем результат           │
└─────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────┐
│           ГОТОВО                    │
│                                     │
│  [🏠 Главное меню] (back_main)      │
└─────────────────────────────────────┘
```

---

## Ценообразование

### Изображения

| Модель | Цена |
|--------|------|
| FLUX.2 Pro | 3🍌 |
| Nano Banana | 3🍌 |
| Banana Pro | 5🍌 |
| Seedream | 3🍌 |
| Z5 Lora | 3🍌 |

### Видео

| Модель | 5 сек | 10 сек | 15 сек |
|--------|-------|--------|--------|
| Kling 2.6 Pro | 8🍌 | 14🍌 | — |
| Kling 3 Std | 6🍌 | 8🍌 | 10🍌 |
| Kling 3 Pro | 8🍌 | 14🍌 | 16🍌 |
| Kling 3 Omni Std | 8🍌 | 14🍌 | 16🍌 |
| Kling 3 Omni Pro | 8🍌 | 14🍌 | 16🍌 |
| Kling 2.6 Motion Pro | 10🍌 | 18🍌 | — |

### Пакеты

| Пакет | Бананы | Цена (₽) | Цена за банан |
|-------|--------|----------|--------------|
| Mini | 15 | 150 | 10₽ |
| Standard | 30 | 250 | 8.3₽ |
| Optimal | 50 | 400 | 8₽ |
| Pro | 100 | 700 | 7₽ |

---

*Документ создан на основе исходного кода бота. Актуальность: 2026-03-10*
