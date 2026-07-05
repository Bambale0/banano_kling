from copy import deepcopy

IMAGE_MODEL_ORDER = [
    # Text-to-image (работают без референсов)
    "banana_pro",
    "banana_2",
    "nano_banana_2_lite",
    "wan_27_image_pro",
    "wan_27_image",
    "gpt_image_2",
    "grok_t2i",
    # Image-to-image (требуют хотя бы один референс)
    "grok_i2i",
    "seedream_5_lite",
    "seedream_edit",
    "ideogram_character",
]


IMAGE_MODEL_ALIASES = {
    "nanobanana": "banana_pro",
    "nano-banana-pro": "banana_pro",
    "nano-banana-2-lite": "nano_banana_2_lite",
    "seedream": "seedream_edit",
    "seedream_45": "seedream_edit",
    "wan-image": "wan_27_image",
    "wan-image-pro": "wan_27_image_pro",
}


IMAGE_MODEL_CONFIGS = {
    "banana_pro": {
        "label": "💎 Banana Pro",
        "settings_label": "💎 Banana Pro",
        "cost_key": "nano-banana-pro",
        "requires_refs": False,
        "supports_refs": True,
        "aspect_ratios": ["1:1", "16:9", "9:16", "4:3", "3:2"],
        "defaults": {
            "aspect_ratio": "1:1",
            "resolution": "4K",
            "output_format": "png",
        },
        "options": {
            "aspect_ratio": ["1:1", "16:9", "9:16", "4:3", "3:2"],
            "resolution": ["2K", "4K"],
            "output_format": ["png", "jpg"],
        },
        "service": "banana_pro",
    },
    "banana_2": {
        "label": "🪙 Banana 2",
        "settings_label": "🪙 Banana 2",
        "cost_key": "banana_2",
        "requires_refs": False,
        "supports_refs": True,
        "aspect_ratios": ["auto", "1:1", "16:9", "9:16", "4:3", "3:2"],
        "defaults": {
            "aspect_ratio": "auto",
            "resolution": "1K",
            "output_format": "png",
        },
        "options": {
            "aspect_ratio": ["auto", "1:1", "16:9", "9:16", "4:3", "3:2"],
            "resolution": ["1K", "2K", "4K"],
            "output_format": ["png", "jpg"],
        },
        "service": "banana_2",
    },
    "nano_banana_2_lite": {
        "label": "⚡ Nano Banana 2 Lite",
        "settings_label": "⚡ Nano Banana 2 Lite",
        "cost_key": "nano_banana_2_lite",
        "requires_refs": False,
        "supports_refs": True,
        "aspect_ratios": [
            "auto", "1:1", "1:4", "1:8", "2:3", "3:2", "3:4", "4:1",
            "4:3", "4:5", "5:4", "8:1", "9:16", "16:9", "21:9",
        ],
        "defaults": {
            "aspect_ratio": "auto",
        },
        "options": {
            "aspect_ratio": [
                "auto", "1:1", "1:4", "1:8", "2:3", "3:2", "3:4", "4:1",
                "4:3", "4:5", "5:4", "8:1", "9:16", "16:9", "21:9",
            ],
        },
        "service": "kie_market",
        "api_model": "nano-banana-2-lite",
    },
    "wan_27_image": {
        "label": "🌊 Wan 2.7 Image",
        "settings_label": "🌊 Wan Image",
        "cost_key": "wan_27_image",
        "requires_refs": False,
        "supports_refs": True,
        "aspect_ratios": ["1:1", "3:4", "4:3", "1:8", "8:1", "9:16", "16:9", "21:9"],
        "defaults": {
            "aspect_ratio": "1:1",
            "resolution": "2K",
            "n": 1,
            "enable_sequential": False,
            "thinking_mode": True,
            "watermark": False,
            "seed": 0,
            "nsfw_checker": True,
        },
        "options": {
            "aspect_ratio": ["1:1", "3:4", "4:3", "1:8", "8:1", "9:16", "16:9", "21:9"],
            "resolution": ["1K", "2K"],
            "enable_sequential": [False, True],
            "thinking_mode": [True, False],
            "watermark": [False, True],
            "nsfw_checker": [True, False],
        },
        "service": "wan_27_image",
    },
    "wan_27_image_pro": {
        "label": "🌊 Wan 2.7 Image Pro",
        "settings_label": "🌊 Wan Image Pro",
        "cost_key": "wan_27_image_pro",
        "requires_refs": False,
        "supports_refs": True,
        "aspect_ratios": ["1:1", "3:4", "4:3", "1:8", "8:1", "9:16", "16:9", "21:9"],
        "defaults": {
            "aspect_ratio": "1:1",
            "resolution": "2K",
            "n": 1,
            "enable_sequential": False,
            "thinking_mode": False,
            "watermark": False,
            "seed": 0,
            "nsfw_checker": True,
        },
        "options": {
            "aspect_ratio": ["1:1", "3:4", "4:3", "1:8", "8:1", "9:16", "16:9", "21:9"],
            "resolution": ["1K", "2K", "4K"],
            "enable_sequential": [False, True],
            "thinking_mode": [False, True],
            "watermark": [False, True],
            "nsfw_checker": [True, False],
        },
        "service": "wan_27_image_pro",
    },
    "gpt_image_2": {
        "label": "🧠 GPT Image 2",
        "settings_label": "🧠 GPT Image 2",
        "cost_key": "gpt_image_2",
        "requires_refs": False,
        "supports_refs": True,
        "aspect_ratios": [
            "auto",
            "1:1",
            "5:4",
            "4:5",
            "4:3",
            "3:4",
            "3:2",
            "2:3",
            "16:9",
            "9:16",
            "21:9",
        ],
        "defaults": {
            "aspect_ratio": "auto",
            "nsfw_checker": False,
        },
        "options": {
            "aspect_ratio": [
                "auto",
                "1:1",
                "5:4",
                "4:5",
                "4:3",
                "3:4",
                "3:2",
                "2:3",
                "16:9",
                "9:16",
                "21:9",
            ],
            "nsfw_checker": [False, True],
        },
        "service": "gpt_image_2",
    },
    "grok_t2i": {
        "label": "✨ Grok Imagine",
        "settings_label": "✨ Grok Imagine T2I",
        "cost_key": "grok_t2i",
        "requires_refs": False,
        "supports_refs": False,
        "aspect_ratios": ["1:1", "16:9", "9:16", "3:2", "2:3"],
        "defaults": {
            "aspect_ratio": "1:1",
            "enable_pro": False,
            "nsfw_checker": False,
        },
        "options": {
            "aspect_ratio": ["1:1", "16:9", "9:16", "3:2", "2:3"],
            "enable_pro": [False, True],
            "nsfw_checker": [False, True],
        },
        "service": "grok_t2i",
    },
    "grok_i2i": {
        "label": "✨ Grok Img→Img",
        "settings_label": "✨ Grok Img→Img",
        "cost_key": "grok_i2i",
        "requires_refs": True,
        "supports_refs": True,
        "aspect_ratios": ["1:1", "16:9", "9:16", "3:2", "2:3"],
        "defaults": {
            "aspect_ratio": "1:1",
            "nsfw_checker": False,
        },
        "options": {
            "aspect_ratio": ["1:1", "16:9", "9:16", "3:2", "2:3"],
            "nsfw_checker": [False, True],
        },
        "service": "grok_i2i",
    },
    "ideogram_character": {
        "label": "🧑 Ideogram Character",
        "settings_label": "🧑 Ideogram Character",
        "cost_key": "ideogram_character",
        "requires_refs": True,
        "supports_refs": True,
        "aspect_ratios": ["1:1", "16:9", "9:16", "4:3", "3:4"],
        "defaults": {
            "aspect_ratio": "1:1",
            "rendering_speed": "BALANCED",
            "style": "AUTO",
            "expand_prompt": True,
            "num_images": "1",
            "nsfw_checker": False,
        },
        "options": {
            "aspect_ratio": ["1:1", "16:9", "9:16", "4:3", "3:4"],
            "rendering_speed": ["TURBO", "BALANCED", "QUALITY"],
            "style": ["AUTO", "REALISTIC", "FICTION"],
            "expand_prompt": [True, False],
            "nsfw_checker": [False, True],
        },
        "service": "ideogram_character",
    },
    "seedream_5_lite": {
        "label": "🔥 Seedream 5.0 Lite",
        "settings_label": "🔥 Seedream 5.0 Lite",
        "cost_key": "seedream_5_lite",
        "requires_refs": True,
        "supports_refs": True,
        "aspect_ratios": ["1:1", "16:9", "9:16", "4:3", "3:2"],
        "defaults": {
            "aspect_ratio": "1:1",
            "quality": "basic",
            "nsfw_checker": False,
        },
        "options": {
            "aspect_ratio": ["1:1", "16:9", "9:16", "4:3", "3:2"],
            "quality": ["basic", "high"],
            "nsfw_checker": [False, True],
        },
        "service": "seedream",
        "api_model": "seedream/5-lite-image-to-image",
    },
    "seedream_edit": {
        "label": "🖌 Seedream 4.5 Edit",
        "settings_label": "🖌 Seedream 4.5 Edit",
        "cost_key": "seedream_edit",
        "requires_refs": True,
        "supports_refs": True,
        "aspect_ratios": ["1:1", "16:9", "9:16", "4:3", "3:2"],
        "defaults": {
            "aspect_ratio": "1:1",
            "quality": "basic",
            "nsfw_checker": False,
        },
        "options": {
            "aspect_ratio": ["1:1", "16:9", "9:16", "4:3", "3:2"],
            "quality": ["basic", "high"],
            "nsfw_checker": [False, True],
        },
        "service": "seedream",
        "api_model": "seedream/4.5-edit",
    },
}


IMAGE_OPTION_LABELS = {
    "aspect_ratio": "Формат",
    "resolution": "Разрешение",
    "output_format": "Формат файла",
    "enable_pro": "Pro режим",
    "quality": "Качество",
    "nsfw_checker": "NSFW check",
    "enable_sequential": "Галерея",
    "thinking_mode": "Thinking",
    "watermark": "Watermark",
    "seed": "Seed",
    "rendering_speed": "Скорость",
    "style": "Стиль",
    "expand_prompt": "Улучшение",
}


def resolve_image_model(model_id: str) -> str:
    if not model_id:
        return "banana_pro"
    return IMAGE_MODEL_ALIASES.get(model_id, model_id)


def get_image_model_config(model_id: str) -> dict:
    resolved = resolve_image_model(model_id)
    config = IMAGE_MODEL_CONFIGS.get(resolved, IMAGE_MODEL_CONFIGS["banana_pro"])
    return deepcopy(config)


def normalize_image_options(model_id: str, options: dict | None = None) -> dict:
    config = get_image_model_config(model_id)
    normalized = deepcopy(config["defaults"])

    if options:
        normalized.update(options)

    for option_name, allowed_values in config["options"].items():
        if normalized.get(option_name) not in allowed_values:
            normalized[option_name] = allowed_values[0]

    return normalized


def get_image_option_label(option_name: str, value):
    if option_name == "aspect_ratio":
        return str(value)
    if option_name == "resolution":
        return str(value)
    if option_name == "output_format":
        return str(value).upper()
    if option_name == "enable_pro":
        return "⚡ Pro" if value else "Std"
    if option_name == "quality":
        return "Basic" if value == "basic" else str(value).upper()
    if option_name in {"nsfw_checker", "enable_sequential", "thinking_mode", "watermark"}:
        if option_name == "nsfw_checker":
            return "NSFW ON" if value else "NSFW OFF"
        if option_name == "enable_sequential":
            return "Галерея ON" if value else "Галерея OFF"
        if option_name == "thinking_mode":
            return "Thinking ON" if value else "Thinking OFF"
        return "Watermark ON" if value else "Watermark OFF"
    if option_name == "seed":
        return str(value)
    if option_name == "nsfw_checker":
        return "NSFW ON" if value else "NSFW OFF"
    if option_name == "rendering_speed":
        return str(value).title()
    if option_name == "style":
        return str(value).title()
    if option_name == "expand_prompt":
        return "ON" if value else "OFF"
    return str(value)
