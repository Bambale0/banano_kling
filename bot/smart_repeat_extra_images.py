"""Draft-only optional photo inputs, separate from the author's ordered slots."""
from __future__ import annotations

import re
from copy import deepcopy

from bot.smart_repeat_policy import configure_limits, list_fields

_PREFIX = 'extra_image_'


def additional_image_limit(template: dict) -> int:
    if template['type'] != 'image':
        return 0
    maximum = list_fields(template).get('image', {}).get('maximum', 0)
    # Fixed/hidden originals occupy provider positions too.
    original_count = sum(slot['kind'] == 'image' for slot in template['slots'])
    return max(0, maximum - original_count)


def additional_image_slots(template: dict, state: dict | None = None) -> list[dict]:
    if template['type'] != 'image':
        return []
    indices = set(range(additional_image_limit(template)))
    # A lowered runtime limit must not hide already-attached files or make them
    # impossible to remove. Only persisted IDs are eligible for this exception.
    for sid in (state or {}).get('slots', {}):
        if re.fullmatch(r'extra_image_(0|[1-9][0-9]*)', sid):
            indices.add(int(sid[len(_PREFIX):]))
    constraints = configure_limits(template['model'], {'kind': 'image'}, {})
    return [{'slot_id': f'{_PREFIX}{index}', 'kind': 'image', 'role': 'reference',
        'field': 'reference_images', 'index': index, 'key': None,
        'source_url': None, 'allow_original': False, 'binding': 'upload',
        'label': f'Дополнительное фото {index + 1}', 'hint': '', 'required': False,
        'min_files': 0, 'max_files': 1, 'constraints': deepcopy(constraints),
        'added': True, 'additional': True} for index in sorted(indices)]


def with_additional_images(template: dict, state: dict) -> dict:
    """Append only attached extras; missing extras never become required inputs.

    Compact extra positions after removal, never the original @ImageN positions.
    UPLOADING/FAILED extras remain in the compiled schema so the normal readiness
    guard rejects quoting/launch instead of silently ignoring the user's file.
    """
    values = state.get('slots') or {}
    attached = [slot for slot in additional_image_slots(template, state) if slot['slot_id'] in values]
    if not attached:
        return template
    start = 1 + max((slot['index'] for slot in template['slots'] if slot['kind'] == 'image'), default=-1)
    return {**template, 'slots': [*template['slots'], *[
        {**slot, 'index': start + offset, 'required': True, 'min_files': 1}
        for offset, slot in enumerate(attached)]]}
