"""Actual delivery persistence functions, synthetic rows, no application imports."""
import ast
import json
import logging
import sys
import unittest
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[2]


class OversizeDelivery(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.task = SimpleNamespace(id=1, task_id='synthetic', telegram_id=123,
                                    status='completed', model='motion_control_v26', is_public_feed=False, result_url='https://example.test/result.mp4',
                                    request_data=json.dumps({'delivery_status': 'delivering', 'delivery_claimed_at': datetime.now(UTC).isoformat()}))
        self.ns = {'json': json, 'datetime': datetime, 'UTC': UTC, 'timedelta': timedelta,
                   'logger': logging.getLogger('test'), 'DATABASE_PATH': ':memory:'}
        exec(compile((ROOT / 'bot/services/delivery_state.py').read_text(), 'delivery_state.py', 'exec'), self.ns)  # noqa: S102 - fixed pure source only
        task = self.task

        class DB:
            async def execute(self, sql, args=()):
                if 'UPDATE generation_tasks' in sql:
                    if len(args) > 2 and task.request_data != args[-1]:
                        return SimpleNamespace(rowcount=0)
                    task.request_data = args[0]
                return SimpleNamespace(rowcount=1)

            async def commit(self):
                pass

        @asynccontextmanager
        async def connect(*args):
            yield DB()

        self.ns.update(db_backend=SimpleNamespace(connect=connect),
                       get_task_by_id=AsyncMock(return_value=task),
                       _parse_json_dict=lambda value: json.loads(value or '{}'),
                       mark_telegram_chat_available=AsyncMock())
        tree = ast.parse((ROOT / 'bot/database.py').read_text())
        nodes = [n for n in tree.body if isinstance(n, ast.AsyncFunctionDef)
                 and n.name in {'mark_task_delivery_status', 'claim_task_delivery', 'store_task_result_ready'}]
        exec(compile(ast.Module(body=nodes, type_ignores=[]), 'delivery-functions', 'exec'), self.ns)  # noqa: S102 - selected definitions, synthetic dependencies  # noqa: S102 - fixed pure source only

    async def mark(self, status, **kwargs):
        return await self.ns['mark_task_delivery_status']('synthetic', status, **kwargs)

    async def test_oversize_plus_confirmed_link_is_terminal_without_media_receipt(self):
        await self.mark('pending', error='telegram_media_too_large')
        await self.mark('link_sent')
        await self.mark('pending', error='temporary wrapper failure')
        metadata = json.loads(self.task.request_data)
        self.assertEqual(metadata['delivery_status'], 'link_delivered')
        self.assertTrue(metadata['delivery_link_sent'])
        self.assertTrue(metadata['delivery_media_too_large'])
        self.assertFalse(self.ns['has_retryable_result'](self.task))
        self.assertFalse(await self.ns['claim_task_delivery']('synthetic'))
        self.assertEqual(self.task.status, 'completed')
        self.assertEqual(self.task.result_url, 'https://example.test/result.mp4')

    async def test_previously_sent_link_becomes_terminal_only_after_size_proof(self):
        self.task.request_data = json.dumps({'delivery_status': 'pending', 'delivery_link_sent': True})
        await self.mark('pending', error='telegram_media_too_large')
        self.assertEqual(json.loads(self.task.request_data)['delivery_status'], 'link_delivered')

    async def test_failed_link_remains_retryable_and_preserves_oversize_evidence(self):
        await self.mark('pending', error='telegram_media_too_large')
        await self.mark('pending', error='temporary link failure')
        metadata = json.loads(self.task.request_data)
        self.assertEqual(metadata['delivery_status'], 'pending')
        self.assertTrue(metadata['delivery_media_too_large'])
        self.assertFalse(metadata.get('delivery_link_sent', False))
        self.assertTrue(self.ns['has_retryable_result'](self.task))

    async def test_transient_link_fallback_remains_retryable(self):
        await self.mark('link_sent')
        await self.mark('pending', error='network')
        self.assertTrue(self.ns['has_retryable_result'](self.task))
        self.assertNotIn('delivery_media_too_large', json.loads(self.task.request_data))

    async def test_normal_media_delivery_stays_delivered(self):
        await self.mark('delivered')
        self.assertEqual(json.loads(self.task.request_data)['delivery_status'], 'delivered')
        self.assertFalse(self.ns['has_retryable_result'](self.task))


    async def test_size_marker_does_not_release_active_link_lease(self):
        await self.mark('pending', error='telegram_media_too_large')
        self.assertEqual(json.loads(self.task.request_data)['delivery_status'], 'delivering')
        self.assertFalse(await self.ns['claim_task_delivery']('synthetic'))

    async def test_duplicate_result_callback_preserves_terminal_link(self):
        await self.mark('pending', error='telegram_media_too_large')
        await self.mark('link_sent')
        before = self.task.request_data
        self.assertTrue(await self.ns['store_task_result_ready']('synthetic', self.task.result_url))
        self.assertEqual(self.task.request_data, before)

    async def test_explicit_terminal_link_without_proof_rejected(self):
        with self.assertRaises(ValueError):
            await self.mark('link_delivered')

    async def test_watchdog_sql_excludes_terminal_link(self):
        import sqlite3

        with sqlite3.connect(':memory:') as db:
            db.execute('CREATE TABLE generation_tasks(status TEXT,result_url TEXT,request_data TEXT)')
            for state in ('link_delivered', 'pending', 'link_sent'):
                db.execute('INSERT INTO generation_tasks VALUES(?,?,?)', ('completed', 'synthetic', json.dumps({'delivery_status': state})))
            rows = db.execute('SELECT request_data FROM generation_tasks WHERE ' + self.ns['retryable_result_sql'](postgres=False)).fetchall()
        self.assertEqual([json.loads(row[0])['delivery_status'] for row in rows], ['pending', 'link_sent'])


class ActualRoute(OversizeDelivery):
    async def run_route(self, *, file_error=None, url_error=None, link_error=None, download_status=200):
        class BadRequest(Exception):
            pass

        class TooLarge(Exception):
            pass

        exceptions = ModuleType('aiogram.exceptions')
        exceptions.TelegramBadRequest = BadRequest
        exceptions.TelegramEntityTooLarge = TooLarge
        types = ModuleType('aiogram.types')
        types.FSInputFile = lambda value: SimpleNamespace(path=value)
        aiohttp = ModuleType('aiohttp')

        class Response:
            status = download_status

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

            async def iter_chunked(self, size):
                yield b'synthetic media'

            @property
            def content(self):
                return self

        class Session(Response):
            def get(self, *args, **kwargs):
                return Response()

        aiohttp.ClientSession = Session
        errors = {'oversize': TooLarge('Request entity too large'),
                  'urlsize': BadRequest('file is too big'), 'network': TimeoutError('timeout')}
        bot = SimpleNamespace(send_video=AsyncMock(side_effect=[errors.get(url_error), errors.get(file_error)]))
        link = AsyncMock(side_effect=TimeoutError('link failure') if link_error else None)
        complete = AsyncMock()
        self.ns.update(bot_instance=bot, task=self.task, task_id='synthetic', telegram_id=123,
                       result_url=self.task.result_url, is_video=True, service_name='Synthetic',
                       model_label='Motion', full_caption='ready', reference_preview_urls=[], kb_link=None,
                       web=SimpleNamespace(Response=lambda status: SimpleNamespace(status=status)),
                       _extract_task_request_data=lambda task: json.loads(task.request_data),
                       get_video_result_keyboard=lambda *a, **kw: None,
                       _task_callback_id=lambda task, task_id: task_id,
                       _build_single_result_caption=lambda text, *a: text,
                       _with_original_link=lambda text, *a: text,
                       _finish_result_with_unavailable_telegram=AsyncMock(return_value=False),
                       _is_terminal_telegram_delivery_error=lambda error: False,
                       _send_plain_result_link=link, complete_video_task=complete)
        tree = ast.parse((ROOT / 'bot/main.py').read_text())
        handler = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == 'handle_kie_ai_webhook')
        block = next(n for n in ast.walk(handler) if isinstance(n, ast.Try) and n.body
                     and isinstance(n.body[0], ast.ImportFrom) and n.body[0].module == 'bot.services.delivery_state')
        function = ast.AsyncFunctionDef(name='actual_delivery_block', args=ast.arguments(posonlyargs=[], args=[], kwonlyargs=[], kw_defaults=[], defaults=[]), body=[block], decorator_list=[])
        module = ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[]))
        exec(compile(module, 'actual-kie-delivery-block', 'exec'), self.ns)  # noqa: S102 - actual route block, fake sends
        delivery = ModuleType('bot.services.delivery_state')
        delivery.is_telegram_media_too_large = self.ns['is_telegram_media_too_large']
        with patch.dict(sys.modules, {'aiogram.exceptions': exceptions, 'aiogram.types': types,
                                     'aiohttp': aiohttp, 'bot.services.delivery_state': delivery}):
            result = await self.ns['actual_delivery_block']()
        return result, bot, link, complete

    async def test_actual_file_oversize_link_success_finishes(self):
        _, bot, link, complete = await self.run_route(url_error='network', file_error='oversize')
        self.assertEqual(bot.send_video.await_count, 2)
        link.assert_awaited_once()
        complete.assert_not_awaited()
        self.assertEqual(json.loads(self.task.request_data)['delivery_status'], 'link_delivered')

    async def test_actual_failed_link_then_restart_retries_only_link(self):
        await self.run_route(url_error='network', file_error='oversize', link_error=True)
        metadata = json.loads(self.task.request_data)
        self.assertEqual(metadata['delivery_status'], 'pending')
        self.assertTrue(metadata['delivery_media_too_large'])
        self.assertTrue(await self.ns['claim_task_delivery']('synthetic'))
        _, bot, link, _ = await self.run_route()
        bot.send_video.assert_not_awaited()
        link.assert_awaited_once()
        self.assertEqual(json.loads(self.task.request_data)['delivery_status'], 'link_delivered')

    async def test_actual_prior_link_is_not_resent(self):
        self.task.request_data = json.dumps({'delivery_status': 'delivering', 'delivery_link_sent': True})
        _, _, link, _ = await self.run_route(url_error='network', file_error='oversize')
        link.assert_not_awaited()
        self.assertEqual(json.loads(self.task.request_data)['delivery_status'], 'link_delivered')

    async def test_url_size_rejection_can_still_upload_media(self):
        _, bot, link, complete = await self.run_route(url_error='urlsize')
        self.assertEqual(bot.send_video.await_count, 2)
        link.assert_not_awaited()
        complete.assert_awaited_once()
        self.assertEqual(json.loads(self.task.request_data)['delivery_status'], 'delivered')

    async def test_url_size_plus_download_failure_remains_retryable(self):
        await self.run_route(url_error='urlsize', download_status=503)
        metadata = json.loads(self.task.request_data)
        self.assertEqual(metadata['delivery_status'], 'pending')
        self.assertNotIn('delivery_media_too_large', metadata)



if __name__ == '__main__':
    unittest.main()
