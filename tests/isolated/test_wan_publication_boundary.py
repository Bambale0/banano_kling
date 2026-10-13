"""Shared HTTP boundary tests with no application or database imports."""
import ast
import json
import logging
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from aiohttp import web


class ValidationError(ValueError):
    status = 400


def boundary(publish):
    from types import SimpleNamespace
    imports = {}
    for name, values in {
        'bot.services.wan3_prime_lifecycle': {'Wan3PrimeActor': lambda uid, tid, **kw: SimpleNamespace(user_id=uid, telegram_id=tid, **kw)},
        'bot.services.wan3_prime_media': {'Wan3PrimeValidationError': ValidationError},
        'bot.services.wan3_prime_trends': {'publish_manual_trend': publish},
    }.items():
        module = types.ModuleType(name)
        module.__dict__.update(values)
        imports[name] = module
    errors = types.ModuleType('bot.services.wan3_public_errors')
    exec(compile(Path('bot/services/wan3_public_errors.py').read_text(), 'wan-public-errors', 'exec'), errors.__dict__)  # noqa: S102
    imports[errors.__name__] = errors
    logger = Mock(spec=logging.Logger)
    scope = {'web': web, 'json': json, 'config': SimpleNamespace(is_admin=lambda _tid: True),
             'normalize_user_fields_settings': lambda settings, **_kw: settings,
             'detect_explicit_prompt_policy_violation': lambda _prompt: None,
             'TrendUserFieldsError': ValueError, 'logger': logger,
             'get_prompt_by_id': AsyncMock(return_value={'id': 1})}
    source = ast.parse(Path('bot/miniapp.py').read_text())
    node = next(n for n in source.body if isinstance(n, ast.AsyncFunctionDef) and n.name == '_miniapp_publish_wan_trend')
    exec(compile(ast.Module(body=[node], type_ignores=[]), 'actual-wan-boundary', 'exec'), scope)  # noqa: S102
    return scope['_miniapp_publish_wan_trend'], imports, logger


class BoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_advertised_twenty_thousand_character_prompt_reaches_validation(self):
        publish = AsyncMock(return_value={'trend_id': 1})
        call, imports, _logger = boundary(publish)
        for count in (12001, 20000):
            with self.subTest(count=count), patch.dict(sys.modules, imports):
                prompt = 'я' * count
                response = await call({'model': 'wan_3', 'prompt_text': prompt, 'generation_settings': {'wan3_recipe': {'prompt': prompt}}}, 123, types.SimpleNamespace(id=7))
                self.assertEqual(response.status, 200)
                self.assertEqual(publish.call_args.kwargs['prompt'], prompt)

    async def test_oversized_settings_still_fail_before_publication(self):
        publish = AsyncMock(return_value={'trend_id': 1})
        call, imports, _logger = boundary(publish)
        with patch.dict(sys.modules, imports):
            response = await call({'model': 'wan_3', 'prompt_text': 'ok', 'generation_settings': {'padding': 'я' * 33000}}, 123, types.SimpleNamespace(id=7))
        self.assertEqual(response.status, 400)
        publish.assert_not_called()

    async def test_compact_utf8_budget_matches_frontend_exact_boundary(self):
        for size, expected in ((64000, 200), (64001, 400)):
            with self.subTest(size=size):
                publish = AsyncMock(return_value={'trend_id': 1})
                call, imports, _logger = boundary(publish)
                settings = {'padding': '', 'nested': {'a': 1, 'b': 2}}
                baseline = len(json.dumps(settings, ensure_ascii=False, separators=(',', ':')).encode('utf-8'))
                settings['padding'] = 'x' * (size - baseline)
                with patch.dict(sys.modules, imports):
                    response = await call({'model': 'wan_3', 'prompt_text': 'ok', 'generation_settings': settings}, 123, types.SimpleNamespace(id=7))
                self.assertEqual(response.status, expected)
                self.assertEqual(publish.call_count, int(expected == 200))

    async def test_unexpected_failure_has_safe_context_and_correlation_without_exception_text(self):
        publish = AsyncMock(side_effect=RuntimeError('SECRET prompt https://private.test/reference'))
        call, imports, logger = boundary(publish)
        with patch.dict(sys.modules, imports):
            response = await call({'model': 'wan_3_prime', 'prompt_text': 'safe'}, 123, types.SimpleNamespace(id=7))
        self.assertEqual(response.status, 500)
        payload = json.loads(response.text)
        self.assertRegex(payload.get('error_id', ''), r'^[a-f0-9]{32}$')
        logged = str(logger.mock_calls)
        self.assertNotIn('SECRET', logged + response.text)
        self.assertNotIn('private.test', logged + response.text)
        self.assertIn(payload['error_id'], logged)
        self.assertIn('wan_3_prime', logged)
        self.assertIn('RuntimeError', logged)
        self.assertIn('123', logged)
        self.assertIn('stack', logged)


if __name__ == '__main__':
    unittest.main()
