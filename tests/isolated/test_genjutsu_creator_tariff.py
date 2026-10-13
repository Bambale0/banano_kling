"""Selected real Genjutsu seams, synthetic config/transactions, no app imports.

Run directly with Python. This intentionally bypasses application pytest fixtures.
No database, provider, Telegram, filesystem configuration or network is mutated.
"""
from __future__ import annotations

import ast
import asyncio
import copy
import hashlib
import json
import logging
import random
import re
import sys
import time
import unicodedata
import unittest
from collections.abc import Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parents[2]


def definitions(path, dependencies):
    """Execute the named source's definitions only, without its app imports."""
    file = ROOT / path
    tree = ast.parse(file.read_text(), filename=str(file))
    tree.body = [node for node in tree.body if not isinstance(node, (ast.Import, ast.ImportFrom))]
    injected = {'asyncio': asyncio, 'logging': logging, 'random': random, 're': re,
                'time': time, 'unicodedata': unicodedata, 'Awaitable': Awaitable,
                'Callable': Callable, 'Mapping': Mapping, 'Any': Any, 'UUID': UUID,
                'uuid4': uuid4}
    ns = {**globals(), **injected, **dependencies, '__file__': str(file),
          '__package__': 'bot.genjutsu', '__name__': 'isolated_genjutsu'}
    exec(compile(tree, str(file), 'exec'), ns)  # noqa: S102 - selected repository definitions, synthetic dependencies
    return ns


class CreatorSeams(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tariff = 'creator'
        self.overrides = {'motion_transfer': {'720p': 1}}
        self.actor_calls = []

        async def actor(owner, *, db=None):
            self.actor_calls.append((owner, db))
            return self.tariff

        def snapshot(ordinary, *, tariff='standard'):
            prices = copy.deepcopy(ordinary)
            profile = 'standard'
            if tariff == 'creator':
                for op, rates in self.overrides.items():
                    for quality, rate in rates.items():
                        if rate is not None:
                            prices[op][quality] = rate
                            profile = 'creator'
            revision = hashlib.sha256(json.dumps([profile, prices], sort_keys=True).encode()).hexdigest()
            return {'prices': prices, 'profile': profile, 'revision': revision}

        def prices(ordinary, *, tariff='standard'):
            return snapshot(ordinary, tariff=tariff)['prices']

        core = {'get_actor_tariff': actor, 'genjutsu_pricing_snapshot': snapshot,
                'genjutsu_price_rates': prices}
        self.contract = definitions('bot/genjutsu/contract.py', {})
        dep = {**self.contract, **core, 'ProviderFailure': ValueError, 'request_id': lambda value: value}
        self.repo_ns = definitions('bot/genjutsu/repository.py', dep)
        self.pipe_ns = definitions('bot/genjutsu/pipeline.py', dep)
        self.recipe_ns = definitions('bot/genjutsu/recipes.py', {**dep, **self.repo_ns, **core})
        self.api_ns = definitions('bot/genjutsu/api.py', {
            **dep, 'web': SimpleNamespace(json_response=lambda body, **kwargs: {'body': body, **kwargs}),
        })
        self.snapshot = snapshot
        self.settings = self.contract['default_settings']()
        self.settings.update(public_enabled=True, verified_operations=list(self.contract['CATALOG']))
        self.settings['prices'] = {
            op: {'480p': 2, '720p': 3, '1080p': 4} for op in self.contract['CATALOG']
        }
        self.assets = {'source': {'id': 'source', 'kind': 'video', 'duration_ms': 4001,
                                  'width': 1280, 'height': 720},
                       'ref': {'id': 'ref', 'kind': 'image'}}
        self.plan = {'source_asset_id': 'source', 'variants': 1, 'continuation': 'automatic',
                     'steps': [{'operation': 'motion_transfer', 'resolution': '720p',
                                'prompt': '', 'preserve': '', 'preset_id': None,
                                'references': [{'asset_id': 'ref', 'role': 'character', 'label': ''}]}]}
        self.repo = SimpleNamespace(
            get_project=AsyncMock(return_value={'revision': 1, 'plan': self.plan}),
            settings=AsyncMock(side_effect=lambda: (copy.deepcopy(self.settings), 7)),
            get_assets=AsyncMock(return_value=self.assets), create_quote=AsyncMock(),
            balance=AsyncMock(return_value=100), list_projects=AsyncMock(return_value=[]),
            list_runs=AsyncMock(return_value=[]), list_assets=AsyncMock(return_value=[]),
        )
        self.repo.create_quote.side_effect = lambda owner, pid, revision, plan, quote, version, settings, **kw: {
            'id': 'quote-id', 'expires_ms': 9999999, **quote,
        }
        self.pipeline = self.pipe_ns['Pipeline'](
            self.repo, SimpleNamespace(configured=True),
            SimpleNamespace(configured=True, ensure_asset=AsyncMock()),
        )

    async def test_quote_prices_creator_and_preserves_ordinary_settings(self):
        quote = await self.pipeline.quote(101, 'project-id', 1)
        self.assertEqual(quote['total_credits'], 10)
        self.assertEqual(quote['allocations'][0]['credits_per_second'], 1)
        self.assertEqual(quote['tariff']['profile'], 'creator')
        self.assertEqual(self.repo.create_quote.call_args.args[6], self.settings)
        self.assertEqual(self.settings['prices']['motion_transfer']['720p'], 3)

    async def test_missing_cell_falls_back_and_chain_reserves_keep_formula(self):
        self.plan['variants'] = 2
        self.plan['steps'].append({**self.plan['steps'][0], 'operation': 'object_swap',
                                   'resolution': '480p'})
        quote = await self.pipeline.quote(101, 'project-id', 1)
        self.assertEqual(quote['total_credits'], (10 + 120) * 2)
        self.assertEqual(quote['allocations'][1]['credits_per_second'], 2)
        self.assertEqual(quote['pricing_version'], 2)

    async def test_standard_and_admin_quotes_keep_ordinary_preview(self):
        for tariff in ('standard', 'admin'):
            self.tariff = tariff
            quote = await self.pipeline.quote(101, 'project-id', 1)
            self.assertEqual(quote['total_credits'], 30)

    async def test_bootstrap_returns_personal_prices_without_mutating_settings(self):
        api = self.api_ns['API'](self.pipeline, AsyncMock(return_value=(101, False)))
        value = await api.dispatch(101, False, 'bootstrap', {})
        self.assertEqual(value['prices']['motion_transfer']['720p'], 1)
        self.assertEqual(value['prices']['object_swap']['720p'], 3)
        self.assertEqual(self.settings['prices']['motion_transfer']['720p'], 3)

    async def test_api_rejects_client_tariff_and_uses_no_store(self):
        api = self.api_ns['API'](self.pipeline, AsyncMock(return_value=(101, False)))
        api.body = AsyncMock(return_value={'action': 'bootstrap', 'tariff': 'creator'})
        result = await api.handle(object())
        self.assertEqual(result['status'], 400)
        self.assertEqual(result['headers']['Cache-Control'], 'no-store')
        self.assertFalse(result['body']['ok'])

    def recipes(self):
        self.repo.get_asset_internal = AsyncMock(return_value=self.assets['source'])
        store = self.recipe_ns['RecipeStore'](self.repo)
        store._row = AsyncMock(return_value={'id': 'recipe-id', 'title': 'Recipe', 'plan': self.plan,
                                             'user_fields': [], 'source_binding': 'fixed'})
        return store

    async def test_recipe_get_and_costs_use_actor_prices_without_private_leak(self):
        store = self.recipes()
        api = self.api_ns['API'](self.pipeline, AsyncMock(), recipes=store)
        public = await store.dispatch(101, False, 'recipe_get', {'recipe_id': 'recipe-id'}, api)
        self.assertEqual(public['recipe']['current_cost'], 10)
        self.assertNotIn('source_asset_id', public['recipe'])
        self.assertNotIn('prompt', public['recipe']['steps'][0])
        costs = await store.dispatch(101, False, 'recipe_costs', {'recipe_ids': ['recipe-id']}, api)
        self.assertEqual(costs['costs']['recipe-id'], 10)
        ordinary = await store.public('recipe-id')
        self.assertEqual(ordinary['current_cost'], 30)

    async def test_recipe_quote_metadata_matches_actor_quote(self):
        store = self.recipes()
        store.instantiate = AsyncMock(return_value={'id': 'project-id', 'revision': 1})
        api = self.api_ns['API'](self.pipeline, AsyncMock(), recipes=store)
        api.require_creation = AsyncMock()
        value = await store.dispatch(101, False, 'recipe_quote', {'recipe_id': 'recipe-id'}, api)
        self.assertEqual(value['quote']['total_credits'], 10)
        self.assertEqual(value['recipe']['current_cost'], 10)

    async def admission(self, *, legacy=False, existing=False, admin_free=False):
        quote = self.contract['quote_plan'](self.plan, self.assets, self.settings)
        if not legacy:
            snap = self.snapshot(self.settings['prices'], tariff='creator')
            priced = {**self.settings, 'prices': snap['prices']}
            quote = self.contract['quote_plan'](self.plan, self.assets, priced)
            quote['tariff'] = {key: snap[key] for key in ('profile', 'revision')}
        self.quoted = {'id': 'quote-id', 'owner': 101, 'used_by': None, 'expires_ms': 999999,
                       'config_version': 7, 'config_hash': self.contract['fingerprint'](self.settings),
                       'project_id': 'project-id', 'revision': 1, 'private_recipe': 0,
                       'plan': json.dumps(self.plan), 'quote': json.dumps(quote),
                       'settings': json.dumps(self.settings)}
        self.fake_db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(rowcount=1)))

        @asynccontextmanager
        async def transaction():
            yield self.fake_db

        async def one(db, sql, params=()):
            if 'SELECT id,quote_id FROM genjutsu_runs' in sql:
                return {'id': 'existing-run', 'quote_id': 'quote-id'} if existing else None
            if 'SELECT * FROM genjutsu_quotes' in sql:
                return self.quoted
            if 'SELECT revision FROM genjutsu_projects' in sql:
                return {'revision': 1}
            if 'COUNT(*)' in sql:
                return {'count': 0}
            if 'SELECT q.quote' in sql:
                return {'quote': self.quoted['quote']}
            raise AssertionError(sql)

        self.repo_ns['one'] = one
        repo = self.repo_ns['Repository'](None, clock=lambda: 100)
        repo.transaction = transaction
        repo._settings = AsyncMock(return_value=(copy.deepcopy(self.settings), 7))
        repo._event = AsyncMock()
        repo.start_validator = AsyncMock()
        return repo

    async def test_start_rejects_changed_creator_rate_before_debit(self):
        repo = await self.admission()
        self.overrides['motion_transfer']['720p'] = 2
        with self.assertRaisesRegex(self.contract['PipelineError'], 'quote_changed'):
            await repo.start(101, 'creator-start-1', 'quote-id')
        self.fake_db.execute.assert_not_awaited()
        self.assertEqual(self.actor_calls, [(101, self.fake_db)])

    async def test_start_rejects_revoked_membership_before_debit(self):
        repo = await self.admission()
        self.tariff = 'standard'
        with self.assertRaisesRegex(self.contract['PipelineError'], 'quote_changed'):
            await repo.start(101, 'creator-start-1', 'quote-id')
        self.fake_db.execute.assert_not_awaited()

    async def test_start_uses_snapshot_rate_and_idempotence_precedes_revalidation(self):
        repo = await self.admission()
        await repo.start(101, 'creator-start-1', 'quote-id')
        queries = self.fake_db.execute.await_args_list
        debit = next(call for call in queries if call.args[0].startswith('UPDATE users SET credits=credits-'))
        self.assertEqual(debit.args[1], (10, 101, 10))
        step = next(call for call in queries if 'INSERT INTO genjutsu_steps' in call.args[0])
        self.assertEqual(step.args[1][7:9], (10, 1))
        repo = await self.admission(existing=True)
        self.actor_calls.clear()
        self.tariff = 'standard'
        result = await repo.start(101, 'creator-start-1', 'quote-id')
        self.assertEqual(result['id'], 'existing-run')
        self.assertEqual(self.actor_calls, [])
        self.fake_db.execute.assert_not_awaited()

    async def test_legacy_quote_and_admin_free_reserve_preserve_amounts(self):
        repo = await self.admission(legacy=True)
        await repo.start(101, 'legacy-start-1', 'quote-id')
        debit = next(call for call in self.fake_db.execute.await_args_list
                     if call.args[0].startswith('UPDATE users SET credits=credits-'))
        self.assertEqual(debit.args[1], (30, 101, 30))
        repo = await self.admission(legacy=True)
        await repo.start(101, 'admin-start-1', 'quote-id', admin_free=True)
        self.assertFalse(any(call.args[0].startswith('UPDATE users SET credits=credits-')
                             for call in self.fake_db.execute.await_args_list))

    async def test_final_submission_keeps_frozen_rate_after_tariff_change(self):
        repo = await self.admission()
        self.overrides['motion_transfer']['720p'] = 9
        self.tariff = 'standard'
        repo._leased_step = AsyncMock(return_value={
            'status': 'ready', 'cancel_requested': 0, 'spec': json.dumps(self.plan['steps'][0]),
            'run_id': 'accepted-run', 'admin_free': 0, 'rate': 1, 'reserved_credits': 10,
        })
        module = ModuleType('bot.genjutsu.contract')
        module.__dict__.update(self.contract)
        with patch.dict(sys.modules, {'bot.genjutsu.contract': module}):
            await repo.begin_submission('step-id', 'lease-token', 4001)
        update = self.fake_db.execute.await_args_list[0]
        self.assertEqual(update.args[1][1], 10)
        self.assertEqual(self.actor_calls, [])


    async def test_used_quote_returns_accepted_run_without_repricing(self):
        repo = await self.admission()
        self.quoted['used_by'] = 'accepted-run'
        self.tariff = 'standard'
        result = await repo.start(101, 'different-idempotency-key', 'quote-id')
        self.assertEqual(result['id'], 'accepted-run')
        self.fake_db.execute.assert_not_awaited()
        self.assertEqual(self.actor_calls, [])

    async def test_accepted_v1_submission_keeps_legacy_formula(self):
        repo = await self.admission(legacy=True)
        quote = json.loads(self.quoted['quote'])
        quote.pop('pricing_version')
        self.quoted['quote'] = json.dumps(quote)
        repo._leased_step = AsyncMock(return_value={
            'status': 'ready', 'cancel_requested': 0, 'spec': json.dumps(self.plan['steps'][0]),
            'run_id': 'accepted-run', 'admin_free': 0, 'rate': 3, 'reserved_credits': 15,
        })
        module = ModuleType('bot.genjutsu.contract')
        module.__dict__.update(self.contract)
        with patch.dict(sys.modules, {'bot.genjutsu.contract': module}):
            await repo.begin_submission('step-id', 'lease-token', 4001)
        self.assertEqual(self.fake_db.execute.await_args_list[0].args[1][1], 15)
        self.assertEqual(self.actor_calls, [])

    async def test_refund_remains_frozen_and_idempotent_after_creator_changes(self):
        repo = await self.admission()
        self.tariff = 'standard'
        self.overrides['motion_transfer']['720p'] = 999
        step = {'id': 'accepted-step', 'run_id': 'accepted-run',
                'reserved_credits': 60, 'refunded_credits': 0}
        await repo._refund(self.fake_db, step, 101, 50)
        await repo._refund(self.fake_db, step, 101, 50)
        credits = [call for call in self.fake_db.execute.await_args_list
                   if call.args[0].startswith('UPDATE users SET credits=credits+')]
        self.assertEqual(len(credits), 1)
        self.assertEqual(credits[0].args[1], (50, 101))
        self.assertEqual(self.actor_calls, [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
