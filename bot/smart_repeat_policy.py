"""Read existing model/upload capabilities; author rules may only narrow them."""
from __future__ import annotations

import math
import mimetypes
from collections import Counter

from bot.smart_repeat_contract import fail


def list_fields(source):
    model = source['model']
    if source['type'] == 'image':
        from bot.handlers.generation import _get_max_image_references
        from bot.miniapp import IMAGE_MODELS
        card = next((item for item in IMAGE_MODELS if item['id'] == model), None)
        maximum = min(int(card['max_references']), _get_max_image_references(model)) if card else 0
        return {'image': {'field': 'reference_images', 'maximum': maximum}}
    if model in {'wan_3', 'wan_3_prime'}:
        from bot.services.wan3_prime_media import REFERENCE_LIMITS
        from bot.services.wan3_prime_repeat import source_recipe
        # Adding media must not silently change a text/frames/edit scenario.
        scenario = source_recipe(source)['scenario']
        if scenario != 'reference':
            return {}
        return {kind: {'field': f'reference_{kind}_urls', 'maximum': REFERENCE_LIMITS[f'reference_{kind}_urls']}
                for kind in ('image', 'video', 'audio')}
    from bot.model_capabilities import get_video_capability
    capability = get_video_capability(model)
    if not capability:
        return {}
    data = source.get('request_data') or {}
    if isinstance(data, str):
        import json
        data = json.loads(data)
    if model == 'seedance_2_5' and (data.get('seedance25_video_editing') or data.get('seedance25_identity_transfer')
        or data.get('seedance25_scenario') not in {'multimodal', None}):
        return {}
    return {kind: {'field': field, 'maximum': maximum} for kind, field, maximum in (
        ('image', 'reference_images', capability.max_reference_images),
        ('video', 'v_reference_videos', capability.max_reference_videos),
        ('audio', 'seedance25_reference_audio_urls', capability.max_reference_audio)) if maximum}


def asset_policy(model, kind):
    if model in {'wan_3', 'wan_3_prime'}:
        from bot.services.wan3_prime_storage import _allowed_ext, _kind_limit
        extensions, maximum = _allowed_ext(kind), _kind_limit(kind)
    elif model == 'seedance_2_5':
        from bot.handlers import seedance_25_fullstack as rules
        extensions = {'.' + value for value in getattr(rules, kind.upper() + '_EXTS')}
        maximum = getattr(rules, 'MAX_' + kind.upper() + '_BYTES')
    else:
        from bot.miniapp import MINIAPP_UPLOAD_DEFAULT_MAX_BYTES
        extensions, maximum = set(), MINIAPP_UPLOAD_DEFAULT_MAX_BYTES
    return {'max_bytes': maximum, 'mime_types': sorted({mimetypes.guess_type('file' + ext)[0]
        for ext in extensions} - {None})}


def configure_limits(model, slot, submitted):
    policy = asset_policy(model, slot['kind'])
    limits = submitted.get('constraints') or {}
    if not isinstance(limits, dict) or set(limits) - {'mime_types', 'max_bytes', 'min_duration', 'max_duration', 'min_side', 'max_side'}:
        fail('INVALID_TEMPLATE', 'Некорректные ограничения файла.', 400)
    configured = {}
    for key in ('max_bytes', 'min_side', 'max_side', 'min_duration', 'max_duration'):
        value = limits.get(key)
        if value is None:
            continue
        if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
            fail('INVALID_TEMPLATE', 'Ограничения должны быть положительными числами.', 400)
        if key in {'max_bytes', 'min_side', 'max_side'} and (type(value) is not int):
            fail('INVALID_TEMPLATE', 'Размер и стороны задаются целыми числами.', 400)
        if key == 'max_bytes' and value > policy['max_bytes']:
            fail('MODEL_CONSTRAINTS_INVALID', 'Размер превышает лимит загрузки этой модели.', 400)
        if slot['kind'] == 'image' and 'duration' in key:
            fail('INVALID_TEMPLATE', 'У фото нет длительности.', 400)
        configured[key] = value
    for lower, upper in (('min_duration', 'max_duration'), ('min_side', 'max_side')):
        if lower in configured and upper in configured and configured[lower] > configured[upper]:
            fail('INVALID_TEMPLATE', 'Минимум не может превышать максимум.', 400)
    mimes = limits.get('mime_types', policy['mime_types'])
    if not isinstance(mimes, list) or any(not isinstance(mime, str) or not mime.startswith(slot['kind'] + '/')
        or (policy['mime_types'] and mime not in policy['mime_types']) for mime in mimes):
        fail('MODEL_CONSTRAINTS_INVALID', 'Формат файла не поддерживается этой моделью.', 400)
    configured['mime_types'] = sorted(set(mimes))
    configured.setdefault('max_bytes', policy['max_bytes'])
    return configured


def validate_counts(source, slots):
    counts = Counter(slot['field'] for slot in slots)
    for descriptor in list_fields(source).values():
        if counts[descriptor['field']] > descriptor['maximum']:
            fail('MODEL_CONSTRAINTS_INVALID', 'Количество файлов превышает возможности модели.', 400)
    if source['type'] == 'video' and source['model'] not in {'wan_3', 'wan_3_prime', 'seedance_2_5'}:
        from bot.model_capabilities import get_video_capability
        capability = get_video_capability(source['model'])
        # These adapters promote a first frame into the reference image list.
        # Count it in that provider budget before a normalizer can truncate it.
        if (capability and capability.provider in {'seedance', 'grok'} and capability.max_reference_images
            and sum(slot['kind'] == 'image' for slot in slots) > capability.max_reference_images):
            fail('MODEL_CONSTRAINTS_INVALID', 'Первый кадр и фото вместе превышают лимит модели.', 400)


def validate_asset(slot, inspection):
    limits = slot.get('constraints') or {}
    media = inspection.get('media') or {}
    if inspection['size_bytes'] > limits.get('max_bytes', float('inf')):
        fail('ASSET_CONSTRAINTS_INVALID', 'Файл превышает размер, заданный автором.', 400)
    if limits.get('mime_types') and media.get('mime_type') not in limits['mime_types']:
        fail('ASSET_CONSTRAINTS_INVALID', 'Выберите файл разрешённого формата.', 400)
    duration = float(media.get('duration_seconds') or 0)
    sides = [int(media[key]) for key in ('width', 'height') if media.get(key)]
    if (('min_duration' in limits and duration < limits['min_duration']) or
        ('max_duration' in limits and duration > limits['max_duration']) or
        ('min_side' in limits and (not sides or min(sides) < limits['min_side'])) or
        ('max_side' in limits and (not sides or max(sides) > limits['max_side']))):
        fail('ASSET_CONSTRAINTS_INVALID', 'Размеры или длительность не соответствуют полю.', 400)
