"""Admin editing and Seedance success accounting at the HTTP/runtime seams."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiohttp import web


@pytest.fixture(autouse=True)
def isolated_database():
    yield


async def test_seedance_dispatch_links_success_even_with_production_hook_order(monkeypatch):
    from bot import trend_api
    from bot.handlers import trend_seedance_25_compat as seedance
    from bot.handlers import trend_success_compat as metrics

    link = AsyncMock(return_value=True)
    monkeypatch.setattr(metrics, "register_trend_generation_run", link)
    monkeypatch.setattr(seedance, "_run_seedance25_trend", AsyncMock(return_value=web.json_response(
        {"ok": True, "task_id": "seedance-test-task"}
    )))
    await trend_api._run_video_trend(telegram_id=123, user=SimpleNamespace(id=7),
        trend=SimpleNamespace(model="seedance_2_5", trend_id=42))
    link.assert_awaited_once_with(task_id="seedance-test-task", trend_id=42, user_id=7)


async def test_content_requires_admin_before_reading_private_prompt(monkeypatch):
    from bot import miniapp
    from bot import trend_preview_admin as api
    monkeypatch.setattr(miniapp, "_get_user_context", AsyncMock(return_value=(123, {})))
    read = AsyncMock()
    monkeypatch.setattr(api, "get_prompt_by_id", read)
    response = await api.miniapp_admin_trend_content(SimpleNamespace(app={}, json=AsyncMock(return_value={"prompt_id": 42})))
    assert response.status == 403
    read.assert_not_awaited()

@pytest.fixture
async def editor(monkeypatch, tmp_path):
    import json

    import aiosqlite

    from bot import miniapp
    from bot import trend_preview_admin as api
    path = tmp_path / 'editor.db'
    async with aiosqlite.connect(path) as db:
        await db.execute('CREATE TABLE user_prompts (id INTEGER PRIMARY KEY, title TEXT, prompt_text TEXT, generation_settings TEXT, updated_at TEXT, preview_url TEXT, uses_count INTEGER)')
        await db.execute('INSERT INTO user_prompts VALUES (42, ?, ?, ?, NULL, ?, 9)',
                         ('Old title', 'Use @Image1 in a garden', '{}', '/uploads/preview.mp4'))
        await db.commit()
    async def read(prompt_id):
        async with aiosqlite.connect(path) as db:
            db.row_factory = aiosqlite.Row
            row = await (await db.execute('SELECT * FROM user_prompts WHERE id=?', (prompt_id,))).fetchone()
            if not row:
                return None
            result = dict(row)
            result.update(tags=['trend'], model='seedance_2_5')
            result['generation_settings'] = json.loads(result['generation_settings'])
            return result
    monkeypatch.setattr(api, 'get_prompt_by_id', read)
    monkeypatch.setattr(api.db_backend, 'connect', lambda *a, **kw: aiosqlite.connect(path))
    monkeypatch.setattr(miniapp, '_get_user_context', AsyncMock(return_value=(999999999, {})))
    async def call(**body):
        response = await api.miniapp_admin_trend_content(SimpleNamespace(app={}, json=AsyncMock(return_value={'prompt_id': 42, **body})))
        return response.status, json.loads(response.body)
    return call, read


async def test_admin_reads_edits_and_reopens_without_losing_preview_or_counters(editor):
    call, read = editor
    status, payload = await call()
    assert status == 200
    content = payload['content']
    assert content['prompt_text'] == 'Use @Image1 in a garden'
    status, result = await call(op='update', revision=content['revision'], title='New title', prompt_text='Use @Image1 on a beach')
    assert status == 200
    assert result['content']['prompt_text'] == 'Use @Image1 on a beach'
    _, reopened = await call()
    assert reopened['content']['title'] == 'New title'
    stored = await read(42)
    assert stored['preview_url'] == '/uploads/preview.mp4'
    assert stored['uses_count'] == 9
    # Another editor cannot overwrite the newer content with a stale form.
    status, _ = await call(op='update', revision=content['revision'], title='Stale title')
    assert status == 409


@pytest.mark.parametrize('text', ['', 'No references', 'Use @Image1 and @Video99', 'x' * 30001])
async def test_invalid_edit_leaves_original_intact(editor, text):
    call, read = editor
    _, payload = await call()
    status, _ = await call(op='update', revision=payload['content']['revision'], title='Changed', prompt_text=text)
    assert status == 400
    assert (await read(42))['title'] == 'Old title'


async def test_public_serializer_still_hides_admin_prompt_and_counters(editor):
    from bot.trend_visibility import sanitize_prompt_for_public
    _, read = editor
    private = {**await read(42), 'successful_runs_count': 9}
    public = sanitize_prompt_for_public(private)
    assert public['prompt_text'] == ''
    assert 'successful_runs_count' not in public
    assert 'uses_count' not in public

@pytest.mark.parametrize('raw, expected', [
    ('{"action_type":"trend","trend_id":42,"prompt_source_id":42}', 42),
    ('{"action_type":"trend","trend_id":42,"prompt_source_id":43}', None),
    ('{"action_type":"repeat","trend_id":42,"prompt_source_id":42}', None),
    ('{"action_type":"trend","trend_id":true,"prompt_source_id":true}', None),
    ('{"action_type":"trend","source":"trend","trend_id":42}', 42),
    ('{"action_type":"trend","trend_id":42}', None),
    ('broken json', None), ('[]', None), (None, None),
])
def test_reconciliation_uses_only_matching_persisted_trend_ids(raw, expected):
    from scripts.reconcile_seedance_trend_runs import source_trend_id
    assert source_trend_id(raw) == expected


def test_every_editable_model_has_a_bounded_prompt():
    from bot.trend_preview_admin import _validate_content_prompt
    with pytest.raises(ValueError):
        _validate_content_prompt({'model': 'banana_pro', 'prompt_text': 'old'}, 'x' * 30001)


async def test_content_audit_is_atomic_private_and_append_only(editor):
    import json

    from bot import trend_preview_admin as api
    call, _ = editor
    _, payload = await call()
    status, _ = await call(op='update', revision=payload['content']['revision'], title='New title', prompt_text='Use @Image1 on a beach')
    assert status == 200
    async with api.db_backend.connect() as db:
        row = await (await db.execute('SELECT action, before_state, after_state FROM trend_catalog_audit')).fetchone()
        assert row[0] == 'content_edit'
        assert json.loads(row[1])['title'] == 'Old title'
        assert json.loads(row[2])['title'] == 'New title'
        assert 'garden' not in row[1] and 'beach' not in row[2]
        with pytest.raises(Exception, match='append-only'):
            await db.execute('DELETE FROM trend_catalog_audit')


@pytest.mark.parametrize('raw, expected', [('broken', False), ('{}', False), ('["trend"]', True)])
def test_reconciliation_skips_bad_tags(raw, expected):
    from scripts.reconcile_seedance_trend_runs import has_trend_tag
    assert has_trend_tag(raw) is expected

async def test_audit_failure_rolls_back_content_change(editor, monkeypatch):
    from bot import trend_catalog_audit
    call, read = editor
    _, payload = await call()
    monkeypatch.setattr(trend_catalog_audit, 'append', AsyncMock(side_effect=RuntimeError('audit unavailable')))
    status, _ = await call(op='update', revision=payload['content']['revision'], title='Must rollback')
    assert status == 500
    assert (await read(42))['title'] == 'Old title'
