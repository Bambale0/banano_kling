"""Native photo repeat preflight; never downgrade an authored smart recipe."""
from __future__ import annotations

import math
import re

from bot.smart_repeat_contract import (
    compile_bindings,
    digest,
    fail,
    infer_template,
    source_fingerprint,
)

UNSUPPORTED = (
    'Для этой публикации заданы отдельные поля, которые нельзя безопасно '
    'заполнить в обычном чате. Генерация не запущена, бананы не списаны.'
)


def current_price(model: str, quality: str, telegram_id: int | None = None) -> float:
    # Same mutable model/quality pricing source as the smart-repeat quote route.
    from bot.miniapp import _resolve_image_unit_cost
    value = float(_resolve_image_unit_cost(model, quality))
    if not math.isfinite(value) or value < 0:
        fail('PRICE_UNAVAILABLE', 'Не удалось проверить актуальную стоимость. Повторите позже.')
    from bot.config import config
    return 0 if telegram_id is not None and config.is_admin(telegram_id) else value


def quote_signature(data: dict, price: float) -> str:
    return digest({key: data.get(key) for key in (
        'repeat_source_task_id', 'img_service', 'img_ratio', 'img_quality',
        'repeat_native_template_marker', 'repeat_prompt', 'reference_images',
        'repeat_private_reference_fingerprint',
    )} | {'cost': price})


async def load_contract(task, viewer_telegram_id: int | None = None):
    """Accept only templates whose positional contract the native FSM supports.

    Labels/hints may be customized. Variables, added slots, changed bindings or
    narrowed constraints need a dedicated field editor and cannot fall through.
    No template is created here and no rollout/publication settings are changed.
    """
    import json

    from bot import database
    from bot import db as db_backend

    source = await database.get_generation_task_payload(task.id)
    if not source or source.get('type') != 'image':
        fail('SOURCE_UNAVAILABLE', 'Исходная работа больше недоступна.')
    if viewer_telegram_id is not None:
        viewer = await database.get_or_create_user(viewer_telegram_id)
        if source['user_id'] != viewer.id and (source.get('status') != 'completed' or
                not (source.get('is_public_feed') or source.get('is_profile_visible'))):
            fail('SOURCE_UNAVAILABLE', 'Автор снял работу с публикации. Повтор недоступен.')
    async with db_backend.connect() as db:
        row = await (await db.execute(
            'SELECT schema_json FROM smart_repeat_templates WHERE source_id = ? '
            'ORDER BY version DESC LIMIT 1', (task.id,),
        )).fetchone()
    if not row:
        return {'source': source, 'template': None}
    template = json.loads(row[0])
    if not source or template.get('source_hash') != source_fingerprint(source):
        fail('TEMPLATE_CHANGED', 'Автор изменил публикацию. Откройте повтор заново.')
    inferred = infer_template(source)
    keys = ('slot_id', 'kind', 'role', 'field', 'index', 'key', 'source_url',
            'allow_original', 'binding', 'required', 'min_files', 'max_files', 'constraints', 'added')

    def shape(value):
        return sorted(({key: slot.get(key) for key in keys} for slot in value['slots']),
                      key=lambda slot: slot['slot_id'])

    if template.get('variables') or shape(template) != shape(inferred):
        fail('NATIVE_TEMPLATE_UNSUPPORTED', UNSUPPORTED)
    if any(slot['kind'] != 'image' or slot['field'] != 'reference_images' for slot in template['slots']):
        fail('NATIVE_TEMPLATE_UNSUPPORTED', UNSUPPORTED)
    return {'source': source, 'template': template}


def marker(contract) -> str | None:
    if not contract:
        return None
    template = contract['template']
    return digest({'source_hash': source_fingerprint(contract['source']),
                   'version': template['version'] if template else 0})


def public_labels(contract) -> list[str]:
    if not contract or not contract.get('template'):
        return []
    return [str(slot['label']) + (' — ' + str(slot['hint']) if slot.get('hint') else '') for slot in sorted(contract['template']['slots'], key=lambda slot: slot['index'])
            if slot['binding'] == 'upload']


async def validate_inputs(contract, references: list[str], prompt: str) -> None:
    if re.search(r'\{\{[a-zA-Z][a-zA-Z0-9_]*\}\}', prompt):
        fail('NATIVE_TEMPLATE_UNSUPPORTED', UNSUPPORTED)
    if not contract or not contract.get("template"):
        return
    from bot.services.media_input_utils import (
        reference_source_identity,
        resolve_local_upload_path,
    )
    from bot.smart_repeat_media import inspect_asset
    from bot.smart_repeat_policy import validate_asset

    template, source = contract['template'], contract['source']
    values = {}
    for slot in template['slots']:
        index = slot['index']
        if slot['binding'] == 'upload' and index < len(references):
            url = references[index]
            values[slot['slot_id']] = {'state': 'READY', 'url': url,
                                      'asset_id': digest(reference_source_identity(url))}
    compiled = compile_bindings(source, template, {'slots': values})
    ordered = sorted(compiled['snapshot']['references'].values(), key=lambda item: item['index'])
    if [reference_source_identity(item['url']) for item in ordered] != [
        reference_source_identity(url) for url in references[:len(ordered)]
    ]:
        fail('REFERENCES_NOT_READY', 'Порядок фото не соответствует исходной работе. Откройте повтор заново.')
    for slot in template['slots']:
        asset = values.get(slot['slot_id'])
        if not asset:
            continue
        path = resolve_local_upload_path(asset['url'])
        if not path:
            fail('REFERENCES_NOT_READY', 'Отправьте фото заново в чат, чтобы проверить файл перед запуском.')
        inspection = await inspect_asset(path, 'image')
        validate_asset(slot, inspection)
