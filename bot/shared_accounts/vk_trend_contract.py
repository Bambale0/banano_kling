"""Server-side capability check; never serialize a native trend recipe."""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

NATIVE_IMAGE_MODELS = {
    'banana_pro': 'nano_banana_pro',
    'banana_2': 'nano_banana_2',
    'gpt_image_2': 'gpt_image_2',
}


def supports_native_vk_image_trend(trend: Mapping[str, Any]) -> bool:
    settings = trend.get('generation_settings')
    if not isinstance(settings, Mapping):
        return False
    return (
        settings.get('kind') == 'image'
        and (settings.get('model') or trend.get('model')) in NATIVE_IMAGE_MODELS
        and str(settings.get('quality') or '2K') in {'2K', '4K'}
        and settings.get('ratio') in {'1:1', '16:9', '9:16', '4:3', '3:4', '3:2', '2:3', '21:9'}
        and settings.get('user_input', 'photo') == 'photo'
        and str(settings.get('count') or 1) == '1'
        and not settings.get('reference_contract')
        and not settings.get('genjutsu_recipe_id')
    )
