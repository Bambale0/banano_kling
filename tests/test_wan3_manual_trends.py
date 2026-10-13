"""Full application/SQLite publication tests; executed by maintained CI only."""
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from PIL import Image

from bot import database
from bot.services.wan3_prime_lifecycle import Wan3PrimeActor
from bot.services.wan3_prime_media import Wan3PrimeValidationError
from bot.services.wan3_prime_repeat import compile_repeat, public_plan
from bot.services.wan3_prime_storage import wan3_prime_probe, wan3_prime_storage
from bot.services.wan3_prime_trends import get_trend_plan, publish_manual_trend


async def setup_publication(monkeypatch, tmp_path, model='wan_3'):
    from bot.config import config
    from bot.handlers import trend_success_compat

    monkeypatch.setattr(trend_success_compat, 'DATABASE_PATH', database.DATABASE_PATH)
    monkeypatch.setattr(trend_success_compat, '_SCHEMA_READY', False)
    monkeypatch.setattr(trend_success_compat, '_SCHEMA_LOCK', None)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(type(config), 'static_base_url', property(lambda _self: 'https://owned.test'))
    user = await database.get_or_create_user(717171)
    actor = Wan3PrimeActor(user.id, user.telegram_id, is_admin=True)
    urls = []
    for index in range(2):
        path = tmp_path / f'input-{index}.png'
        Image.new('RGB', (320, 240), (index * 50, 30, 40)).save(path)
        media = await wan3_prime_storage.save_owned_file(actor, kind='image', filename=path.name, path=path)
        urls.append(media['url'])
    recipe = {'model': model, 'prompt': 'PRIVATE Image1 beside Image2', 'scenario': 'reference', 'resolution': '720P',
                  'aspect_ratio': '9:16', 'duration': 5, 'audio': True, 'nsfw_checker': False, 'reference_image_urls': urls}
    settings = {'model': model, 'preview_type': 'video', 'wan3_recipe': recipe, 'wan3_replacement_keys': ['image:0']}
    kwargs = {'model': model, 'prompt': recipe['prompt'], 'settings': settings, 'title': 'Synthetic trend', 'description': '',
                  'preview_url': 'https://owned.test/preview.mp4'}
    return actor, kwargs


@pytest.mark.asyncio
@pytest.mark.parametrize('model', ['wan_3', 'wan_3_prime'])
async def test_manual_publish_plan_and_replacement_keep_private_recipe(monkeypatch, tmp_path, model):
    actor, kwargs = await setup_publication(monkeypatch, tmp_path, model)
    created = await publish_manual_trend(actor, **kwargs)
    again = await publish_manual_trend(actor, **kwargs)
    assert again['trend_id'] == created['trend_id'] and again['replayed']
    prompt = await database.get_prompt_by_id(created['trend_id'])
    assert prompt['model'] == model
    async with database.db_backend.connect(database.DATABASE_PATH) as db:
        original = await (await db.execute('SELECT source_generation_id FROM user_prompts WHERE id = ?', (created['trend_id'],))).fetchone()
    assert original[0] is None
    assert 'PRIVATE' not in str(prompt) and 'input-' not in str(prompt)
    plan = await get_trend_plan(actor, created['trend_id'])
    public = public_plan(plan)
    assert [slot['binding'] for slot in public['slots']] == ['upload', 'fixed']
    assert 'PRIVATE' not in str(public) and 'owned.test' not in str(public)
    viewer = SimpleNamespace(user_id=actor.user_id + 100, telegram_id=818181)
    request = {**public['recipe'], 'trend_id': created['trend_id'], 'repeat_plan_hash': public['repeat_plan_hash'],
               'repeat_replacements': {'image:0': 'https://viewer.test/own.png'}}
    compiled, _, _, _ = await compile_repeat(viewer, request, wan3_prime_probe)
    assert compiled['reference_image_urls'] == ['https://viewer.test/own.png', kwargs['settings']['wan3_recipe']['reference_image_urls'][1]]
    assert compiled['prompt'] == kwargs['prompt']
    # Stored recipe pins inputs through ordinary cleanup, including temporary
    # author inputs which will be replaced by the viewer later.
    async with database.db_backend.connect(database.DATABASE_PATH) as db:
        await db.execute("UPDATE wan3_prime_media SET created_at = '2000-01-01'")
        await db.commit()
    from bot.services.wan3_prime_retention import cleanup_expired
    assert (await cleanup_expired())['removed_media'] == 0
    await database.deactivate_prompt(created['trend_id'], author_id=actor.user_id)
    assert (await publish_manual_trend(actor, **kwargs))['replayed']
    with pytest.raises(Wan3PrimeValidationError):
        await get_trend_plan(actor, created['trend_id'])


@pytest.mark.asyncio
async def test_foreign_media_and_nonadmin_rejected_before_publication(monkeypatch, tmp_path):
    actor, kwargs = await setup_publication(monkeypatch, tmp_path)
    for stranger in (Wan3PrimeActor(actor.user_id, actor.telegram_id, is_admin=False),
                     Wan3PrimeActor(actor.user_id + 1, actor.telegram_id + 1, is_admin=True)):
        with pytest.raises(Wan3PrimeValidationError) as error:
            await publish_manual_trend(stranger, **kwargs)
        assert error.value.status == 403
    async with database.db_backend.connect(database.DATABASE_PATH) as db:
        count = await (await db.execute('SELECT COUNT(*) FROM user_prompts')).fetchone()
    assert count[0] == 0


@pytest.mark.asyncio
async def test_recipe_insert_failure_rolls_back_public_prompt(monkeypatch, tmp_path):
    actor, kwargs = await setup_publication(monkeypatch, tmp_path)
    from bot.services import wan3_prime_trends as trends
    await trends.init_trend_schema()
    async with database.db_backend.connect(database.DATABASE_PATH) as db:
        await db.execute("CREATE TRIGGER reject_manual_recipe BEFORE INSERT ON wan3_prime_trend_recipes BEGIN SELECT RAISE(ABORT, 'synthetic failure'); END")
        await db.commit()
    with pytest.raises(Exception, match='synthetic failure'):
        await publish_manual_trend(actor, **kwargs)
    async with database.db_backend.connect(database.DATABASE_PATH) as db:
        assert (await (await db.execute('SELECT COUNT(*) FROM user_prompts')).fetchone())[0] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('model', ['wan_3', 'wan_3_prime'])
@pytest.mark.parametrize('installer', ['active', 'video', 'legacy'])
async def test_generic_submit_routes_wan_before_legacy_create(monkeypatch, tmp_path, model, installer):
    from bot import miniapp
    actor, kwargs = await setup_publication(monkeypatch, tmp_path, model)
    user = await database.get_or_create_user(actor.telegram_id)
    monkeypatch.setattr(miniapp.config, 'is_admin', lambda tid: tid == actor.telegram_id)
    monkeypatch.setattr(miniapp, '_get_user_context', AsyncMock(return_value=(actor.telegram_id, {'user': user})))
    body = {'init_data': 'synthetic', 'model': model, 'prompt_text': '  ' + kwargs['prompt'] + '  ', 'title': kwargs['title'],
            'description': '', 'preview_url': kwargs['preview_url'], 'tags': ['trend', 'trend-video'],
            'generation_settings': kwargs['settings']}
    body['generation_settings']['wan3_recipe']['prompt'] = '  ' + kwargs['prompt'] + '  '
    monkeypatch.setattr(miniapp, '_miniapp_payload', AsyncMock(return_value=body))
    legacy = AsyncMock(side_effect=AssertionError('WAN cannot create a generic orphan'))
    monkeypatch.setattr(miniapp, 'create_prompt', legacy)
    module = SimpleNamespace(**vars(miniapp))
    if installer == 'video':
        from bot.handlers.trend_video_compat import _install_miniapp_video_submit
        _install_miniapp_video_submit(module)
    elif installer == 'legacy':
        from bot.handlers.trends_compat import _install_miniapp_trends
        _install_miniapp_trends(module)
    response = await module.miniapp_prompt_submit(SimpleNamespace(app={}))
    assert response.status == 200, response.text
    import json
    published = json.loads(response.text)['prompt']
    assert (await get_trend_plan(actor, published['id']))['recipe']['model'] == model
    legacy.assert_not_called()
    broken = deepcopy(body)
    broken['generation_settings'].pop('wan3_recipe')
    monkeypatch.setattr(miniapp, '_miniapp_payload', AsyncMock(return_value=broken))
    module._miniapp_payload = miniapp._miniapp_payload
    response = await module.miniapp_prompt_submit(SimpleNamespace(app={}))
    assert response.status == 400
    legacy.assert_not_called()


@pytest.mark.asyncio
async def test_manual_submit_unexpected_storage_error_is_not_public(monkeypatch):
    from bot import miniapp
    from bot.services import wan3_prime_trends

    monkeypatch.setattr(miniapp.config, 'is_admin', lambda _tid: True)
    monkeypatch.setattr(wan3_prime_trends, 'publish_manual_trend',
                        AsyncMock(side_effect=RuntimeError('internal-provider-secret-location')))
    response = await miniapp._miniapp_publish_wan_trend(
        {'model': 'wan_3', 'prompt_text': 'A landscape', 'generation_settings': {}},
        717171, SimpleNamespace(id=1),
    )
    assert response.status == 500
    assert 'internal-provider-secret-location' not in response.text
    assert 'wan_publication_unavailable' in response.text
