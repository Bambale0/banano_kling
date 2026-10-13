"""Execute actual public sanitizer declarations without importing the application."""
import ast
import hashlib
import hmac
import json
import re
import unittest
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qsl, urlencode

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

source = ast.parse(Path('bot/trend_visibility.py').read_text())
ns = {'Mapping': Mapping, 'Any': Any, 're': re,
      'configured_user_fields': lambda *_args, **_kwargs: [], 'TrendUserFieldsError': ValueError, 'hashlib': hashlib, 'hmac': hmac, 'json': json, 'parse_qsl': parse_qsl}
selected = {'is_trend_prompt', 'public_trend_settings', 'sanitize_prompt_for_public', 'sanitize_prompt_api_payload', 'verified_telegram_id_from_init_data'}
exec(compile(ast.Module(body=[node for node in source.body if isinstance(node, ast.FunctionDef) and node.name in selected], type_ignores=[]), 'actual-trend-sanitizer', 'exec'), ns)  # noqa: S102 - isolated trusted repository declarations


class PublicWanMarkerTests(unittest.TestCase):
    def card(self, model='wan_3', version=1):
        return {'id': 731, 'model': model, 'tags': ['trend', 'trend-video'], 'category': 'video',
                'prompt_text': 'PRIVATE-SYNTHETIC', 'source_generation_id': 99,
                'generation_settings': {'kind': 'video', 'ratio': '9:16', 'model': model,
                  'wan3_recipe_version': version, 'wan3_recipe': {'prompt': 'PRIVATE-SYNTHETIC'},
                  'reference_image_urls': ['https://private.test/fixed.png'], 'user_reference_count': 1}}

    def test_both_models_keep_only_safe_public_discriminator(self):
        for model in ('wan_3', 'wan_3_prime'):
            with self.subTest(model=model):
                result = ns['sanitize_prompt_for_public'](self.card(model))
                self.assertEqual(result['generation_settings'].get('wan3_recipe_version'), 1)
                self.assertIsNone(result['model'])
                self.assertEqual(result['prompt_text'], '')
                self.assertNotIn('source_generation_id', result)
                self.assertNotIn('PRIVATE-SYNTHETIC', str(result))
                self.assertNotIn('private.test', str(result))
                self.assertNotIn('model', result['generation_settings'])
                self.assertNotIn('wan3_recipe', result['generation_settings'])

    def test_generic_or_invalid_marker_does_not_gain_wan_route(self):
        for model, version in [('seedance_2_5', 1), ('wan_3', None), ('wan_3', 2), ('wan_3', True), ('wan_3', '1')]:
            with self.subTest(model=model, version=version):
                result = ns['sanitize_prompt_for_public'](self.card(model, version))
                self.assertNotIn('wan3_recipe_version', result['generation_settings'])

    def test_list_and_detail_payloads_apply_identical_marker_privacy(self):
        result = ns['sanitize_prompt_api_payload']({'prompt': self.card(), 'prompts': [self.card('wan_3_prime')]})
        for item in [result['prompt'], *result['prompts']]:
            self.assertEqual(item['generation_settings'].get('wan3_recipe_version'), 1)
            self.assertIsNone(item['model'])
            self.assertNotIn('private.test', str(item))


class PublicWanHttpTests(unittest.IsolatedAsyncioTestCase):
    async def test_actual_privacy_middleware_preserves_marker_on_list_and_shared_detail(self):
        async def preview_passthrough(payload):
            return payload

        middleware_source = ast.parse(Path('bot/browser_auth.py').read_text())
        middleware_node = next(node for node in middleware_source.body if isinstance(node, ast.AsyncFunctionDef) and node.name == 'trend_prompt_privacy_middleware')
        scope = {**ns, 'web': web, '_with_compatible_trend_previews': preview_passthrough,
                 'config': SimpleNamespace(BOT_TOKEN='synthetic-test-token', is_admin=lambda tid: tid == 222)}
        exec(compile(ast.Module(body=[middleware_node], type_ignores=[]), 'actual-privacy-middleware', 'exec'), scope)  # noqa: S102 - trusted isolated declaration
        for model in ('wan_3', 'wan_3_prime'):
            for detail, actor, shared in [(False, 111, False), (True, 111, False), (True, 222, True)]:
                with self.subTest(model=model, detail=detail, actor=actor):
                    app = web.Application(middlewares=[scope['trend_prompt_privacy_middleware']])
                    app['trend_prompt_privacy_root'] = '/mini-app'
                    async def endpoint(_request, model=model, detail=detail):
                        card = PublicWanMarkerTests().card(model)
                        return web.json_response({'prompt': card} if detail else {'prompts': [card]})
                    route = '/mini-app/api/prompts/detail' if detail else '/mini-app/api/prompts'
                    app.router.add_post(route, endpoint)
                    fields = {'auth_date': '1776200000', 'user': json.dumps({'id': actor})}
                    if shared:
                        fields['start_param'] = 'prompt_731'
                    check = '\n'.join(f'{key}={fields[key]}' for key in sorted(fields))
                    secret = hmac.new(b'WebAppData', b'synthetic-test-token', hashlib.sha256).digest()
                    fields['hash'] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
                    async with TestClient(TestServer(app)) as client:
                        response = await client.post(route, json={'init_data': urlencode(fields)})
                        self.assertEqual(response.status, 200)
                        self.assertEqual(response.headers['Cache-Control'], 'no-store')
                        body = await response.json()
                    card = body['prompt'] if detail else body['prompts'][0]
                    self.assertEqual(card['generation_settings'].get('wan3_recipe_version'), 1)
                    self.assertIsNone(card['model'])
                    self.assertEqual(card['prompt_text'], '')
                    self.assertNotIn('PRIVATE-SYNTHETIC', str(body))
                    self.assertNotIn('private.test', str(body))


if __name__ == '__main__':
    unittest.main()
