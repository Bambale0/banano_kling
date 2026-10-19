"""Durable template versions, fenced uploads and launch snapshots for repeats."""
from __future__ import annotations

import json
import logging
import math
import uuid
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

from bot import db as db_backend
from bot.smart_repeat_contract import (
    SmartRepeatError,
    compile_bindings,
    configure_template,
    current_authorization,
    fail,
    infer_template,
    public_template,
    selected_slot_ids,
    source_fingerprint,
)

logger = logging.getLogger(__name__)

TABLES = (
    """CREATE TABLE IF NOT EXISTS smart_repeat_templates (
        source_id BIGINT NOT NULL, version INTEGER NOT NULL, owner_id BIGINT NOT NULL,
        schema_json TEXT NOT NULL, source_hash TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (source_id, version))""",
    """CREATE TABLE IF NOT EXISTS smart_repeat_drafts (
        id TEXT PRIMARY KEY, user_id BIGINT NOT NULL, telegram_id BIGINT NOT NULL,
        source_id BIGINT NOT NULL, template_version INTEGER NOT NULL,
        revision INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'draft',
        state_json TEXT NOT NULL DEFAULT '{}', quote_json TEXT, snapshot_json TEXT,
        result_json TEXT, task_id TEXT, accepted_task_json TEXT, charge_amount REAL NOT NULL DEFAULT 0,
        refund_amount REAL NOT NULL DEFAULT 0, provider_accepted INTEGER NOT NULL DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""",
    "CREATE INDEX IF NOT EXISTS idx_smart_repeat_drafts_actor ON smart_repeat_drafts(user_id, source_id, created_at)",
)


async def ensure_schema(db):
    from bot.services.wan3_prime_schema import execute_wan_ddl
    for statement in TABLES:
        await execute_wan_ddl(db, statement)
    # The shared retention lock is required for image/video drafts as well as
    # Wan uploads, including clean deployments before the Wan runner starts.
    await execute_wan_ddl(db, 'CREATE TABLE IF NOT EXISTS wan3_prime_storage_lock (id INTEGER PRIMARY KEY)')
    await db.execute('INSERT INTO wan3_prime_storage_lock (id) VALUES (1) ON CONFLICT (id) DO NOTHING')


async def rollout_enabled(telegram_id=None):
    from bot.database import get_bot_setting
    raw = await get_bot_setting('smart_repeat_rollout', '{}')
    try:
        settings = json.loads(raw or '{}')
        return isinstance(settings, dict) and (settings.get('enabled') is True or
            (telegram_id is not None and telegram_id in settings.get('telegram_ids', [])))
    except (ValueError, TypeError):
        return False


def event(name, *, user_id, source_id, **fields):
    logger.info('smart_repeat %s', json.dumps({'event': name, 'user_id': user_id,
        'repeat_id': source_id, **fields}, sort_keys=True))


async def _lock_user(db, user_id):
    cursor = await db.execute('UPDATE users SET updated_at = updated_at WHERE id = ?', (user_id,))
    if cursor.rowcount != 1:
        fail('AUTH_REQUIRED', 'Откройте Mini App заново.', 401)


async def _current_source(db, source_id):
    row = await (await db.execute('SELECT * FROM generation_tasks WHERE id = ?' +
        (' FOR SHARE' if db_backend.is_postgres() else ''), (source_id,))).fetchone()
    if not row:
        fail('SOURCE_UNAVAILABLE', 'Публикация больше недоступна.', 404)
    source = dict(row)
    raw = source.get('request_data')
    source['request_data'] = json.loads(raw) if isinstance(raw, str) and raw else (raw or {})
    if (source.get('status') != 'completed' or
        not (source.get('is_public_feed') or source.get('is_profile_visible'))):
        fail('SOURCE_UNAVAILABLE', 'Публикация больше недоступна.', 404)
    return source


async def get_template(source, *, author=False):
    async with db_backend.connect() as db:
        db.row_factory = db_backend.Row
        row = await (await db.execute('SELECT * FROM smart_repeat_templates WHERE source_id = ? '
            'ORDER BY version DESC LIMIT 1', (source['id'],))).fetchone()
        if row:
            template = json.loads(row['schema_json'])
            if template['source_hash'] == source_fingerprint(source):
                return template
            if not author:
                fail('TEMPLATE_REVIEW_REQUIRED', 'Автору нужно обновить поля изменившейся публикации.')
            template = infer_template(source)
            template['version'] = int(row['version']) + 1
            return template
        template = infer_template(source)
        await db.execute('INSERT INTO smart_repeat_templates '
            '(source_id, version, owner_id, schema_json, source_hash) VALUES (?, 1, ?, ?, ?) '
            'ON CONFLICT(source_id, version) DO NOTHING',
            (source['id'], source['user_id'], json.dumps(template), template['source_hash']))
        await db.commit()
        # A concurrent first reader can only create the same deterministic v1.
        return template


async def save_template(user, source, submitted):
    if source['user_id'] != user.id:
        fail('FORBIDDEN', 'Настраивать повтор может только автор публикации.', 403)
    async with db_backend.connect() as db:
        db.row_factory = db_backend.Row
        await _lock_user(db, user.id)
        current = await _current_source(db, source['id'])
        if source_fingerprint(current) != source_fingerprint(source):
            fail('TEMPLATE_CHANGED', 'Публикация изменилась. Обновите редактор.')
        previous = await (await db.execute('SELECT version, schema_json FROM smart_repeat_templates '
            'WHERE source_id = ? ORDER BY version DESC LIMIT 1', (source['id'],))).fetchone()
        prior = json.loads(previous['schema_json']) if previous else None
        if prior and prior['source_hash'] != source_fingerprint(source):
            prior = None
        if previous and submitted.get('version') != previous['version'] + int(prior is None):
            fail('TEMPLATE_CHANGED', 'Версия редактора устарела. Откройте его заново.')
        template = configure_template(source, submitted, previous=prior)
        template['version'] = int(previous['version']) + 1 if previous else 1
        await db.execute('INSERT INTO smart_repeat_templates '
            '(source_id, version, owner_id, schema_json, source_hash) VALUES (?, ?, ?, ?, ?)',
            (source['id'], template['version'], user.id, json.dumps(template), template['source_hash']))
        await db.commit()
    event('template_saved', user_id=user.id, source_id=source['id'], template_version=template['version'])
    return template


def _decode(row):
    if row is None:
        fail('DRAFT_NOT_FOUND', 'Черновик повтора не найден.', 404)
    result = dict(row)
    for field, key in (('state_json', 'state'), ('quote_json', 'quote'),
                       ('snapshot_json', 'snapshot'), ('result_json', 'result'), ('accepted_task_json', 'accepted_task')):
        result[key] = json.loads(result.pop(field) or 'null')
    return result


async def load_draft(user_id, draft_id):
    async with db_backend.connect() as db:
        db.row_factory = db_backend.Row
        return _decode(await (await db.execute('SELECT * FROM smart_repeat_drafts '
            'WHERE id = ? AND user_id = ?', (draft_id, user_id))).fetchone())


async def latest_draft(user_id, source_id):
    async with db_backend.connect() as db:
        db.row_factory = db_backend.Row
        row = await (await db.execute('SELECT * FROM smart_repeat_drafts WHERE user_id = ? AND source_id = ? '
            'ORDER BY created_at DESC, id DESC LIMIT 1', (user_id, source_id))).fetchone()
    return _decode(row) if row else None


async def open_draft(user, source, template, *, new=False):
    async with db_backend.connect() as db:
        db.row_factory = db_backend.Row
        await _lock_user(db, user.id)
        row = await (await db.execute('SELECT * FROM smart_repeat_drafts '
            'WHERE user_id = ? AND source_id = ? ORDER BY created_at DESC, id DESC LIMIT 1',
            (user.id, source['id']))).fetchone()
        current = _decode(row) if row else None
        if current and current['status'] != 'draft':
            task = await (await db.execute('SELECT status FROM generation_tasks '
                'WHERE task_id = ? AND user_id = ?', (current['task_id'], user.id))).fetchone() if current['task_id'] else None
            if not new or (current['status'] != 'rejected' and
                           (not task or task['status'] in {'pending', 'processing'})):
                await db.commit()
                return current
        if current and not new and current['template_version'] == template['version']:
            await db.commit()
            return current
        draft_id = uuid.uuid4().hex
        await db.execute('INSERT INTO smart_repeat_drafts '
            '(id, user_id, telegram_id, source_id, template_version, state_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)',
            (draft_id, user.id, user.telegram_id, source['id'], template['version'],
             json.dumps({'slots': {}, 'preset_id': None, 'user_values': {}}),
             datetime.now(UTC).replace(tzinfo=None).isoformat(' ', timespec='microseconds')))
        await db.commit()
    event('repeat_opened', user_id=user.id, source_id=source['id'], draft_id=draft_id,
          template_version=template['version'])
    return await load_draft(user.id, draft_id)


def public_draft(draft, template):
    state = draft['state'] or {}
    return {'draft_id': draft['id'], 'revision': draft['revision'], 'status': draft['status'],
        'template': public_template(template), 'preset_id': state.get('preset_id'),
        'user_values': state.get('user_values', {}), 'prompt_changes': state.get('prompt_changes', ''),
        'slots': {sid: {key: value[key] for key in ('state', 'asset_id', 'url', 'upload_token', 'error', 'saved_reference_id', 'filename') if key in value}
                  for sid, value in state.get('slots', {}).items()},
        'quote': ({key: draft['quote'][key] for key in ('cost', 'quote_id')} if draft['quote'] else None),
        'task_id': draft.get('task_id'), 'result': draft.get('result')}


async def validate_owned_asset(user, kind, url, *, existing=None):
    from bot.services.media_input_utils import (
        reference_source_identity,
        resolve_local_upload_path,
    )
    if not isinstance(url, str) or not url or kind not in {'image', 'video', 'audio'}:
        fail('INVALID_ASSET', 'Некорректный файл.', 400)
    identity = reference_source_identity(url)
    async with db_backend.connect() as db:
        rows = await (await db.execute('SELECT id, file_url, original_filename FROM saved_references WHERE user_id = ? AND kind = ?',
            (user.id, kind))).fetchall()
    saved = next((row for row in rows if reference_source_identity(row[1]) == identity), None)
    owned = saved is not None
    if existing and existing.get('asset_id') and existing.get('sha256') and reference_source_identity(existing.get('url', '')) == identity:
        # A recent-upload shortcut may be pruned without revoking ownership of
        # an asset already attached to this user's durable draft.
        owned = True
    if not owned:
        try:
            async with db_backend.connect() as db:
                rows = await (await db.execute('SELECT public_url FROM wan3_prime_media WHERE user_id = ? AND kind = ?',
                    (user.id, kind))).fetchall()
            owned = any(reference_source_identity(row[0]) == identity for row in rows)
        except db_backend.OperationalError:
            owned = False
    if not owned:
        fail('ASSET_NOT_OWNED', 'Загрузите собственный файл для этого поля.', 403)
    path = resolve_local_upload_path(url)
    if not path or not Path(path).is_file() or Path(path).stat().st_size <= 0:
        fail('REFERENCES_NOT_READY', 'Файл ещё не сохранён или больше недоступен.')
    from bot.smart_repeat_media import inspect_asset
    inspection = await inspect_asset(path, kind)
    if existing and inspection['sha256'] != existing.get('sha256'):
        fail('REFERENCES_NOT_READY', 'Содержимое файла изменилось. Загрузите его заново.')
    if saved is not None:
        inspection.update(saved_reference_id=str(saved[0]), filename=saved[2])
    elif existing:
        inspection.update({key: existing[key] for key in ('saved_reference_id', 'filename') if key in existing})
    return inspection


async def mutate_draft(user, draft_id, template, operation, *, slot_id=None, upload_token=None, url=None,
                       preset_id=None, user_values=None, saved_reference_id=None, prompt_changes=None):
    # READY is accepted only for the current upload lease and a persisted owned
    # asset. Slow validation happens outside the row lock, then the lease fences it.
    definition = next((slot for slot in template['slots'] if slot['slot_id'] == slot_id), None)
    selected_reference = None
    if operation == 'ready':
        if not definition:
            fail('INVALID_SLOTS', 'Неизвестное поле.', 400)
        if saved_reference_id is not None:
            if (type(saved_reference_id) not in (str, int)
                or not str(saved_reference_id).isascii() or not str(saved_reference_id).isdigit()
                or len(str(saved_reference_id)) > 19 or not 0 < int(saved_reference_id) <= 2**63 - 1):
                fail('INVALID_ASSET', 'Некорректный сохранённый файл.', 400)
            from bot.database import get_saved_reference_by_id
            selected_reference = await get_saved_reference_by_id(user.telegram_id, int(saved_reference_id))
            if selected_reference is None or selected_reference.kind != definition['kind']:
                fail('ASSET_NOT_OWNED', 'Выберите собственный файл подходящего типа.', 403)
            # The ID is authoritative. Never trust a client URL or filename for it.
            url = selected_reference.file_url
        inspection = await validate_owned_asset(user, definition['kind'], url)
    async with db_backend.connect() as db:
        db.row_factory = db_backend.Row
        if operation == 'ready':
            from bot.services.wan3_prime_storage_policy import lock_storage
            await lock_storage(db)
            # Retention uses this same lock. Recheck after acquiring it so an
            # asset cannot disappear between validation and durable attachment.
            inspection = await validate_owned_asset(user, definition['kind'], url)
            from bot.smart_repeat_policy import validate_asset
            validate_asset(definition, inspection)
            if selected_reference is not None:
                inspection.update(saved_reference_id=str(selected_reference.id),
                                  filename=selected_reference.original_filename)
        locked = await db.execute('UPDATE smart_repeat_drafts SET revision = revision '
            "WHERE id = ? AND user_id = ? AND status = 'draft'", (draft_id, user.id))
        if locked.rowcount != 1:
            fail('DRAFT_LOCKED', 'Для этого повтора уже создана операция.')
        draft = _decode(await (await db.execute('SELECT * FROM smart_repeat_drafts WHERE id = ?', (draft_id,))).fetchone())
        if draft['template_version'] != template['version']:
            fail('TEMPLATE_CHANGED', 'Автор обновил поля. Откройте повтор заново.')
        state = deepcopy(draft['state'])
        if operation in {'begin', 'processing', 'ready', 'remove', 'failed'}:
            if not definition or slot_id not in selected_slot_ids(template, state.get('preset_id')):
                fail('INVALID_SLOTS', 'Это поле недоступно в выбранном варианте.', 400)
            previous = state['slots'].get(slot_id, {})
            if operation == 'begin':
                state['slots'][slot_id] = {'state': 'UPLOADING', 'upload_token': uuid.uuid4().hex}
            elif operation == 'remove':
                state['slots'].pop(slot_id, None)
            else:
                if not upload_token or upload_token != previous.get('upload_token') or previous.get('state') not in {'UPLOADING', 'PROCESSING'}:
                    fail('UPLOAD_SUPERSEDED', 'Эта загрузка уже заменена или отменена.')
                state['slots'][slot_id] = {**previous, 'state': operation.upper() if operation != 'processing' else 'PROCESSING'}
                if operation == 'ready':
                    state['slots'][slot_id].update(asset_id=uuid.uuid4().hex, url=url, **inspection)
        elif operation == 'preset':
            selected = selected_slot_ids(template, preset_id)
            state.update(preset_id=preset_id, slots={sid: value for sid, value in state['slots'].items() if sid in selected})
        elif operation == 'changes':
            if not isinstance(prompt_changes, str) or len(prompt_changes) > 64 * 1024:
                fail('INVALID_CHANGES', 'Проверьте текст изменений.', 400)
            state['prompt_changes'] = prompt_changes.strip()
        elif operation == 'values':
            if not isinstance(user_values, dict) or not set(user_values) <= {var['id'] for var in template['variables']}:
                fail('INVALID_VARIABLES', 'Некорректные поля персонализации.', 400)
            if any(not isinstance(value, str) or len(value) > next(var['max_length'] for var in template['variables'] if var['id'] == key)
                   for key, value in user_values.items()):
                fail('INVALID_VARIABLES', 'Проверьте длину пользовательских полей.', 400)
            state['user_values'] = user_values
        else:
            fail('INVALID_OPERATION', 'Неизвестная операция.', 400)
        await db.execute('UPDATE smart_repeat_drafts SET state_json = ?, quote_json = NULL, '
            'revision = revision + 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?', (json.dumps(state), draft_id))
        await db.commit()
    event({'begin': 'slot_upload_started', 'ready': 'slot_ready'}.get(operation, 'draft_changed'),
          user_id=user.id, source_id=template['source_id'], template_version=template['version'],
          draft_id=draft_id, slot_id=slot_id, model=template['model'],
          asset_id=(state.get('slots', {}).get(slot_id) or {}).get('asset_id'))
    return await load_draft(user.id, draft_id)


async def validate_inputs(user, source, template, draft):
    compiled = compile_bindings(source, template, draft['state'])
    from bot.services.media_input_utils import missing_local_upload_sources
    for sid, ref in compiled['snapshot']['references'].items():
        if ref['binding'] == 'upload':
            inspection = await validate_owned_asset(user, ref['kind'], ref['url'], existing=draft['state']['slots'][sid])
            from bot.smart_repeat_policy import validate_asset
            validate_asset(next(slot for slot in template['slots'] if slot['slot_id'] == sid), inspection)
        elif missing_local_upload_sources([ref['url']]):
            fail('REFERENCES_NOT_READY', 'Исходник автора больше недоступен.')
    return compiled


async def refresh_draft_media(user, draft):
    if draft['status'] != 'draft':
        return await recover_draft(user, draft)
    state = deepcopy(draft['state'])
    changed = False
    template = await _template_for_draft(draft)
    for sid, asset in state.get('slots', {}).items():
        if asset.get('state') != 'READY':
            continue
        try:
            kind = next(slot['kind'] for slot in template['slots'] if slot['slot_id'] == sid)
            await validate_owned_asset(user, kind, asset.get('url'), existing=asset)
        except (SmartRepeatError, OSError):
            asset.update(state='FAILED', error='Файл больше недоступен. Загрузите его заново.')
            changed = True
    if changed:
        async with db_backend.connect() as db:
            await db.execute('UPDATE smart_repeat_drafts SET state_json = ?, quote_json = NULL, '
                "revision = revision + 1 WHERE id = ? AND user_id = ? AND status = 'draft' AND revision = ?",
                (json.dumps(state), draft['id'], user.id, draft['revision']))
            await db.commit()
        return await load_draft(user.id, draft['id'])
    return draft


async def _template_for_draft(draft):
    async with db_backend.connect() as db:
        row = await (await db.execute('SELECT schema_json FROM smart_repeat_templates WHERE source_id = ? AND version = ?',
            (draft['source_id'], draft['template_version']))).fetchone()
    if not row:
        fail('TEMPLATE_CHANGED', 'Версия шаблона недоступна.')
    return json.loads(row[0])


async def recover_draft(user, draft):
    """Persist known provider acceptance without ever resubmitting a generation."""
    if not draft.get('task_id'):
        return draft
    from bot import database
    task = await database.get_task_by_id(draft['task_id'])
    if task and task.user_id != user.id:
        fail('OPERATION_CONFLICT', 'Не удалось подтвердить владельца задачи.')
    if not task and draft['provider_accepted'] and draft.get('accepted_task'):
        record = draft['accepted_task']
        if record['type'] == 'image' and record.get('reserved_task_id'):
            from bot.partner_policy import generation_partner_snapshot
            metadata = generation_partner_snapshot(record['request_data'], accepted=True)
            metadata['task_id_aliases'] = [record['reserved_task_id'], record['task_id']]
            async with db_backend.connect() as db:
                await db.execute('UPDATE generation_tasks SET task_id = ?, request_data = ? '
                    "WHERE task_id = ? AND user_id = ? AND status IN ('pending', 'processing')",
                    (record['task_id'], json.dumps(metadata), record['reserved_task_id'], user.id))
                await db.commit()
        else:
            await database.add_generation_task(**record)
        task = await database.get_task_by_id(draft['task_id'])
    wan_intent = None
    if (draft.get('snapshot') or {}).get('model') in {'wan_3', 'wan_3_prime'}:
        async with db_backend.connect() as db:
            wan_intent = await (await db.execute('SELECT internal_task_id FROM wan3_prime_intents '
                'WHERE user_id = ? AND idempotency_key = ?', (user.id, draft['id']))).fetchone()
    if not task or (not draft['provider_accepted'] and task.status != 'failed' and not wan_intent):
        return draft
    result = {'ok': True, 'task_id': task.task_id,
              'status': 'done' if task.status == 'completed' else 'queued',
              'prompt_hidden': True, 'source_feed_gen_id': draft['source_id']}
    if task.status == 'failed':
        result.update(ok=False, code='PREVIOUS_TASK_FAILED', error='Предыдущая задача завершилась ошибкой. Создайте новый повтор явно.')
    async with db_backend.connect() as db:
        status = ('rejected' if task.status == 'failed' and not draft['provider_accepted']
                  and draft['charge_amount'] == draft['refund_amount'] else 'launched')
        await db.execute('UPDATE smart_repeat_drafts SET status = ?, result_json = ? WHERE id = ? AND user_id = ?',
            (status, json.dumps({'status': 409 if task.status == 'failed' else 200, 'body': result}), draft['id'], user.id))
        await db.commit()
    return await load_draft(user.id, draft['id'])


async def save_quote(user, draft, template, quote):
    amount = quote.get('cost')
    if not isinstance(amount, (int, float)) or not math.isfinite(amount) or amount < 0:
        fail('PRICE_UNAVAILABLE', 'Сервер не подтвердил стоимость.')
    frozen = {**quote, 'revision': draft['revision'], 'template_version': template['version'],
              'quote_id': uuid.uuid4().hex, 'source_hash': template['source_hash']}
    async with db_backend.connect() as db:
        changed = await db.execute('UPDATE smart_repeat_drafts SET quote_json = ?, updated_at = CURRENT_TIMESTAMP '
            "WHERE id = ? AND user_id = ? AND revision = ? AND status = 'draft'",
            (json.dumps(frozen), draft['id'], user.id, draft['revision']))
        if changed.rowcount != 1:
            fail('DRAFT_CHANGED', 'Файлы изменились во время расчёта. Рассчитайте стоимость заново.')
        await db.commit()
    return frozen


async def claim_launch(user, source, template, draft, quote_id, compiled):
    quote = draft.get('quote')
    if not quote or not quote_id or quote['quote_id'] != quote_id or quote['revision'] != draft['revision']:
        fail('PRICE_NOT_CONFIRMED', 'Подтвердите текущую стоимость перед запуском.')
    snapshot = {**compiled['snapshot'], 'draft_id': draft['id'], 'revision': draft['revision'],
        'quote': quote, 'body': compiled['body'], 'source_hash': template['source_hash']}
    async with db_backend.connect() as db:
        db.row_factory = db_backend.Row
        await _lock_user(db, user.id)
        current = await _current_source(db, source['id'])
        if source_fingerprint(current) != template['source_hash']:
            fail('TEMPLATE_CHANGED', 'Публикация изменилась до запуска.')
        latest = await (await db.execute('SELECT version FROM smart_repeat_templates '
            'WHERE source_id = ? ORDER BY version DESC LIMIT 1', (source['id'],))).fetchone()
        if not latest or latest[0] != template['version']:
            fail('TEMPLATE_CHANGED', 'Автор обновил шаблон до запуска.')
        changed = await db.execute("UPDATE smart_repeat_drafts SET status = 'launching', snapshot_json = ?, "
            'updated_at = CURRENT_TIMESTAMP WHERE id = ? AND user_id = ? AND revision = ? '
            "AND status = 'draft' AND quote_json = ?", (json.dumps(snapshot), draft['id'], user.id,
            draft['revision'], json.dumps(quote)))
        if changed.rowcount != 1:
            fail('OPERATION_ALREADY_CREATED', 'Операция уже создана. Проверьте историю.')
        await db.commit()
    event('generation_requested', user_id=user.id, source_id=source['id'],
          draft_id=draft['id'], template_version=template['version'], model=template['model'])
    return snapshot


async def finish_launch(user, draft_id, response):
    result = json.loads(response.text) if response.text else {}
    task_id = result.get('task_id') or result.get('internal_task_id')
    async with db_backend.connect() as db:
        db.row_factory = db_backend.Row
        row = await (await db.execute('SELECT * FROM smart_repeat_drafts WHERE id = ? AND user_id = ?',
            (draft_id, user.id))).fetchone()
        local = await (await db.execute('SELECT status FROM generation_tasks WHERE task_id = ? AND user_id = ?',
            (row['task_id'], user.id))).fetchone() if row['task_id'] else None
        rejected = (not row['provider_accepted'] and response.status >= 400 and
            (400 <= response.status < 500 or (local and local['status'] == 'failed')) and
            row['charge_amount'] == row['refund_amount'])
        await db.execute('UPDATE smart_repeat_drafts SET status = ?, result_json = ?, '
            'task_id = COALESCE(?, task_id), updated_at = CURRENT_TIMESTAMP WHERE id = ? AND user_id = ?',
            ('rejected' if rejected else 'launched' if response.status < 400 and task_id else 'unknown',
             json.dumps({'status': response.status, 'body': result}), task_id, draft_id, user.id))
        await db.commit()
    return result


async def repeat_finance(telegram_id, amount, *, refund=False):
    """One draft reservation and one synchronous refund; no pre-debit credit."""
    context = current_authorization()
    if not context or telegram_id != context['telegram_id']:
        fail('OPERATION_CONTEXT_INVALID', 'Не удалось подтвердить операцию.')
    if not isinstance(amount, (int, float)) or not math.isfinite(amount) or amount <= 0:
        return False
    async with db_backend.connect() as db:
        db.row_factory = db_backend.Row
        await _lock_user(db, context['user_id'])
        row = await (await db.execute('SELECT * FROM smart_repeat_drafts WHERE id = ? AND user_id = ?',
            (context['draft_id'], context['user_id']))).fetchone()
        if not row or (not refund and row['status'] != 'launching'):
            fail('OPERATION_CONTEXT_INVALID', 'Не удалось подтвердить операцию.')
        if refund:
            if row['charge_amount'] != amount or row['refund_amount'] or row['provider_accepted']:
                await db.commit()
                return False
            await db.execute('UPDATE users SET credits = credits + ? WHERE id = ?', (amount, context['user_id']))
            await db.execute('UPDATE smart_repeat_drafts SET refund_amount = ? WHERE id = ?', (amount, context['draft_id']))
        else:
            quote = json.loads(row['quote_json'])
            if row['charge_amount'] or not math.isclose(float(quote['cost']), float(amount), rel_tol=0, abs_tol=0.00001):
                fail('PRICE_CHANGED', 'Стоимость изменилась. Обновите расчёт.')
            current = await _current_source(db, context['source_id'])
            if source_fingerprint(current) != context['source_hash']:
                fail('TEMPLATE_CHANGED', 'Автор изменил публикацию до списания.')
            changed = await db.execute('UPDATE users SET credits = credits - ?, updated_at = CURRENT_TIMESTAMP '
                'WHERE id = ? AND telegram_id = ? AND credits >= ?',
                (amount, context['user_id'], telegram_id, amount))
            if changed.rowcount != 1:
                await db.rollback()
                return False
            await db.execute('UPDATE smart_repeat_drafts SET charge_amount = ? WHERE id = ?', (amount, context['draft_id']))
        await db.commit()
    return True


async def record_accepted(task_id, task_record):
    context = current_authorization()
    if not context:
        return
    async with db_backend.connect() as db:
        await db.execute('UPDATE smart_repeat_drafts SET provider_accepted = ?, task_id = ?, accepted_task_json = ?, '
            'updated_at = CURRENT_TIMESTAMP WHERE id = ? AND user_id = ?',
            (int(task_record.get('provider_accepted', False)), task_id, json.dumps(task_record), context['draft_id'], context['user_id']))
        await db.commit()
    event('generation_created', user_id=context['user_id'], source_id=context['source_id'],
          draft_id=context['draft_id'], task_id=task_id, template_version=context['template_version'],
          model=task_record.get('model'), provider_accepted=bool(task_record.get('provider_accepted')))


async def record_provider_ack(task_id):
    """Save real acceptance before subsequent task/notification writes can fail."""
    context = current_authorization()
    if not context:
        return
    async with db_backend.connect() as db:
        db.row_factory = db_backend.Row
        row = await (await db.execute('SELECT accepted_task_json FROM smart_repeat_drafts '
            'WHERE id = ? AND user_id = ?', (context['draft_id'], context['user_id']))).fetchone()
        record = json.loads(row[0]) if row and row[0] else None
        if record:
            if record['task_id'] != task_id:
                record['reserved_task_id'] = record['task_id']
            record.update(task_id=task_id, provider_accepted=True)
        await db.execute('UPDATE smart_repeat_drafts SET provider_accepted = 1, task_id = ?, '
            'accepted_task_json = ? WHERE id = ? AND user_id = ?',
            (task_id, json.dumps(record) if record else None, context['draft_id'], context['user_id']))
        await db.commit()


async def migrate_public_templates(*, after_id, limit):
    """Add versions only for unambiguous sources; report reviews without media writes."""
    from bot.database import get_generation_task_payload
    from bot.smart_repeat_contract import SmartRepeatError
    async with db_backend.connect() as db:
        rows = await (await db.execute("SELECT id FROM generation_tasks WHERE id > ? AND status = 'completed' "
            "AND type IN ('image', 'video') AND (is_public_feed = 1 OR is_profile_visible = 1) ORDER BY id LIMIT ?",
            (after_id, limit))).fetchall()
    results = []
    for row in rows:
        source = await get_generation_task_payload(row[0])
        try:
            template = await get_template(source)
            results.append({'source_id': row[0], 'status': 'ready', 'version': template['version']})
        except SmartRepeatError as exc:
            results.append({'source_id': row[0], 'status': 'review_required', 'code': exc.code})
    return {'publications': results, 'next_after_id': rows[-1][0] if rows else after_id, 'has_more': len(rows) == limit}


async def diagnostic_finance(draft):
    """Read current settlement/refund proof; never mutate balances for diagnostics."""
    reserved = float(draft['charge_amount'])
    refunded = float(draft['refund_amount'])
    result = {'reserved_amount': reserved, 'charge_amount': max(0, reserved - refunded),
              'refund_amount': refunded, 'billing_source': 'repeat_reservation'}
    if not draft.get('task_id'):
        return result
    async with db_backend.connect() as db:
        db.row_factory = db_backend.Row
        if (draft.get('snapshot') or {}).get('model') in {'wan_3', 'wan_3_prime'}:
            intent = await (await db.execute('SELECT reserve_credits, charged_credits, refunded_credits, settled '
                'FROM wan3_prime_intents WHERE internal_task_id = ? AND user_id = ?',
                (draft['task_id'], draft['user_id']))).fetchone()
            if intent:
                return {'reserved_amount': float(intent['reserve_credits']),
                    'charge_amount': float(intent['charged_credits'] if intent['settled'] else intent['reserve_credits']),
                    'refund_amount': float(intent['refunded_credits']), 'billing_source': 'wan_intent',
                    'billing_status': 'settled' if intent['settled'] else 'reserved'}
        task = await (await db.execute('SELECT cost, request_data FROM generation_tasks WHERE task_id = ? AND user_id = ?',
            (draft['task_id'], draft['user_id']))).fetchone()
    if task:
        metadata = json.loads(task['request_data'] or '{}')
        if metadata.get('refund_claimed') and metadata.get('refund_state') == 'refunded':
            refunded = max(refunded, float(metadata.get('charged_cost', task['cost']) or 0))
            result.update(charge_amount=max(0, reserved - refunded), refund_amount=refunded,
                          billing_source='task_refund', billing_status='refunded')
    return result
