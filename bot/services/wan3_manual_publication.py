"""Strict manual publication input; no persistence, permissions or network I/O."""
from __future__ import annotations

from copy import deepcopy

from bot.services.wan3_prime_media import Wan3PrimeValidationError
from bot.services.wan3_prime_repeat import RECIPE_FIELDS, source_slots


def manual_publication_input(model, prompt, settings):
    if model not in {'wan_3', 'wan_3_prime'} or not isinstance(settings, dict):
        raise Wan3PrimeValidationError('Выберите модель Wan и заполните редактор тренда.')
    raw = settings.get('wan3_recipe')
    if not isinstance(raw, dict) or set(raw) - set(RECIPE_FIELDS):
        raise Wan3PrimeValidationError('Для публикации нужен полный рецепт Wan.')
    if raw.get('model') != model or settings.get('model') != model:
        raise Wan3PrimeValidationError('Модель рецепта не совпадает с моделью тренда.')
    if (not isinstance(raw.get('prompt'), str) or not isinstance(prompt, str) or not prompt.strip()
            or raw['prompt'].strip() != prompt.strip()):
        raise Wan3PrimeValidationError('Текст рецепта не совпадает с промптом тренда.')
    if settings.get('user_fields'):
        raise Wan3PrimeValidationError('Поля подстановки пока не поддерживаются в трендах Wan. Удалите их перед публикацией.')
    required = {'scenario', 'resolution', 'aspect_ratio', 'duration', 'audio', 'nsfw_checker'}
    if not required <= raw.keys():
        raise Wan3PrimeValidationError('Укажите режим, качество, формат, длительность и настройки Wan.')
    if raw.get('reference_link_urls'):
        raise Wan3PrimeValidationError('Для тренда загрузите файл вместо внешней ссылки.')
    for field in ('reference_image_urls', 'reference_video_urls', 'reference_audio_urls', 'reference_file_urls'):
        values = raw.get(field, [])
        if not isinstance(values, list) or any(not isinstance(value, str) or not value.strip() for value in values):
            raise Wan3PrimeValidationError('Референсы должны быть списком загруженных файлов.')
    for field in ('first_frame_url', 'last_frame_url'):
        if raw.get(field) is not None and not isinstance(raw[field], str):
            raise Wan3PrimeValidationError('Кадр должен быть загруженным изображением.')
    recipe = deepcopy(raw)
    recipe['prompt'] = prompt.strip()
    keys = settings.get('wan3_replacement_keys')
    if (not isinstance(keys, list) or any(not isinstance(key, str) for key in keys)
            or len(set(keys)) != len(keys)):
        raise Wan3PrimeValidationError('Укажите отдельные места для замены референсов.')
    slots = source_slots(recipe)
    if not set(keys) <= {slot['key'] for slot in slots}:
        raise Wan3PrimeValidationError('Место замены отсутствует в рецепте.')
    # Slot roles are derived from the validated scenario and ordered media,
    # never from an arbitrary client-provided fixed/owner capability.
    return recipe, keys
