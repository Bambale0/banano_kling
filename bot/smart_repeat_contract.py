"""Versioned input schemas layered over the existing repeat adapters.

Only public_template may cross the public API boundary. Source media, provider
field positions and the original prompt remain server-side.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import uuid
from contextvars import ContextVar
from copy import deepcopy
from typing import Any

from bot.services.media_input_utils import reference_source_identity
from bot.video_repeat_reference_contract import active_video_recipe, source_request


class SmartRepeatError(ValueError):
    def __init__(self, code: str, message: str, status: int = 409):
        super().__init__(f"{code}: {message}")
        self.code, self.message, self.status = code, message, status


def fail(code: str, message: str, status: int = 409):
    raise SmartRepeatError(code, message, status)


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":"), default=str).encode()).hexdigest()


def source_fingerprint(source: dict) -> str:
    snapshot = {key: source.get(key) for key in (
        'id', 'user_id', 'type', 'model', 'status', 'prompt', 'request_data',
        'duration', 'aspect_ratio', 'is_public_feed', 'is_profile_visible',
        'feed_repeat_reference_selection', 'feed_reference_selection', 'feed_references_visible',
    )}
    snapshot['request_data'] = source_request(source)
    return digest(snapshot)


# A capability set only after authenticated draft preflight. Client JSON can
# never opt into source overrides, even when it copies the private field names.
AUTHORIZED_REPEAT: ContextVar[dict | None] = ContextVar('authorized_smart_repeat', default=None)


def current_authorization():
    context = AUTHORIZED_REPEAT.get()
    if context and context.get('request_task') is not None and context['request_task'] is not asyncio.current_task():
        return None
    return context


def authorized_source(source: dict) -> dict:
    context = current_authorization()
    if not context or int(source.get('id') or 0) != context['source_id']:
        return source
    if source.get('_smart_repeat_authorization') is context:
        return source
    if source_fingerprint(source) != context['source_hash']:
        fail('TEMPLATE_CHANGED', 'Публикация изменилась. Откройте повтор заново.')
    return {**source, **context['overrides'], '_smart_repeat_authorization': context}


def _grant(source: dict) -> dict:
    from bot.database import generation_repeat_reference_selection_by_kind
    grant = generation_repeat_reference_selection_by_kind(source)
    # Preserve explicit legacy public selections, never infer all source media
    # from publication alone.
    if source.get('type') == 'video' and source.get('feed_repeat_reference_selection') is None:
        selection = source.get('feed_reference_selection')
        if isinstance(selection, str):
            try:
                selection = json.loads(selection)
            except ValueError:
                fail('TEMPLATE_REVIEW_REQUIRED', 'Автору нужно проверить старый рецепт.')
        if source.get('feed_references_visible') and isinstance(selection, dict):
            grant = {kind: selection.get(kind, []) for kind in ('images', 'videos')}
    return grant


def infer_template(source: dict) -> dict:
    try:
        return _infer_template(source)
    except SmartRepeatError:
        raise
    except ValueError:
        fail('TEMPLATE_REVIEW_REQUIRED', 'Автору нужно проверить соответствие референсов исходному рецепту.')


def _infer_template(source: dict) -> dict:
    if source.get('type') not in {'image', 'video'} or source.get('status') != 'completed':
        fail('TEMPLATE_REVIEW_REQUIRED', 'Нужна завершённая генерация фото или видео.')
    data = source_request(source)
    model = str(source.get('model') or '')
    slots = []
    grant = _grant(source)

    def add(kind, role, field, index, url, key=None):
        allowed = bool(url) and any(reference_source_identity(url) == reference_source_identity(value)
            for value in grant.get({'image': 'images', 'video': 'videos'}.get(kind, ''), []))
        sid = uuid.uuid5(uuid.NAMESPACE_URL, f"neuromix:repeat:{source['id']}:{field}:{index}:{role}").hex
        slots.append({'slot_id': sid, 'kind': kind, 'role': role, 'field': field, 'index': index,
            'key': key, 'source_url': url, 'allow_original': allowed,
            'label': f"{'Фото' if kind == 'image' else 'Видео' if kind == 'video' else 'Аудио'} {index + 1}",
            'hint': '', 'binding': 'fixed' if allowed else 'upload', 'required': not allowed})

    if source['type'] == 'image':
        from bot.miniapp import _source_image_references_from_task_payload
        images = _source_image_references_from_task_payload(source)
        for index, url in enumerate(images):
            add('image', 'reference', 'reference_images', index, url)
        if not images:
            from bot.smart_repeat_policy import list_fields
            if not list_fields(source).get('image', {}).get('maximum'):
                fail('TEMPLATE_REVIEW_REQUIRED', 'Автору нужно выбрать модель с поддержкой фото-референсов.')
            # Preserve the existing public image remix's personal-photo input.
            add('image', 'reference', 'reference_images', 0, None)
    elif model in {'wan_3', 'wan_3_prime'}:
        from bot.services.wan3_prime_repeat import source_recipe, source_slots
        for slot in source_slots(source_recipe(source)):
            if slot['kind'] not in {'image', 'video', 'audio'}:
                fail('TEMPLATE_REVIEW_REQUIRED', 'Для файлов и ссылок автору нужен специальный редактор.')
            add(slot['kind'], slot['role'], slot['field'], slot['index'], slot['url'], slot['key'])
    else:
        recipe = active_video_recipe(source)
        from bot.video_repeat_reference_contract import PROVIDER_ASSET_KEYS
        if any(data.get(key) for key in PROVIDER_ASSET_KEYS):
            fail('TEMPLATE_REVIEW_REQUIRED', 'Сохранённые персонажи провайдера требуют проверки автора.')
        for kind, plural, field in (('image', 'images', 'reference_images'), ('video', 'videos', 'v_reference_videos')):
            for slot in recipe[plural]:
                actual_field = (('seedance25_first_frame_url' if model == 'seedance_2_5' else 'v_image_url')
                    if slot['role'] == 'first_frame' else 'seedance25_last_frame_url'
                    if slot['role'] == 'last_frame' else field)
                add(kind, slot['role'], actual_field, slot['index'], slot['url'])
        for index, url in enumerate(recipe.get('audio') or []):
            add('audio', 'reference', 'seedance25_reference_audio_urls', index, url)
    from bot.services.media_input_utils import resolve_reference_source
    for kind, plural in (('image', 'images'), ('video', 'videos')):
        candidates = [slot['source_url'] for slot in slots if slot['kind'] == kind and slot['source_url']]
        allowed = {resolve_reference_source(value, candidates) for value in grant.get(plural, [])}
        for slot in slots:
            if slot['kind'] == kind:
                keep = slot['source_url'] is not None and slot['source_url'] in allowed
                slot.update(allow_original=keep, binding='fixed' if keep else 'upload', required=not keep)
    if data.get('seedance25_identity_transfer') or data.get('identityTransfer'):
        # Identity validation requires user-owned replacement media.
        for slot in slots:
            slot.update(binding='upload', required=True, allow_original=False)
    from bot.smart_repeat_policy import configure_limits, list_fields
    for slot in slots:
        slot.update(min_files=int(slot['required']), max_files=1,
                    constraints=configure_limits(model, slot, {}), added=False)
    return {'contract_version': 1, 'source_id': int(source['id']), 'version': 1,
        'model': model, 'type': source['type'], 'slots': slots, 'presets': [], 'variables': [],
        'addable': list_fields(source),
        'source_hash': source_fingerprint(source)}


def public_template(template: dict, *, author: bool = False) -> dict:
    fields = ('slot_id', 'kind', 'role', 'label', 'hint', 'binding', 'required',
              'min_files', 'max_files', 'constraints', 'added')
    return {**{key: deepcopy(template[key]) for key in (
        'contract_version', 'source_id', 'version', 'model', 'type', 'presets', 'variables')},
        **({'addable': deepcopy(template.get('addable', {}))} if author else {}),
        'slots': [{**{key: slot[key] for key in fields if key in slot},
                   **({'can_keep_original': slot['allow_original']} if author else {})}
                  for slot in template['slots']]}


def _text(value: Any, maximum: int, *, empty: bool = False) -> str:
    if not isinstance(value, str) or len(value.strip()) > maximum or (not empty and not value.strip()):
        fail('INVALID_TEMPLATE', 'Проверьте подписи и подсказки полей.', 400)
    return value.strip()


def configure_template(source: dict, submitted: dict, *, previous=None) -> dict:
    template = infer_template(source)
    raw = submitted.get('slots')
    expected = {slot['slot_id']: slot for slot in (previous or template)['slots']}
    mandatory_ids = {slot['slot_id'] for slot in template['slots']}
    if (not isinstance(raw, list) or len(raw) > 100
        or any(not isinstance(slot, dict) for slot in raw)
        or any(not isinstance(slot.get('slot_id'), str) for slot in raw)
        or len({slot['slot_id'] for slot in raw}) != len(raw)
        or not mandatory_ids <= {slot['slot_id'] for slot in raw}):
        fail('INVALID_SLOTS', 'Набор полей должен соответствовать исходному рецепту.', 400)
    from bot.smart_repeat_policy import configure_limits, validate_counts
    configured = []
    for slot in raw:
        if slot['slot_id'] in expected:
            base = deepcopy(expected[slot['slot_id']])
        else:
            descriptor = template['addable'].get(slot.get('kind'))
            if not descriptor or not re.fullmatch(r'[a-f0-9]{32}', slot['slot_id']):
                fail('INVALID_SLOTS', 'Модель не поддерживает добавление этого поля.', 400)
            field = descriptor['field']
            index = 1 + max((item['index'] for item in [*expected.values(), *configured] if item['kind'] == slot['kind']), default=-1)
            base = {'slot_id': slot['slot_id'], 'kind': slot['kind'], 'role': 'reference',
                'field': field, 'index': index, 'source_url': None, 'allow_original': False,
                'key': f"{slot['kind']}:{index}" if source['model'] in {'wan_3', 'wan_3_prime'} else None,
                'added': True}
        binding, required = slot.get('binding'), slot.get('required')
        if binding not in {'fixed', 'upload'} or type(required) is not bool:
            fail('INVALID_TEMPLATE', 'Неверный тип поля.', 400)
        if (binding == 'fixed' or not required) and not base['allow_original']:
            fail('ORIGINAL_NOT_PERMITTED', 'Для необязательного поля разрешите сохранение исходника автора.', 400)
        base.update(label=_text(slot.get('label'), 80), hint=_text(slot.get('hint', ''), 240, empty=True),
                    binding=binding, required=required if binding == 'upload' else False,
                    constraints=configure_limits(template['model'], base, slot))
        base.update(min_files=int(base['required']), max_files=1)
        if slot.get('max_files', 1) != 1 or slot.get('min_files', int(required)) not in (0, 1):
            fail('INVALID_TEMPLATE', 'Каждое именованное поле соответствует одному файлу.', 400)
        configured.append(base)
    # Gaps would renumber provider tags. Only a trailing added field may be removed.
    for kind in {item['kind'] for item in configured}:
        indices = sorted(item['index'] for item in configured if item['kind'] == kind)
        if indices != list(range(len(indices))):
            fail('PROMPT_BINDINGS_INVALID', 'Удалите сначала последнее дополнительное поле.', 400)
    validate_counts(source, configured)
    from bot.services.seedance_reference_binding import missing_seedance_reference_tags
    if missing_seedance_reference_tags(str(source.get('prompt') or ''),
        image_count=sum(item['kind'] == 'image' for item in configured),
        video_count=sum(item['kind'] == 'video' for item in configured),
        audio_count=sum(item['kind'] == 'audio' for item in configured)):
        fail('PROMPT_BINDINGS_INVALID', 'Поле используется в скрытом промпте.', 400)
    template['slots'] = configured
    presets = submitted.get('presets', [])
    if not isinstance(presets, list) or len(presets) > 20:
        fail('INVALID_TEMPLATE', 'Некорректные варианты персонализации.', 400)
    upload_ids = {slot['slot_id'] for slot in configured if slot['binding'] == 'upload'}
    seen = set()
    for preset in presets:
        if not isinstance(preset, dict):
            fail('INVALID_TEMPLATE', 'Некорректный вариант персонализации.', 400)
        pid = _text(preset.get('id'), 64)
        ids = preset.get('slot_ids')
        if (not re.fullmatch(r'[a-zA-Z0-9_-]+', pid) or pid in seen or not isinstance(ids, list)
            or any(not isinstance(sid, str) for sid in ids) or len(set(ids)) != len(ids) or not set(ids) <= upload_ids):
            fail('INVALID_SLOTS', 'Некорректные поля варианта.', 400)
        if any(slot['slot_id'] not in ids and slot['binding'] == 'upload' and not slot['allow_original'] for slot in configured):
            fail('ORIGINAL_NOT_PERMITTED', 'Вариант не может пропускать обязательные исходники.', 400)
        seen.add(pid)
        template['presets'].append({'id': pid, 'label': _text(preset.get('label'), 80), 'slot_ids': ids})
    variables = submitted.get('variables', [])
    placeholders = set(re.findall(r'\{\{([a-zA-Z][a-zA-Z0-9_]*)\}\}', str(source.get('prompt') or '')))
    if not isinstance(variables, list) or len(variables) > 12:
        fail('INVALID_TEMPLATE', 'Некорректные пользовательские поля.', 400)
    seen = set()
    for variable in variables:
        if not isinstance(variable, dict):
            fail('INVALID_TEMPLATE', 'Некорректное пользовательское поле.', 400)
        key = variable.get('id')
        if (key not in placeholders or key in seen or type(variable.get('required')) is not bool
            or type(variable.get('max_length')) is not int or not 1 <= variable['max_length'] <= 160):
            fail('INVALID_TEMPLATE', 'Пользовательское поле не связано с исходным промптом.', 400)
        seen.add(key)
        template['variables'].append({'id': key, 'label': _text(variable.get('label'), 80),
            'required': variable['required'], 'max_length': variable['max_length']})
    if seen != placeholders:
        fail('PROMPT_BINDINGS_INVALID', 'Настройте все переменные скрытого промпта.', 400)
    return template


def selected_slot_ids(template: dict, preset_id: str | None) -> set[str]:
    if not preset_id:
        return {slot['slot_id'] for slot in template['slots'] if slot['binding'] == 'upload'}
    preset = next((item for item in template['presets'] if item['id'] == preset_id), None)
    if preset is None:
        fail('INVALID_PRESET', 'Выберите существующий вариант.', 400)
    return set(preset['slot_ids'])


def compile_bindings(source: dict, template: dict, draft: dict) -> dict:
    from bot.smart_repeat_policy import validate_counts
    validate_counts(source, template['slots'])
    if source_fingerprint(source) != template['source_hash']:
        fail('TEMPLATE_CHANGED', 'Автор изменил публикацию. Откройте повтор заново.')
    selected = selected_slot_ids(template, draft.get('preset_id'))
    values = draft.get('slots') or {}
    if not isinstance(values, dict) or not set(values) <= selected:
        fail('INVALID_SLOTS', 'Переданы лишние поля.')
    used, references, replacements, fixed = set(), {}, {}, {'images': [], 'videos': []}
    fixed_identities = {reference_source_identity(slot['source_url']) for slot in template['slots']
        if slot['source_url'] and slot['allow_original'] and not (
            slot['slot_id'] in selected and (values.get(slot['slot_id']) or {}).get('state') == 'READY')}
    images, videos, audio = [], [], []
    # UI ordering is presentation only; compile each original field/index.
    ordered = sorted(template['slots'], key=lambda slot: (slot['kind'], slot['index'], slot['field']))
    for slot in ordered:
        sid = slot['slot_id']
        asset = values.get(sid) or {}
        replace = sid in selected and asset.get('state') == 'READY'
        if sid in selected and asset.get('state') in {'UPLOADING', 'PROCESSING', 'FAILED'}:
            fail('REFERENCES_NOT_READY', 'Дождитесь успешной загрузки каждого файла.')
        if sid in selected and slot['required'] and not replace:
            fail('REFERENCES_NOT_READY', 'Загрузите файлы во все обязательные поля.')
        if replace:
            url, aid = asset.get('url'), asset.get('asset_id')
            if not isinstance(url, str) or not url or not isinstance(aid, str) or not aid:
                fail('REFERENCES_NOT_READY', 'Файл не подтверждён сервером.')
            identity = reference_source_identity(url)
            if identity in used or identity in fixed_identities:
                fail('DUPLICATE_ASSET', 'Для каждого поля нужен отдельный файл.')
            used.add(identity)
            replacements[slot.get('key') or sid] = url
            {'image': images, 'video': videos, 'audio': audio}[slot['kind']].append(url)
            references[sid] = {'binding': 'upload', 'asset_id': aid, 'kind': slot['kind'],
                'field': slot['field'], 'index': slot['index'], 'url': url, 'state': 'READY'}
            for key in ('saved_reference_id', 'wan3_media_id'):
                if asset.get(key):
                    references[sid][key] = asset[key]
            if asset.get('sha256'):
                references[sid].update(sha256=asset['sha256'], size_bytes=asset['size_bytes'])
        else:
            if not slot['allow_original'] or not slot['source_url']:
                fail('ORIGINAL_NOT_PERMITTED', 'Для этого поля нужен собственный файл.')
            if slot['kind'] in {'image', 'video'}:
                fixed['images' if slot['kind'] == 'image' else 'videos'].append(slot['source_url'])
            references[sid] = {'binding': 'fixed', 'kind': slot['kind'], 'field': slot['field'],
                'index': slot['index'], 'url': slot['source_url'], 'state': 'READY',
                'asset_id': uuid.uuid5(uuid.NAMESPACE_URL, str(reference_source_identity(slot['source_url']))).hex}
    prompt = str(source.get('prompt') or '')
    user_values = draft.get('user_values') or {}
    if not isinstance(user_values, dict) or not set(user_values) <= {var['id'] for var in template['variables']}:
        fail('INVALID_VARIABLES', 'Проверьте пользовательские поля.', 400)
    for variable in template['variables']:
        value = _text(user_values.get(variable['id'], ''), variable['max_length'], empty=not variable['required'])
        prompt = prompt.replace('{{' + variable['id'] + '}}', value)
    if re.search(r'\{\{[a-zA-Z][a-zA-Z0-9_]*\}\}', prompt):
        fail('PROMPT_BINDINGS_INVALID', 'Автору нужно настроить переменные скрытого промпта.')
    from bot.services.remix_prompt import compose_feed_remix_prompt
    changes = _text(draft.get('prompt_changes', ''), 64 * 1024, empty=True)
    prompt = compose_feed_remix_prompt(prompt, changes)
    from bot.services.seedance_reference_binding import missing_seedance_reference_tags
    if missing_seedance_reference_tags(prompt,
        image_count=sum(slot['kind'] == 'image' for slot in template['slots']),
        video_count=sum(slot['kind'] == 'video' for slot in template['slots']),
        audio_count=sum(slot['kind'] == 'audio' for slot in template['slots'])):
        fail('PROMPT_BINDINGS_INVALID', 'Исходный промпт ссылается на отсутствующие референсы.')
    body = {'source_feed_gen_id': int(source['id']), 'reference_images': images,
        'v_reference_videos': videos, 'seedance25_reference_audio_urls': audio}
    effective = {**source, 'prompt': prompt,
        'feed_repeat_reference_selection': ({'version': 1, **fixed} if source['type'] == 'video' else fixed)}
    if any(slot.get('added') for slot in template['slots']):
        data = deepcopy(source_request(source))
        fields = {slot['field'] for slot in template['slots']}
        for field in fields:
            field_slots = sorted((slot for slot in template['slots'] if slot['field'] == field), key=lambda slot: slot['index'])
            # Additional fields are permitted only in explicit list descriptors.
            if any(slot.get('added') for slot in field_slots):
                data[field] = [references[slot['slot_id']]['url'] for slot in field_slots]
                if source['type'] == 'image':
                    data['source_reference_images'] = list(data[field])
        effective['request_data'] = data
    if template['model'] in {'wan_3', 'wan_3_prime'}:
        effective['request_data'] = {**source_request(effective), 'prompt': prompt}
        body = {'model': template['model'], 'source_feed_gen_id': int(source['id']),
                'repeat_replacements': replacements}
    data = source_request(source)
    if template['model'] == 'seedance_2_5' and (data.get('seedance25_video_editing') or data.get('seedance25_identity_transfer') or data.get('identityTransfer')):
        effective.update(feed_repeat_reference_selection=None, feed_references_visible=True, feed_reference_selection=fixed)
    return {'body': body, 'source': effective, 'snapshot': {
        'contract_version': 1, 'source_id': int(source['id']), 'template_version': template['version'],
        'model': template['model'], 'preset_id': draft.get('preset_id'), 'references': references,
        'prompt_changes': changes}}
