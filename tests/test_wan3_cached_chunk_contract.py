"""Run standalone with unittest: no app imports, database, network provider or credentials."""
from __future__ import annotations

import ast
import base64
import hashlib
import io
import json
import logging
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

CHUNK_SIZE = 7 * 1024 * 1024
ENCODED_LIMIT = 4 * ((CHUNK_SIZE + 2) // 3)
BODY_LIMIT = ENCODED_LIMIT + 16 * 1024
ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'bot' / 'wan3_prime_api.py'

class ValidationError(ValueError):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status

class LifecycleError(Exception):
    def __init__(self, message, status=400, code='wan3_error'):
        super().__init__(message)
        self.status, self.code = status, code

class LogCapture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lines = []
    def emit(self, record):
        self.lines.append(record.getMessage())

class Storage:
    def __init__(self):
        self.saved = []
    async def save_chunk(self, actor, *, upload_id, index, total, chunk):
        self.saved.append((actor.telegram_id, upload_id, index, total, len(chunk), hashlib.sha256(chunk).hexdigest()))

class Stream:
    def __init__(self, raw):
        self.raw, self.reads = raw, 0
    async def iter_chunked(self, size):
        for offset in range(0, len(self.raw), size):
            self.reads += 1
            yield self.raw[offset:offset + size]

class Request(dict):
    def __init__(self, body, *, cached, content_length=None):
        super().__init__()
        self.content_type = 'application/json'
        self.content_length = content_length
        self._read_bytes = body if cached else None
        self.content = Stream(b'' if cached else body)

class CachedChunkContract(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        stub = types.ModuleType('bot.services.wan3_prime_storage')
        stub.CHUNK_SIZE = CHUNK_SIZE
        self.modules = patch.dict(sys.modules, {'bot.services.wan3_prime_storage': stub})
        self.modules.start()
        self.addCleanup(self.modules.stop)
        self.storage = Storage()
        self.logger = logging.getLogger(f'wan-chunk-test-{id(self)}')
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False
        self.capture = LogCapture()
        self.logger.addHandler(self.capture)
        self.addCleanup(self.logger.removeHandler, self.capture)
        self.actor_calls = 0
        async def actor(request, body):
            self.actor_calls += 1
            if body.get('init_data') != 'signed-fixture':
                raise LifecycleError('Invalid auth fixture', status=401, code='auth_invalid')
            return types.SimpleNamespace(user_id=22, telegram_id=1001)
        def error(message, *, status=400, code='wan3_error'):
            return web.json_response({'ok': False, 'error': message, 'code': code}, status=status)
        tree = ast.parse(SOURCE.read_text())
        nodes = [node for node in tree.body if isinstance(node, ast.AsyncFunctionDef)
                 and node.name in {'_read_upload_chunk', '_upload_chunk_route'}]
        self.assertEqual(len(nodes), 2)
        self.ns = {'web': web, 'Any': object, 'Wan3PrimeValidationError': ValidationError,
                   'Wan3PrimeLifecycleError': LifecycleError, 'logger': self.logger,
                   '_actor_from_request': actor, 'wan3_prime_storage': self.storage,
                   '_json_error': error, '_json_ok': web.json_response}
        exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SOURCE), 'exec'), self.ns)  # noqa: S102 - isolated actual route, no application imports

    def payload(self, data=b'owned fixture'):
        return {'upload_id': 'a' * 32, 'index': 0, 'total': 1,
                'chunk_base64': base64.b64encode(data).decode()}

    async def http(self, raw, *, preread=None, auth=True, chunked=False):
        @web.middleware
        async def consume(request, handler):
            if preread == 'json':
                await request.json()
            elif preread == 'read':
                await request.read()
            return await handler(request)
        app = web.Application(client_max_size=220 * 1024 * 1024, middlewares=[consume])
        app.router.add_post('/chunk', self.ns['_upload_chunk_route'])
        headers = {'Content-Type': 'application/json'}
        if auth:
            headers['X-Telegram-Init-Data'] = 'signed-fixture'
        async with TestClient(TestServer(app)) as client:
            response = await client.post('/chunk', data=io.BytesIO(raw), headers=headers, **({'chunked': True} if chunked else {}))
            body = await response.read()
            return response.status, json.loads(body), len(body)

    async def test_stream_and_preread_json_and_bytes_save_identical_owned_chunk(self):
        data = b'owned-file-bytes\x00\xff'
        raw = json.dumps(self.payload(data)).encode()
        for preread in (None, 'read', 'json'):
            with self.subTest(preread=preread):
                status, body, _ = await self.http(raw, preread=preread)
                self.assertEqual(status, 200)
                self.assertEqual(body, {'ok': True})
        self.assertEqual(len(self.storage.saved), 3)
        self.assertEqual(self.storage.saved[0], self.storage.saved[1])
        self.assertEqual(self.storage.saved[1], self.storage.saved[2])
        self.assertEqual(self.storage.saved[0][0], 1001)

    async def test_chunked_json_without_content_length_is_supported_in_both_paths(self):
        raw = json.dumps(self.payload()).encode()
        for preread in (None, 'read'):
            self.assertEqual((await self.http(raw, preread=preread, chunked=True))[0], 200)
        self.assertEqual(self.storage.saved[0], self.storage.saved[1])

    async def test_unauthorized_request_never_calls_actor_or_storage(self):
        for preread in (None, 'read'):
            status, body, _ = await self.http(json.dumps(self.payload()).encode(), preread=preread, auth=False)
            self.assertEqual(status, 401)
            self.assertEqual(body['code'], 'auth_required')
        self.assertEqual(self.actor_calls, 0)
        self.assertEqual(self.storage.saved, [])

    async def test_malformed_json_and_utf8_rejected_with_same_code_in_both_paths(self):
        for raw in (b'{', b'\xff', b''):
            for preread in (None, 'read'):
                with self.subTest(raw=repr(raw), preread=preread):
                    status, body, size = await self.http(raw, preread=preread)
                    self.assertEqual((status, body['code'], size), (400, 'validation_error', 226))
        self.assertEqual(self.storage.saved, [])

    async def test_duplicate_fields_rejected_in_both_paths(self):
        raw = json.dumps(self.payload())[:-1] + ',"index":0}'
        for preread in (None, 'read'):
            self.assertEqual((await self.http(raw.encode(), preread=preread))[0], 400)
        self.assertEqual(self.storage.saved, [])

    async def test_strict_base64_unknown_fields_and_boolean_indexes_preserved(self):
        payloads = [dict(self.payload(), chunk_base64='***'), dict(self.payload(), chunk_base64='Zg==\n'),
                    dict(self.payload(), chunk_base64='é'), dict(self.payload(), index=True),
                    dict(self.payload(), extra='not permitted')]
        for payload in payloads:
            for preread in (None, 'read'):
                self.assertEqual((await self.http(json.dumps(payload).encode(), preread=preread))[0], 400)
        self.assertEqual(self.storage.saved, [])

    async def test_cached_and_stream_actual_body_caps_ignore_missing_or_false_content_length(self):
        body = b' ' * (BODY_LIMIT + 1)
        for cached in (False, True):
            for content_length in (None, 1):
                request = Request(body, cached=cached, content_length=content_length)
                with self.assertRaises(ValidationError) as caught:
                    await self.ns['_read_upload_chunk'](request)
                self.assertEqual(caught.exception.status, 413)
                if cached:
                    self.assertEqual(request.content.reads, 0)
        self.assertEqual(self.storage.saved, [])

    async def test_cached_body_actual_length_is_checked_even_with_small_content_length(self):
        request = Request(b' ' * (BODY_LIMIT + 1), cached=True, content_length=2)
        with self.assertRaises(ValidationError) as caught:
            await self.ns['_read_upload_chunk'](request)
        self.assertEqual(caught.exception.status, 413)
        self.assertEqual(request._wan3_chunk_cached_bytes, BODY_LIMIT + 1)
        self.assertEqual(request._wan3_chunk_wire_bytes, BODY_LIMIT + 1)

    async def test_encoded_and_decoded_limits_apply_to_both_paths(self):
        too_long_encoded = dict(self.payload(), chunk_base64='A' * (ENCODED_LIMIT + 4))
        too_long_decoded = self.payload(b'x' * (CHUNK_SIZE + 1))
        self.assertLessEqual(len(too_long_decoded['chunk_base64']), ENCODED_LIMIT)
        for payload in (too_long_encoded, too_long_decoded):
            raw = json.dumps(payload).encode()
            for preread in (None, 'read'):
                status, body, _ = await self.http(raw, preread=preread)
                self.assertEqual((status, body['code']), (413, 'validation_error'))
        self.assertEqual(self.storage.saved, [])

    async def test_exact_decoded_chunk_limit_is_accepted_in_both_paths(self):
        raw = json.dumps(self.payload(b'x' * CHUNK_SIZE)).encode()
        for preread in (None, 'read'):
            self.assertEqual((await self.http(raw, preread=preread))[0], 200)
        self.assertEqual(self.storage.saved[0], self.storage.saved[1])
        self.assertEqual(self.storage.saved[0][4], CHUNK_SIZE)

    async def test_metadata_logs_do_not_include_body_auth_filename_url_or_exception_text(self):
        secret = b'{"filename":"PRIVATE-FILENAME","prompt":"PRIVATE-PROMPT","url":"https://private.invalid/TOKEN",'
        await self.http(secret, preread='read')
        await self.http(json.dumps(self.payload()).encode(), preread='read')
        logs = '\n'.join(self.capture.lines)
        self.assertIn('transport=json', logs)
        self.assertIn('telegram_id=1001', logs)
        self.assertIn('JSONDecodeError', logs)
        self.assertIn('cached_bytes=', logs)
        for forbidden in ('PRIVATE-', 'private.invalid', 'signed-fixture', 'Expecting', 'chunk_base64'):
            self.assertNotIn(forbidden, logs)

if __name__ == '__main__':
    unittest.main(verbosity=2)
