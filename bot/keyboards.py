import json
import os

try:
    from vkbottle import Keyboard, Text
except Exception:
    Keyboard = None
    Text = None

try:
    from vkbottle.keyboard import InlineKeyboardBuilder
except Exception:
    # Compatibility shim for environments where vkbottle exposes different keyboard API
    class InlineKeyboardMarkup:
        def __init__(self, inline_keyboard=None):
            self.inline_keyboard = inline_keyboard or []

        def build(self):
            return self

        def as_markup(self):
            return self

        def get_json(self):
            import json

            buttons = []
            for row in self.inline_keyboard:
                vk_row = []
                for btn in row:
                    action = {"type": "text", "label": btn["text"]}
                    if "callback_data" in btn:
                        payload_dict = {"button": btn["callback_data"]}
                        payload_json = json.dumps(payload_dict, separators=(",", ":"))
                        action["payload"] = payload_json
                    if "url" in btn:
                        action["type"] = "open_link"
                        action["link_url"] = btn["url"]
                    vk_row.append({"action": action})
                buttons.append(vk_row)
            return json.dumps(
                {"one_time": False, "inline": True, "buttons": buttons},
                ensure_ascii=False,
            )

    class InlineKeyboardBuilder:
        def __init__(self):
            self._rows = []
            self._current_row = []

        def button(self, text: str = "", callback_data: str = None, url: str = None):
            btn = {"text": text}
            if callback_data is not None:
                btn["callback_data"] = callback_data
            if url is not None:
                btn["url"] = url
            self._current_row.append(btn)
            return self

        def row(self, *items):
            # Accept a sequence of button dicts (from another markup)
            if items:
                self._rows.append(list(items))
            else:
                if self._current_row:
                    self._rows.append(self._current_row)
                    self._current_row = []

        def adjust(self, *widths):
            # Распределяем текущие кнопки по строкам согласно widths
            if not self._current_row:
                return

            buttons = self._current_row
            self._current_row = []
            button_idx = 0

            for width in widths:
                if button_idx >= len(buttons):
                    break
                row = []
                for _ in range(width):
                    if button_idx < len(buttons):
                        row.append(buttons[button_idx])
                        button_idx += 1
                if row:
                    self._rows.append(row)

            # Добавляем оставшиеся кнопки в отдельные строки
            while button_idx < len(buttons):
                self._rows.append([buttons[button_idx]])
                button_idx += 1

        def as_markup(self):
            markup = InlineKeyboardMarkup(inline_keyboard=self._rows)
            return markup.get_json()

        def build(self):
            markup = InlineKeyboardMarkup(inline_keyboard=self._rows)
            return markup.get_json()

        # for compatibility used elsewhere
        def __repr__(self):
            return f"<InlineKeyboardBuilder rows={len(self._rows)}>"

    class Text:
        def __init__(self, label: str, payload=None):
            self.label = label
            self.payload = payload or {}

    class Keyboard:
        def __init__(self, one_time=False, inline=False):
            self.one_time = one_time
            self.inline = inline
            self.rows = [[]]

        def add(self, *text_objs):
            for text_obj in text_objs:
                payload = json.dumps(
                    text_obj.payload, separators=(",", ":"), ensure_ascii=False
                )
                self.rows[-1].append(
                    {
                        "action": {
                            "type": "text",
                            "label": text_obj.label,
                            "payload": payload,
                        }
                    }
                )
            return self

        def row(self):
            self.rows.append([])
            return self

        def get_json(self):
            rows = [row for row in self.rows if row]
            return json.dumps(
                {"one_time": self.one_time, "inline": self.inline, "buttons": rows},
                ensure_ascii=False,
            )


# Загрузка цен из price.json
def load_prices():
    """Загружает цены из price.json"""
    price_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "data", "price.json"
    )
    try:
        with open(price_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        # Значения по умолчанию если файл не найден
        return {
            "costs_reference": {
                "image_models": {
                    "flux_pro": 3,
                    "nanobanana": 3,
                    "banana_pro": 5,
                    "seedream": 3,
                },
                "video_models": {
                    "v26_pro": {"base": 8, "duration_costs": {"5": 8, "10": 14}},
                    "v3_std": {
                        "base": 6,
                        "duration_costs": {"5": 6, "10": 8, "15": 10},
                    },
                    "v3_pro": {
                        "base": 8,
                        "duration_costs": {"5": 8, "10": 14, "15": 16},
                    },
                    "v3_omni_std": {
                        "base": 8,
                        "duration_costs": {"5": 8, "10": 14, "15": 16},
                    },
                    "v3_omni_pro": {
                        "base": 8,
                        "duration_costs": {"5": 8, "10": 14, "15": 16},
                    },
                },
            },
            "packages": [
                {"id": "mini", "credits": 15, "price_rub": 150},
                {"id": "standard", "credits": 30, "price_rub": 250},
                {"id": "optimal", "credits": 50, "price_rub": 400, "popular": True},
                {"id": "pro", "credits": 100, "price_rub": 700},
            ],
        }


PRICES = load_prices()

# Словари для удобного доступа
IMAGE_COSTS = PRICES.get("costs_reference", {}).get(
    "image_models",
    {
        "novita": 3,
        "nanobanana": 3,
        "banana_pro": 5,
        "seedream": 3,
        "seedream45": 3,
        "z_image_turbo_lora": 3,
        "gemini_2_5_flash": 3,
        "gemini_3_pro": 5,
    },
)

VIDEO_COSTS = PRICES.get("costs_reference", {}).get(
    "video_models",
    {
        "v3_std": {"base": 6, "duration_costs": {"5": 6, "10": 8, "15": 10}},
        "v3_pro": {"base": 8, "duration_costs": {"5": 8, "10": 14, "15": 16}},
        "v3_omni_std": {"base": 8, "duration_costs": {"5": 8, "10": 14, "15": 16}},
        "v3_omni_pro": {"base": 8, "duration_costs": {"5": 8, "10": 14, "15": 16}},
        "v26_pro": {"base": 8, "duration_costs": {"5": 8, "10": 14}},
        "v26_motion_pro": {"base": 10, "duration_costs": {"5": 10, "10": 18}},
        "v26_motion_std": {"base": 8, "duration_costs": {"5": 8, "10": 14}},
        "z_image_turbo_lora": {"base": 3, "duration_costs": {"5": 3, "10": 6, "15": 9}},
    },
)

PACKAGES = PRICES.get("packages", [])


# =============================================================================
# ГЛАВНОЕ МЕНЮ - согласно ux.md
# =============================================================================


def make_payload(button_name):
    import json

    data = {"button": button_name}
    return json.dumps(data, separators=(",", ":"), ensure_ascii=False)


def get_main_menu_keyboard(user_credits: int = 0):
    """Главное меню бота - reply keyboard версия для стабильности"""
    buttons = [
        [
            {
                "action": {
                    "type": "text",
                    "label": "🎬 Создать видео",
                    "payload": make_payload("create_video_new"),
                }
            },
            {
                "action": {
                    "type": "text",
                    "label": "🖼 Создать фото",
                    "payload": make_payload("create_image_refs_new"),
                }
            },
        ],
        [
            {
                "action": {
                    "type": "text",
                    "label": "🎬 Motion Control",
                    "payload": make_payload("menu_motion_control"),
                }
            },
            {
                "action": {
                    "type": "text",
                    "label": "📸 Фото=Промпт",
                    "payload": make_payload("photo_to_prompt"),
                }
            },
        ],
        [
            {
                "action": {
                    "type": "text",
                    "label": " Пополнить",
                    "payload": make_payload("menu_topup"),
                }
            }
        ],
        [
            {
                "action": {
                    "type": "text",
                    "label": "🆘 Тех. поддержка",
                    "payload": make_payload("menu_support"),
                }
            },
            {
                "action": {
                    "type": "text",
                    "label": "❓ Помощь бота",
                    "payload": make_payload("menu_help"),
                }
            },
        ],
    ]
    return json.dumps(
        {"one_time": False, "inline": False, "buttons": buttons}, ensure_ascii=False
    )


def get_main_menu_reply_keyboard():
    """Обычная VK-клавиатура с кнопкой главное меню."""
    keyboard = Keyboard(one_time=False, inline=False)
    keyboard.add(Text("🏠 Главное меню", payload={"button": "back_main"}))
    return keyboard.get_json()


def merge_with_main_menu_reply(inline_keyboard_json: str = None):
    """Возвращает обычную клавиатуру с постоянной кнопкой главного меню.
    Если передан inline keyboard, для VK она не может быть объединена с reply keyboard,
    поэтому приоритет у постоянной reply-кнопки.
    """
    return get_main_menu_reply_keyboard()


def get_admin_keyboard():
    """Админ-панель"""
    builder = InlineKeyboardBuilder()
    builder.button(text="🔄 Перезагрузить пресеты", callback_data="admin_reload")
    builder.button(text="📊 Статистика", callback_data="admin_stats")
    builder.button(text="👥 Пользователи", callback_data="admin_users")
    builder.button(text="⚙️ Рассылка", callback_data="admin_broadcast")
    builder.adjust(2)
    return builder


def get_video_ready_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button("✍️ Готово, промпт", callback_data="video_ready_prompt")
    builder.button("🔙 Назад", callback_data="back_main")
    builder.row()
    return builder


def get_back_keyboard(back_payload: str = "back_main"):
    """Клавиатура 'Назад' + 'Главное меню'"""
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад", callback_data=back_payload)
    builder.button(text="🏠 Главное меню", callback_data="back_main")
    builder.row()
    return builder


def get_ai_assistant_keyboard():
    """Клавиатура для AI Assistant"""
    builder = InlineKeyboardBuilder()
    builder.button(text="🤖 Задать вопрос AI", callback_data="ai_assistant")
    builder.button(text="🔙 Назад", callback_data="back_main")
    builder.row()
    return builder


def get_create_image_keyboard(current_service: str = None, current_ratio: str = "1:1"):
    """Клавиатура создания изображения: модели, формат, рефы"""
    builder = InlineKeyboardBuilder()

    # Модели - 2 rows
    models = ["banana_2", "nano_banana_pro", "seedream45"]
    builder.button(text=f"🖼 banana_2", callback_data="model_banana_2")
    builder.button(text=f"🖼 nano_banana_pro", callback_data="model_nano_banana_pro")
    builder.row()
    builder.button(text=f"🖼 seedream45", callback_data="model_seedream45")
    builder.row()

    # Ratios - 1 row
    ratios = ["1:1", "16:9", "9:16"]
    builder.button(text="📐 1:1", callback_data="img_ratio_1_1")
    builder.button(text="📐 16:9", callback_data="img_ratio_16_9")
    builder.button(text="📐 9:16", callback_data="img_ratio_9_16")
    builder.row()

    # Actions
    builder.button(text="📎 Рефы", callback_data="img_ref_continue_new")
    builder.button(text="⏭ Пропустить рефы", callback_data="img_ref_skip_new")
    builder.row()

    return builder.build()


def get_create_video_keyboard():
    """Клавиатура создания видео"""
    builder = InlineKeyboardBuilder()
    builder.button(text="📝 Текст → Видео", callback_data="v_type_text")
    builder.button(text="🖼 Фото + Текст → Видео", callback_data="v_type_imgtxt")
    builder.button(text="🎬 Видео + Текст → Видео", callback_data="v_type_video")
    builder.button(text="🔙 Назад", callback_data="back_main")
    builder.row()
    return builder


def get_video_type_keyboard():
    """Клавиатура выбора типа видео"""
    builder = InlineKeyboardBuilder()
    builder.button(text="📝 Текст → Видео", callback_data="v_type_text")
    builder.button(text="🖼 Фото + Текст → Видео", callback_data="v_type_imgtxt")
    builder.row()
    builder.button(text="🎬 Видео + Текст → Видео", callback_data="v_type_video")
    builder.button(text="🔙 Назад", callback_data="back_main")
    builder.row()
    return builder.build()


def get_reference_images_skip_keyboard():
    """Клавиатура пропуска референсов изображений"""
    builder = InlineKeyboardBuilder()
    builder.button(text="⏭ Пропустить", callback_data='{"button": "img_ref_skip_new"}')
    builder.button(text="🏠 Главное меню", callback_data='{"button": "back_main"}')
    builder.row()
    return builder


def get_reference_images_upload_keyboard(
    current_count: int, max_count: int, mode: str = "new"
):
    """Клавиатура загрузки референсов изображений"""
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Продолжить", callback_data="img_ref_continue_new")
    builder.button(text="⏭ Пропустить", callback_data="img_ref_skip_new")
    builder.button(text="🏠 Главное меню", callback_data="back_main")
    builder.row()
    return builder.build()


def get_video_models_keyboard(current_model: str = None):
    builder = InlineKeyboardBuilder()
    models = ["v3_std", "v3_pro", "v3_omni_std", "v3_omni_pro", "v26_pro"]
    for i in range(0, len(models), 2):
        if i < len(models):
            model1 = models[i]
            text1 = f"🤖 {model1}" + (" ✓" if current_model == model1 else "")
            builder.button(text=text1, callback_data=f"v_model_{model1}")
        if i + 1 < len(models):
            model2 = models[i + 1]
            text2 = f"🤖 {model2}" + (" ✓" if current_model == model2 else "")
            builder.button(text=text2, callback_data=f"v_model_{model2}")
        builder.row()
    builder.button(text="🔙 Назад", callback_data="back_main")
    builder.row()
    return builder


def get_video_params_keyboard(current_duration: int = 5, current_ratio: str = "16:9"):
    """Клавиатура параметров видео: ratio и duration"""
    builder = InlineKeyboardBuilder()
    ratios = ["16:9", "9:16", "1:1"]
    for ratio in ratios:
        text = f"📐 {ratio}" + (" ✓" if current_ratio == ratio else "")
        builder.button(text=text, callback_data=f"ratio_{ratio.replace(':', '_')}")
        builder.row()
    durations = [5, 10, 15]
    for dur in durations:
        text = f"⏱ {dur}s" + (" ✓" if current_duration == dur else "")
        builder.button(text=text, callback_data=f"video_dur_{dur}")
        builder.row()
    builder.button(text="✍️ Готово, промпт", callback_data="video_ready_prompt")
    builder.button(text="🔙 Назад", callback_data="back_main")
    builder.row()
    return builder


def get_payment_confirmation_keyboard(package_id: str, price_rub: int):
    """Клавиатура подтверждения платежа"""
    builder = InlineKeyboardBuilder()
    builder.button(
        text=f"💳 Оплатить {price_rub}₽", callback_data=f"confirm_payment_{package_id}"
    )
    builder.button(text="❌ Отмена", callback_data="back_main")
    builder.row()
    return builder


def get_motion_control_keyboard():
    builder = InlineKeyboardBuilder()
    builder.button(text="🎬 Std (6🍌)", callback_data="motion_control_std")
    builder.button(text="💎 Pro (8🍌)", callback_data="motion_control_pro")
    builder.row()
    builder.button(text="🔙 Главное меню", callback_data="back_main")
    builder.row()
    return builder.build()


def get_payment_packages_keyboard():
    """Клавиатура пакетов оплаты"""
    builder = InlineKeyboardBuilder()
    for package in PACKAGES:
        pkg_id = package["id"]
        price = package["price_rub"]
        popular = package.get("popular", False)
        text = f"{'⭐ ' if popular else ''}{package['credits']}🍌 за {price}₽"
        builder.button(text=text, callback_data=f"package_{pkg_id}")
    builder.row()
    builder.button(text="❌ Отмена", callback_data="back_main")
    builder.row()
    return builder
