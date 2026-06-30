from copy import deepcopy

VIDEO_MODEL_ORDER_BY_TYPE = {
    "text": [
        "gemini_omni",
        "v3_std",
        "v3_pro",
        "runway",
        "veo3_fast",
        "veo3",
        "veo3_lite",
        "wan_27_t2v",
        "wan_27_r2v",
        "hailuo_pro",
        "hailuo_std",
        "happyhorse_t2v",
    ],
    "imgtxt": [
        "gemini_omni",
        "v3_std",
        "v3_pro",
        "seedance2",
        "runway",
        "grok_imagine",
        "wan_27_i2v",
        "wan_27_r2v",
        "veo3_fast",
        "hailuo_23_pro",
        "hailuo_23_std",
        "hailuo_i2v_pro",
        "hailuo_i2v_std",
        "happyhorse_i2v",
        "happyhorse_ref2v",
    ],
    "video": [
        "gemini_omni",
        "aleph",
        "glow",
        "wan_27_videoedit",
        "happyhorse_edit",
    ],
}


VIDEO_MODEL_CONFIGS = {
    "gemini_omni": {
        "label": "🔷 Gemini Omni",
        "v_types": ["text", "imgtxt", "video"],
        "supports_refs": True,
        "aspect_ratios": ["16:9", "9:16"],
        "durations": [4, 6, 8, 10],
        "defaults": {"resolution": "720p", "seed": None},
        "options": {"resolution": ["720p", "1080p", "4k"]},
    },
    "v3_std": {
        "label": "⚡ Kling 3 Std",
        "v_types": ["text", "imgtxt"],
        "supports_refs": True,
        "aspect_ratios": ["16:9", "9:16", "1:1"],
        "durations": [3, 5, 10, 15],
        "defaults": {"sound": True},
        "options": {"sound": [True, False]},
    },
    "v3_pro": {
        "label": "💎 Kling 3 Pro",
        "v_types": ["text", "imgtxt"],
        "supports_refs": True,
        "aspect_ratios": ["16:9", "9:16", "1:1"],
        "durations": [3, 5, 10, 15],
        "defaults": {"sound": True},
        "options": {"sound": [True, False]},
    },
    "seedance2": {
        "label": "🌱 Seedance 2.0",
        "v_types": ["imgtxt"],
        "requires_refs": True,
        "supports_refs": True,
        "aspect_ratios": ["16:9", "9:16", "1:1"],
        "durations": [5, 10, 15],
        "defaults": {
            "resolution": "720p",
            "sound": True,
            "nsfw_checker": False,
            "web_search": False,
        },
        "options": {
            "resolution": ["720p", "1080p"],
            "sound": [True, False],
            "nsfw_checker": [False, True],
            "web_search": [False, True],
        },
    },
    "grok_imagine": {
        "label": "🧠 Grok Imagine",
        "v_types": ["imgtxt"],
        "requires_refs": True,
        "supports_refs": True,
        "aspect_ratios": ["16:9", "9:16", "1:1", "3:2", "2:3"],
        "durations": [6, 10, 20, 30],
        "defaults": {"mode": "normal", "resolution": "720p", "nsfw_checker": False},
        "options": {
            "mode": ["normal", "fun", "spicy"],
            "resolution": ["720p", "1080p"],
            "nsfw_checker": [False, True],
        },
    },
    "runway": {
        "label": "🎥 Runway AI",
        "v_types": ["text", "imgtxt"],
        "supports_refs": True,
        "aspect_ratios": ["16:9", "9:16", "1:1"],
        "durations": [5, 10],
        "defaults": {"quality": "720p"},
        "options": {"quality": ["720p", "1080p"]},
    },
    "aleph": {
        "label": "🔮 Aleph Video",
        "v_types": ["video"],
        "requires_refs": True,
        "supports_refs": True,
        "aspect_ratios": ["21:9", "16:9", "4:3", "1:1", "3:4", "9:16"],
        "durations": [5, 10],
        "defaults": {},
        "options": {},
    },
    "glow": {
        "label": "✨ Kling Glow",
        "v_types": ["video"],
        "requires_refs": True,
        "supports_refs": True,
        "aspect_ratios": ["16:9", "9:16", "1:1"],
        "durations": [5, 10],
        "defaults": {
            "motion_quality": "720p",
            "character_orientation": "video",
            "keep_original_sound": True,
        },
        "options": {
            "motion_quality": ["720p", "1080p"],
            "character_orientation": ["video", "image"],
            "keep_original_sound": [True, False],
        },
    },
    "veo3_fast": {
        "label": "🎬 Veo 3.1 Fast",
        "v_types": ["text", "imgtxt"],
        "supports_refs": True,
        "aspect_ratios": ["16:9", "9:16"],
        "durations": [],
        "defaults": {"resolution": "1080p", "enable_translation": True},
        "options": {
            "resolution": ["720p", "1080p"],
            "enable_translation": [True, False],
        },
    },
    "veo3": {
        "label": "🎬 Veo 3.1 Pro",
        "v_types": ["text"],
        "supports_refs": False,
        "aspect_ratios": ["16:9", "9:16"],
        "durations": [],
        "defaults": {"resolution": "1080p", "enable_translation": True},
        "options": {
            "resolution": ["720p", "1080p"],
            "enable_translation": [True, False],
        },
    },
    "veo3_lite": {
        "label": "🎬 Veo 3.1 Lite",
        "v_types": ["text"],
        "supports_refs": False,
        "aspect_ratios": ["16:9", "9:16"],
        "durations": [],
        "defaults": {"resolution": "720p", "enable_translation": True},
        "options": {
            "resolution": ["720p", "1080p"],
            "enable_translation": [True, False],
        },
    },
    "hailuo_23_pro": {
        "label": "🌊 Hailuo 2.3 I2V Pro",
        "v_types": ["imgtxt"],
        "requires_refs": True,
        "supports_refs": True,
        "aspect_ratios": ["16:9"],
        "durations": [6, 10],
        "defaults": {"resolution": "768P", "nsfw_checker": False},
        "options": {"resolution": ["768P", "1080P"], "nsfw_checker": [False, True]},
    },
    "hailuo_23_std": {
        "label": "🌊 Hailuo 2.3 I2V Std",
        "v_types": ["imgtxt"],
        "requires_refs": True,
        "supports_refs": True,
        "aspect_ratios": ["16:9"],
        "durations": [6, 10],
        "defaults": {"resolution": "768P", "nsfw_checker": False},
        "options": {"resolution": ["768P", "1080P"], "nsfw_checker": [False, True]},
    },
    "hailuo_pro": {
        "label": "🌊 Hailuo 02 T2V Pro",
        "v_types": ["text"],
        "supports_refs": False,
        "aspect_ratios": ["16:9"],
        "durations": [],
        "defaults": {"prompt_optimizer": False, "nsfw_checker": False},
        "options": {"prompt_optimizer": [False, True], "nsfw_checker": [False, True]},
    },
    "hailuo_std": {
        "label": "🌊 Hailuo 02 T2V Std",
        "v_types": ["text"],
        "supports_refs": False,
        "aspect_ratios": ["16:9"],
        "durations": [6, 10],
        "defaults": {"prompt_optimizer": False, "nsfw_checker": False},
        "options": {"prompt_optimizer": [False, True], "nsfw_checker": [False, True]},
    },
    "hailuo_i2v_pro": {
        "label": "🌊 Hailuo 02 I2V Pro",
        "v_types": ["imgtxt"],
        "requires_refs": True,
        "supports_refs": True,
        "aspect_ratios": ["16:9"],
        "durations": [],
        "defaults": {"prompt_optimizer": False, "nsfw_checker": False},
        "options": {"prompt_optimizer": [False, True], "nsfw_checker": [False, True]},
    },
    "hailuo_i2v_std": {
        "label": "🌊 Hailuo 02 I2V Std",
        "v_types": ["imgtxt"],
        "requires_refs": True,
        "supports_refs": True,
        "aspect_ratios": ["16:9"],
        "durations": [6, 10],
        "defaults": {
            "resolution": "768P",
            "prompt_optimizer": False,
            "nsfw_checker": False,
        },
        "options": {
            "resolution": ["768P", "1080P"],
            "prompt_optimizer": [False, True],
            "nsfw_checker": [False, True],
        },
    },
    "happyhorse_t2v": {
        "label": "🐴 HappyHorse T2V",
        "v_types": ["text"],
        "supports_refs": False,
        "aspect_ratios": ["16:9", "9:16", "1:1"],
        "durations": [5, 10, 15],
        "defaults": {"resolution": "1080p", "seed": None},
        "options": {"resolution": ["720p", "1080p"]},
    },
    "happyhorse_i2v": {
        "label": "🐴 HappyHorse I2V",
        "v_types": ["imgtxt"],
        "requires_refs": True,
        "supports_refs": True,
        "aspect_ratios": ["16:9"],
        "durations": [5, 10, 15],
        "defaults": {"resolution": "1080p", "seed": None},
        "options": {"resolution": ["720p", "1080p"]},
    },
    "happyhorse_ref2v": {
        "label": "🐴 HappyHorse Ref2V",
        "v_types": ["imgtxt"],
        "requires_refs": True,
        "supports_refs": True,
        "aspect_ratios": ["16:9", "9:16", "1:1"],
        "durations": [5, 10, 15],
        "defaults": {"resolution": "1080p", "seed": None},
        "options": {"resolution": ["720p", "1080p"]},
    },
    "happyhorse_edit": {
        "label": "🐴 HappyHorse Edit",
        "v_types": ["video"],
        "requires_refs": True,
        "supports_refs": True,
        "aspect_ratios": ["16:9"],
        "durations": [],
        "defaults": {"resolution": "1080p", "audio_setting": "auto", "seed": None},
        "options": {
            "resolution": ["720p", "1080p"],
            "audio_setting": ["auto", "keep", "remove"],
        },
    },
    "wan_27_t2v": {
        "label": "🌊 Wan 2.7 T2V",
        "v_types": ["text"],
        "supports_refs": False,
        "aspect_ratios": ["16:9", "9:16", "1:1", "4:3", "3:4"],
        "durations": list(range(2, 16)),
        "defaults": {
            "negative_prompt": "",
            "audio_url": "",
            "resolution": "1080p",
            "prompt_extend": True,
            "watermark": False,
            "seed": 0,
            "nsfw_checker": True,
        },
        "options": {
            "resolution": ["720p", "1080p"],
            "prompt_extend": [True, False],
            "watermark": [False, True],
            "nsfw_checker": [False, True],
        },
    },
    "wan_27_i2v": {
        "label": "🌊 Wan 2.7 I2V",
        "v_types": ["imgtxt"],
        "requires_refs": True,
        "supports_refs": True,
        "aspect_ratios": [],
        "durations": list(range(2, 16)),
        "defaults": {
            "resolution": "1080p",
            "prompt_extend": True,
            "watermark": False,
            "seed": 0,
            "nsfw_checker": True,
        },
        "options": {
            "resolution": ["720p", "1080p"],
            "prompt_extend": [True, False],
            "watermark": [False, True],
            "nsfw_checker": [True, False],
        },
    },
    "wan_27_r2v": {
        "label": "🌊 Wan 2.7 R2V",
        "v_types": ["text", "imgtxt"],
        "requires_refs": True,
        "supports_refs": True,
        "aspect_ratios": ["16:9", "9:16", "1:1", "4:3", "3:4"],
        "durations": list(range(2, 11)),
        "defaults": {
            "resolution": "1080p",
            "prompt_extend": True,
            "watermark": False,
            "seed": 0,
            "nsfw_checker": True,
        },
        "options": {
            "resolution": ["720p", "1080p"],
            "prompt_extend": [True, False],
            "watermark": [False, True],
            "nsfw_checker": [True, False],
        },
    },
    "wan_27_videoedit": {
        "label": "🌊 Wan 2.7 VideoEdit",
        "v_types": ["video"],
        "requires_refs": True,
        "supports_refs": True,
        "aspect_ratios": ["16:9", "9:16", "1:1", "4:3", "3:4"],
        "durations": list(range(0, 11)),
        "defaults": {
            "resolution": "720p",
            "audio_setting": "auto",
            "prompt_extend": True,
            "watermark": False,
            "seed": 0,
            "nsfw_checker": True,
        },
        "options": {
            "resolution": ["720p", "1080p"],
            "audio_setting": ["auto", "origin"],
            "prompt_extend": [True, False],
            "watermark": [False, True],
            "nsfw_checker": [True, False],
        },
    },
}


VIDEO_OPTION_LABELS = {
    "quality": "Качество",
    "resolution": "Разрешение",
    "mode": "Режим",
    "motion_quality": "Motion",
    "character_orientation": "Ориентация",
    "audio_setting": "Аудио",
    "sound": "Звук",
    "keep_original_sound": "Ориг. звук",
    "nsfw_checker": "NSFW check",
    "web_search": "Web search",
    "prompt_optimizer": "Оптимизация",
    "enable_translation": "Перевод",
    "prompt_extend": "Улучшение",
    "watermark": "Watermark",
    "seed": "Seed",
}


def format_inline_choice(option_name: str, value) -> str:
    labels = {
        "mode": {
            "normal": "🎬 Normal",
            "fun": "✨ Fun",
            "spicy": "🌶 Spicy",
        },
        "resolution": {
            "720p": "📺 HD",
            "1080p": "🖥 Full HD",
            "4k": "🎞 4K",
        },
        "quality": {
            "720p": "📺 HD",
            "1080p": "🖥 Full HD",
            "4k": "🎞 4K",
            "std": "⚡ Std",
            "pro": "💎 Pro",
        },
        "nsfw_checker": {
            True: "🛡 Фильтр ON",
            False: "🔓 Фильтр OFF",
        },
    }
    option_labels = labels.get(option_name)
    if option_labels is not None and value in option_labels:
        return option_labels[value]
    return get_video_option_label(option_name, value)



def get_video_model_config(model_id: str) -> dict:
    return deepcopy(VIDEO_MODEL_CONFIGS.get(model_id, VIDEO_MODEL_CONFIGS["v3_std"]))


def get_video_models_for_type(v_type: str) -> list[str]:
    return [
        model_id
        for model_id in VIDEO_MODEL_ORDER_BY_TYPE.get(v_type, [])
        if v_type in VIDEO_MODEL_CONFIGS.get(model_id, {}).get("v_types", [])
    ]


def normalize_video_options(model_id: str, options: dict | None = None) -> dict:
    config = get_video_model_config(model_id)
    normalized = deepcopy(config.get("defaults", {}))
    if options:
        normalized.update(options)

    for option_name, allowed_values in config.get("options", {}).items():
        value = normalized.get(option_name)
        if value not in allowed_values:
            normalized[option_name] = allowed_values[0]
    return normalized


def get_video_option_label(option_name: str, value) -> str:
    if isinstance(value, bool):
        return "ON" if value else "OFF"
    labels = {
        "normal": "Normal",
        "fun": "Fun",
        "spicy": "Spicy",
        "video": "Video",
        "image": "Image",
        "auto": "Auto",
        "keep": "Keep",
        "remove": "Remove",
    }
    return labels.get(str(value), str(value))
