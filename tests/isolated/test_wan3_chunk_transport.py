"""Exercise the real upload route without importing application/DB modules.

Run with: python tests/isolated/test_wan3_chunk_transport.py
Only auth and owned-storage seams are mocked. aiohttp parsing is real.
"""
import ast
import base64
import importlib.util
import logging
import sys
import types
import unittest
from functools import wraps
from pathlib import Path
from unittest.mock import AsyncMock, patch

from aiohttp import FormData, web
from aiohttp.test_utils import TestClient, TestServer


class ValidationError(ValueError):
    def __init__(self, message, *, status=400):
        super().__init__(message)
        self.status = status


class LifecycleError(Exception):
    def __init__(self, message, *, status=401, code='auth_required'):
        super().__init__(message)
        self.status, self.code = status, code


class ChunkTransportTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.storage = types.ModuleType('bot.services.wan3_prime_storage')
        self.storage.CHUNK_SIZE = 7 * 1024 * 1024
        self.storage.save_chunk = AsyncMock()
        error_path = Path(__file__).resolve().parents[2] / 'bot/services/wan3_public_errors.py'
        spec = importlib.util.spec_from_file_location('wan_public_errors_test', error_path)
        errors = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(errors)
        self.modules = patch.dict(sys.modules, {
            'bot': types.ModuleType('bot'),
            'bot.services': types.ModuleType('bot.services'),
            'bot.services.wan3_prime_storage': self.storage,
            'bot.services.wan3_public_errors': errors,
        })
        self.modules.start()
        source = Path(__file__).resolve().parents[2] / 'bot/wan3_prime_api.py'
        tree = ast.parse(source.read_text())
        names = {'_json_ok', '_json_error', '_http_boundary', '_upload_chunk_route', '_read_upload_chunk'}
        selected = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in names]
        self.owner = types.SimpleNamespace(user_id=7, telegram_id=17)
        namespace = {'web': web, 'Any': object, 'wraps': wraps, 'logger': logging.getLogger('wan-chunk-test'),
                     'Wan3PrimeValidationError': ValidationError, 'Wan3PrimeLifecycleError': LifecycleError,
                     'wan3_prime_storage': self.storage, '_actor_from_request': AsyncMock(return_value=self.owner)}
        # Trusted repository AST only; avoids importing application/database modules.
        exec(compile(ast.Module(body=selected, type_ignores=[]), str(source), 'exec'), namespace)  # noqa: S102
        self.namespace = namespace
        self.actor = namespace['_actor_from_request']
        app = web.Application(client_max_size=220 * 1024 * 1024)
        app.router.add_post('/chunk', namespace['_http_boundary'](namespace['_upload_chunk_route']))
        self.client = TestClient(TestServer(app))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        self.modules.stop()

    def payload(self, chunk=b'synthetic-jpeg'):
        return {'init_data': 'synthetic', 'start_param_fallback': '', 'upload_id': 'a' * 32,
                'index': 0, 'total': 1, 'chunk_base64': base64.b64encode(chunk).decode()}

    async def post_json(self, payload):
        return await self.client.post('/chunk', json=payload, headers={'X-Telegram-Init-Data': 'synthetic'})

    async def test_disconnect_is_retryable_and_retry_keeps_the_owned_chunk(self):
        read = self.namespace['_read_upload_chunk']
        self.namespace['_read_upload_chunk'] = AsyncMock(side_effect=ConnectionResetError('Connection lost'))
        response = await self.post_json(self.payload())
        self.assertEqual(response.status, 499, await response.text())
        self.assertEqual((await response.json())['code'], 'upload_interrupted')
        self.storage.save_chunk.assert_not_awaited()
        self.namespace['_read_upload_chunk'] = read
        response = await self.post_json(self.payload())
        self.assertEqual(response.status, 200, await response.text())
        self.storage.save_chunk.assert_awaited_once()

    async def test_json_chunk_preserves_exact_bytes_and_owner(self):
        response = await self.post_json(self.payload())
        self.assertEqual(response.status, 200, await response.text())
        self.storage.save_chunk.assert_awaited_once_with(self.owner, upload_id='a' * 32, index=0, total=1, chunk=b'synthetic-jpeg')

    async def test_real_multipart_still_works(self):
        form = FormData()
        for key, value in [('init_data', 'synthetic'), ('start_param_fallback', ''), ('upload_id', 'a' * 32), ('index', '0'), ('total', '1')]:
            form.add_field(key, value)
        form.add_field('chunk', b'synthetic-jpeg', filename='image.jpeg', content_type='image/jpeg')
        response = await self.client.post('/chunk', data=form, headers={'X-Telegram-Init-Data': 'synthetic'})
        self.assertEqual(response.status, 200, await response.text())
        self.storage.save_chunk.assert_awaited_once_with(self.owner, upload_id='a' * 32, index=0, total=1, chunk=b'synthetic-jpeg')

    async def test_broken_webkit_boundary_reproduces_upload_error(self):
        response = await self.client.post('/chunk', data=b'--different-boundary\r\n', headers={
            'X-Telegram-Init-Data': 'synthetic',
            'Content-Type': 'multipart/form-data; boundary=----WebKitFormBoundary8BArtO9WWjSm8IKS',
        })
        self.assertEqual(response.status, 400)
        self.storage.save_chunk.assert_not_awaited()
        body = await response.json()
        self.assertEqual(body['code'], 'invalid_upload_multipart')
        print('Broken WebKit multipart:', response.status, body)

    async def test_missing_auth_never_parses_or_saves(self):
        response = await self.client.post('/chunk', json=self.payload())
        self.assertEqual(response.status, 401)
        self.actor.assert_not_awaited()
        self.storage.save_chunk.assert_not_awaited()

    async def test_invalid_json_payloads_do_not_reach_storage(self):
        cases = [[], {**self.payload(), 'chunk_base64': '%%%='}, {**self.payload(), 'chunk_base64': ''},
                 {**self.payload(), 'index': True}, {**self.payload(), 'total': 1.5},
                 {**self.payload(), 'other_owner': 123}, {**self.payload(), 'chunk_base64': 12}]
        for payload in cases:
            with self.subTest(payload_type=type(payload).__name__):
                response = await self.post_json(payload)
                self.assertEqual(response.status, 400, await response.text())
        self.storage.save_chunk.assert_not_awaited()

    async def test_one_maximum_chunk_is_accepted(self):
        chunk = b'x' * self.storage.CHUNK_SIZE
        response = await self.post_json(self.payload(chunk))
        self.assertEqual(response.status, 200, await response.text())
        self.assertEqual(self.storage.save_chunk.await_args.kwargs['chunk'], chunk)

    async def test_decoded_chunk_over_limit_is_rejected(self):
        response = await self.post_json(self.payload(b'x' * (self.storage.CHUNK_SIZE + 1)))
        self.assertEqual(response.status, 413, await response.text())
        self.storage.save_chunk.assert_not_awaited()

    async def test_encoded_body_over_limit_is_rejected_before_decode(self):
        response = await self.post_json({**self.payload(), 'start_param_fallback': 'x' * (10 * 1024 * 1024)})
        self.assertEqual(response.status, 413, await response.text())
        self.storage.save_chunk.assert_not_awaited()

    async def test_storage_errors_preserve_owned_contract(self):
        self.storage.save_chunk.side_effect = ValidationError('Upload session not found', status=404)
        response = await self.post_json(self.payload())
        self.assertEqual(response.status, 404, await response.text())
        self.assertEqual((await response.json())['error'], 'Upload session not found')

    async def test_auth_failure_precedes_body_parsing(self):
        self.actor.side_effect = LifecycleError('Invalid auth', code='auth_invalid')
        response = await self.post_json([])
        self.assertEqual(response.status, 401)
        self.storage.save_chunk.assert_not_awaited()

    async def test_duplicate_json_fields_are_rejected(self):
        response = await self.client.post('/chunk', data=b'{"index":0,"index":1}', headers={
            'X-Telegram-Init-Data': 'synthetic', 'Content-Type': 'application/json'})
        self.assertEqual(response.status, 400)
        self.storage.save_chunk.assert_not_awaited()

    async def test_streamed_json_body_over_limit_is_rejected(self):
        async def oversized_body():
            for _ in range(180):
                yield b' ' * 65536
        response = await self.client.post('/chunk', data=oversized_body(), headers={
            'X-Telegram-Init-Data': 'synthetic', 'Content-Type': 'application/json'})
        self.assertEqual(response.status, 413, await response.text())
        self.storage.save_chunk.assert_not_awaited()


if __name__ == '__main__':
    unittest.main(verbosity=2)
