"""Actual publication function with synthetic SQLite, not a production DB adapter."""
import ast
import hashlib
import json
import sqlite3
import sys
import tempfile
import types
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, patch

from test_wan_manual_publication import ManualPublicationTests


class ValidationError(ValueError):
    def __init__(self, message, *, status=400):
        super().__init__(message)
        self.status = status


class Cursor:
    def __init__(self, cursor):
        self.cursor = cursor
        self.lastrowid = cursor.lastrowid

    async def fetchone(self):
        return self.cursor.fetchone()


class Connection:
    def __init__(self, db):
        self.db = db

    async def execute(self, sql, args=()):
        return Cursor(self.db.execute(sql, args))

    async def commit(self):
        self.db.commit()


class ManualTransactionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = sqlite3.connect(':memory:')
        self.db.row_factory = sqlite3.Row
        self.addCleanup(self.db.close)
        self.db.executescript('''CREATE TABLE user_prompts(id INTEGER PRIMARY KEY, author_id, title, description,
            category, prompt_text, preview_url, model, tags, generation_settings, is_public, status, source_generation_id);
            CREATE TABLE wan3_prime_media(public_url, user_id, telegram_id, kind, local_path, sha256);
            CREATE TABLE wan3_prime_trend_recipes(trend_id PRIMARY KEY,source_task_id,owner_id,owner_telegram_id,
            recipe_json,slots_json,publication_key UNIQUE);''')
        fixture = ManualPublicationTests()
        fixture.setUp()
        self.recipe = fixture.recipe
        self.settings = fixture.settings
        for index, url in enumerate(self.recipe['reference_image_urls']):
            file = self.root / f'{index}.png'
            file.write_bytes(b'synthetic')
            self.db.execute('INSERT INTO wan3_prime_media VALUES(?,?,?,?,?,?)', (url, 1, 100, 'image', str(file), 'digest'))
        self.db.commit()
        self.actor = types.SimpleNamespace(user_id=1, telegram_id=100, is_admin=True)
        self.prepared = AsyncMock(return_value={})

        @asynccontextmanager
        async def connect(_path):
            try:
                yield Connection(self.db)
            finally:
                if self.db.in_transaction:
                    self.db.rollback()

        async def lock(db):
            await db.execute('BEGIN IMMEDIATE')

        async def validate(raw, probe):
            for slot in fixture.slots(raw):
                await probe.probe_url(slot['url'], kind=slot['kind'])
            return types.SimpleNamespace(raw_provider_args=lambda: {k: v for k, v in raw.items() if k != 'model'})

        modules = {}
        def module(name, **values):
            result = types.ModuleType(name)
            result.__dict__.update(values)
            modules[name] = result
        module('bot'); module('bot.services')
        module('bot.services.wan3_manual_publication', manual_publication_input=fixture.validate)
        module('bot.services.wan3_models', wan3_service_for_model=lambda _model: types.SimpleNamespace(prepare_request=self.prepared))
        module('bot.services.wan3_prime_media', assert_public_url=AsyncMock(), validate_wan3_recipe=validate)
        module('bot.services.wan3_prime_probe_cache', verified_metadata=AsyncMock(return_value=object()))
        module('bot.services.wan3_prime_repeat', source_slots=fixture.slots)
        module('bot.services.wan3_prime_storage', UPLOAD_ROOT=self.root, _sha256_file=lambda _: 'digest',
               wan3_prime_storage=types.SimpleNamespace(init_schema=AsyncMock()))
        module('bot.services.wan3_prime_storage_policy', lock_storage=lock)
        self.patch = patch.dict(sys.modules, modules)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        tree = ast.parse(Path('bot/services/wan3_prime_trends.py').read_text())
        node = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == 'publish_manual_trend')
        namespace = {'Any': object, 'hashlib': hashlib, '_json': lambda value: json.dumps(value, sort_keys=True),
                     'Wan3PrimeValidationError': ValidationError, 'init_trend_schema': AsyncMock(),
                     'database': types.SimpleNamespace(DATABASE_PATH='synthetic'),
                     'db_backend': types.SimpleNamespace(connect=connect, Row=sqlite3.Row)}
        exec(compile(ast.Module(body=[node], type_ignores=[]), 'trusted-publication', 'exec'), namespace)  # noqa: S102
        self.publish = namespace['publish_manual_trend']
        self.kwargs = {'model': 'wan_3', 'prompt': self.recipe['prompt'], 'settings': self.settings,
                       'title': 'Synthetic', 'description': '', 'preview_url': 'https://owned.test/preview.mp4'}

    async def test_atomic_pair_private_data_and_replay(self):
        first = await self.publish(self.actor, **self.kwargs)
        replay = await self.publish(self.actor, **self.kwargs)
        self.assertEqual(first['trend_id'], replay['trend_id'])
        self.assertTrue(replay['replayed'])
        row = dict(self.db.execute('SELECT * FROM user_prompts').fetchone())
        self.assertNotIn('owned.test/a.jpg', str(row))
        self.assertNotIn('Image1 beside', str(row))
        self.assertIsNone(row['source_generation_id'])
        self.assertEqual(self.db.execute('SELECT count(*) FROM wan3_prime_trend_recipes').fetchone()[0], 1)
        self.db.execute("UPDATE user_prompts SET status='deactivated',is_public=0")
        self.db.commit()
        await self.publish(self.actor, **self.kwargs)
        self.assertEqual(self.db.execute('SELECT status FROM user_prompts').fetchone()[0], 'deactivated')

    async def test_failure_in_second_insert_rolls_back_first(self):
        self.db.execute("CREATE TRIGGER reject_recipe BEFORE INSERT ON wan3_prime_trend_recipes BEGIN SELECT RAISE(ABORT,'synthetic failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            await self.publish(self.actor, **self.kwargs)
        self.assertEqual(self.db.execute('SELECT count(*) FROM user_prompts').fetchone()[0], 0)

    async def test_foreign_owner_rejected_before_any_publication(self):
        self.db.execute('UPDATE wan3_prime_media SET user_id=99')
        self.db.commit()
        with self.assertRaises(ValidationError) as error:
            await self.publish(self.actor, **self.kwargs)
        self.assertEqual(error.exception.status, 403)
        self.assertEqual(self.db.execute('SELECT count(*) FROM user_prompts').fetchone()[0], 0)
        self.prepared.assert_not_awaited()


if __name__ == '__main__':
    unittest.main()
