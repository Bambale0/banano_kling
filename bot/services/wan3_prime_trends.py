"""Curated Wan trends in the existing catalog, with private recipes kept server-side.

The public user_prompts row contains presentation data, never an author's hidden
prompt/reference URLs. Execution uses the same quote, ownership, ledger and
provider lifecycle as the ordinary Wan composer.
"""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any

from bot import database
from bot import db as db_backend
from bot.services.wan3_prime_media import WAN3_MODEL_KEY, Wan3PrimeValidationError
from bot.services.wan3_prime_schema import execute_wan_ddl


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


async def init_trend_schema() -> None:
    async with db_backend.connect(database.DATABASE_PATH) as db:
        await execute_wan_ddl(db, '''CREATE TABLE IF NOT EXISTS wan3_prime_trend_recipes (
            trend_id BIGINT PRIMARY KEY, source_task_id TEXT NOT NULL,
            owner_id BIGINT NOT NULL, owner_telegram_id BIGINT NOT NULL,
            recipe_json TEXT NOT NULL, slots_json TEXT NOT NULL,
            publication_key TEXT UNIQUE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        # Existing success-counter contract joins this durable relation to the
        # final generation state, rather than counting callbacks or attempts.
        await execute_wan_ddl(db, '''CREATE TABLE IF NOT EXISTS trend_generation_runs (
            task_id TEXT PRIMARY KEY, trend_id BIGINT NOT NULL,
            user_id BIGINT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        await db.commit()


async def publication_recipe(actor, task_id: str) -> dict[str, Any]:
    from bot.services.wan3_prime_repeat import source_recipe, source_slots

    if not actor.is_admin:
        raise Wan3PrimeValidationError('Administrator access required', status=403)
    source = await database.get_generation_task_payload(task_id, user_id=actor.user_id)
    if not source or source.get('status') != 'completed' or not source.get('result_url'):
        raise Wan3PrimeValidationError('Completed own Wan result required', status=404)
    if database.generation_has_private_recipe(source):
        raise Wan3PrimeValidationError('A derived private recipe cannot be republished', status=403)
    recipe = source_recipe(source)
    return {'source': source, 'recipe': recipe, 'slots': source_slots(recipe)}


async def publish_trend(actor, *, task_id: str, title: str, description: str, replacement_keys: list[str]) -> dict[str, Any]:
    from bot.services.wan3_prime_storage_policy import lock_storage

    original = await publication_recipe(actor, task_id)
    if not isinstance(title, str) or not 1 <= len(title.strip()) <= 60:
        raise Wan3PrimeValidationError('Trend title must contain 1-60 characters')
    if not isinstance(description, str) or len(description) > 200:
        raise Wan3PrimeValidationError('Trend description must contain at most 200 characters')
    if (not isinstance(replacement_keys, list) or any(not isinstance(key, str) for key in replacement_keys)
            or len(set(replacement_keys)) != len(replacement_keys)):
        raise Wan3PrimeValidationError('Choose distinct replaceable slots')
    keys = set(replacement_keys)
    if not keys <= {slot['key'] for slot in original['slots']}:
        raise Wan3PrimeValidationError('Unknown recipe slot')
    slots = [{**slot, 'binding': 'upload' if slot['key'] in keys else 'fixed'} for slot in original['slots']]
    recipe = original['recipe']
    revision = {'owner': actor.user_id, 'source': task_id, 'recipe': recipe, 'slots': slots,
                'title': title.strip(), 'description': description.strip()}
    publication_key = hashlib.sha256(_json(revision).encode()).hexdigest()
    await init_trend_schema()
    async with db_backend.connect(database.DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        await lock_storage(db)
        existing = await (await db.execute('SELECT trend_id FROM wan3_prime_trend_recipes WHERE publication_key = ?', (publication_key,))).fetchone()
        if existing:
            return {'ok': True, 'trend_id': int(existing['trend_id']), 'replayed': True}
        # The immutable generation recipe and its ownership must still agree
        # when publishing. No user-provided prompt/media enters the private row.
        current = await (await db.execute('SELECT * FROM generation_tasks WHERE task_id = ? AND user_id = ?' +
                                          (' FOR SHARE' if db_backend.is_postgres() else ''), (task_id, actor.user_id))).fetchone()
        from bot.services.wan3_prime_repeat import source_recipe
        if not current or current['status'] != 'completed' or source_recipe(dict(current)) != recipe:
            raise Wan3PrimeValidationError('Source generation changed; open it again', status=409)
        settings = {
            'kind': 'video', 'model': WAN3_MODEL_KEY, 'scenario': recipe['scenario'],
            'ratio': recipe.get('aspect_ratio', 'adaptive'), 'duration': recipe.get('duration', 5),
            'resolution': recipe.get('resolution', '1080P'), 'wan3_recipe_version': 1,
            'user_reference_count': len(keys),
            'reference_slots': [
                {'media_type': slot['kind'], 'position': slot['index'] + 1,
                 'label': slot['key'], 'role': 'user_upload' if slot['binding'] == 'upload' else 'fixed_hidden'}
                for slot in slots],
        }
        inserted = await db.execute('''INSERT INTO user_prompts
            (author_id, title, description, category, prompt_text, preview_url,
             model, tags, generation_settings, is_public, status, source_generation_id)
            VALUES (?, ?, ?, 'video', 'Wan 3.0 curated recipe', ?, ?, ?, ?, 1, 'approved', ?)
        ''', (actor.user_id, title.strip(), description.strip(), original['source']['result_url'], WAN3_MODEL_KEY,
              _json(['trend', 'trend-video', 'wan3-prime']), _json(settings), original['source']['id']))
        trend_id = int(inserted.lastrowid)
        await db.execute('''INSERT INTO wan3_prime_trend_recipes
            (trend_id, source_task_id, owner_id, owner_telegram_id, recipe_json, slots_json, publication_key)
            VALUES (?, ?, ?, ?, ?, ?, ?)''',
            (trend_id, task_id, actor.user_id, actor.telegram_id, _json(recipe), _json(slots), publication_key))
        await db.commit()
    return {'ok': True, 'trend_id': trend_id, 'replayed': False}


def _plan(row) -> dict[str, Any]:
    recipe = json.loads(row['recipe_json'])
    slots = json.loads(row['slots_json'])
    revision = {'id': row['trend_id'], 'owner': row['owner_id'], 'recipe': recipe, 'slots': slots,
                'status': row['status'], 'is_public': bool(row['is_public'])}
    return {'source_id': 0, 'trend_id': int(row['trend_id']), 'owner_id': int(row['owner_id']),
            'owner_telegram_id': int(row['owner_telegram_id']), 'recipe': deepcopy(recipe), 'slots': slots,
            'hash': hashlib.sha256(_json(revision).encode()).hexdigest()}


async def get_trend_plan(actor, trend_id: int) -> dict[str, Any]:
    if isinstance(trend_id, bool) or not isinstance(trend_id, int) or trend_id <= 0:
        raise Wan3PrimeValidationError('Invalid trend', status=400)
    async with db_backend.connect(database.DATABASE_PATH) as db:
        db.row_factory = db_backend.Row
        row = await (await db.execute('''SELECT recipe.*, prompt.status, prompt.is_public
            FROM wan3_prime_trend_recipes recipe JOIN user_prompts prompt ON prompt.id = recipe.trend_id
            WHERE recipe.trend_id = ? AND prompt.status = 'approved' AND prompt.is_public = 1
              AND prompt.model = ?''', (trend_id, WAN3_MODEL_KEY))).fetchone()
    if not row:
        raise Wan3PrimeValidationError('Trend is no longer available', status=404)
    return _plan(row)


async def verify_trend_in_transaction(db, context: dict[str, Any]) -> None:
    row = await (await db.execute('''SELECT recipe.*, prompt.status, prompt.is_public
        FROM wan3_prime_trend_recipes recipe JOIN user_prompts prompt ON prompt.id = recipe.trend_id
        WHERE recipe.trend_id = ? AND prompt.status = 'approved' AND prompt.is_public = 1
        ''' + (' FOR SHARE OF recipe, prompt' if db_backend.is_postgres() else ''), (context['trend_id'],))).fetchone()
    if not row or _plan(row)['hash'] != context['source_hash']:
        raise Wan3PrimeValidationError('Trend permission changed; open it again', status=409)
