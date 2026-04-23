from copy import deepcopy

IMAGE_MODEL_ORDER = [
    "banana_pro",
    "banana_2",
    "gpt_image_2",
    "seedream_5_lite",
    "seedream_edit",
]


IMAGE_MODEL_ALIASES = {
    "nanobanana": "banana_pro",
    "nano-banana-pro": "banana_pro",
    "seedream": "seedream_edit",
    "seedream_45": "seedream_edit",
}


IMAGE_MODEL_CONFIGS = {
    "banana_pro": {
        "label": "💎 Banana Pro",
        "settings_label": "💎 Banana Pro",
        "cost_key": "nano-banana-pro",
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
        "label": "🍌 Banana 2",
        "settings_label": "🍌 Banana 2",
        "cost_key": "banana_2",
        "aspect_ratios": ["auto", "1:1", "16:9", "9:16", "4:3", "3:2"],
        "defaults": {
            "aspect_ratio": "auto",
            "resolution": "4K",
            "output_format": "png",
        },
        "options": {
            "aspect_ratio": ["auto", "1:1", "16:9", "9:16", "4:3", "3:2"],
            "resolution": ["2K", "4K"],
            "output_format": ["png", "jpg"],
        },
        "service": "banana_2",
    },
    "gpt_image_2": {
        "label": "🧠 GPT Image 2",
        "settings_label": "🧠 GPT Image 2",
        "cost_key": "gpt_image_2",
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
    "seedream_5_lite": {
        "label": "🔥 Seedream 5.0 Lite",
        "settings_label": "🔥 Seedream 5.0 Lite",
        "cost_key": "seedream_5_lite",
        "aspect_ratios": ["1:1", "16:9", "9:16", "4:3", "3:2"],
        "defaults": {
            "aspect_ratio": "1:1",
            "quality": "basic",
            "nsfw_checker": False,
        },
        "options": {
            "aspect_ratio": ["1:1", "16:9", "9:16", "4:3", "3:2"],
            "nsfw_checker": [False, True],
        },
        "service": "seedream",
        "api_model": "seedream/5-lite-image-to-image",
    },
    "seedream_edit": {
        "label": "🖌 Seedream 4.5",
        "settings_label": "🖌 Seedream 4.5",
        "cost_key": "seedream_edit",
        "aspect_ratios": ["1:1", "16:9", "9:16", "4:3", "3:2"],
        "defaults": {
            "aspect_ratio": "1:1",
            "quality": "basic",
            "nsfw_checker": False,
        },
        "options": {
            "aspect_ratio": ["1:1", "16:9", "9:16", "4:3", "3:2"],
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
    "nsfw_checker": "NSFW check",
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
    if option_name == "nsfw_checker":
        return "ON" if value else "OFF"
    return str(value)
