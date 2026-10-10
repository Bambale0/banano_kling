from pathlib import Path

import pytest

from bot import database
from bot.services.wan3_prime_lifecycle import Wan3PrimeActor, Wan3PrimeLifecycle
from tests.test_wan3_prime_lifecycle import (
    Downloader,
    Prices,
    Probe,
    Provider,
    balance,
    body,
    user_actor,
)


@pytest.mark.asyncio
async def test_curated_wan_edit_preserves_all_media_and_uses_same_lifecycle(monkeypatch, tmp_path):
    from bot.handlers import trend_success_compat
    from bot.services import wan3_prime_trends as trends
    from bot.services.wan3_prime_repeat import public_plan
    monkeypatch.setattr(trend_success_compat, "DATABASE_PATH", database.DATABASE_PATH)
    monkeypatch.chdir(tmp_path)
    owner = await user_actor(100, telegram_id=7111)
    admin = Wan3PrimeActor(owner.user_id, owner.telegram_id, is_admin=True)
    provider = Provider()
    lifecycle = Wan3PrimeLifecycle(probe=Probe(file_duration=5), preset_manager=Prices(), transport=provider,
                                  downloader=Downloader(Path('static/uploads/wan3_prime/results/trend.mp4')))
    recipe = body(scenario='edit', prompt='PRIVATE AUTHOR INSTRUCTIONS. Replace Video1 character from Image1.',
                  duration=5, seed=0, audio=False, nsfw_checker=True,
                  reference_image_urls=['https://owned.test/author.png'],
                  reference_video_urls=['https://owned.test/source.mp4'],
                  reference_audio_urls=['https://owned.test/sound.mp3'],
                  reference_file_urls=['https://owned.test/brief.txt'])
    quote = await lifecycle.quote(admin, recipe)
    source = await lifecycle.launch(admin, recipe, quote, 'original-trend')
    await database.complete_video_task(source['task_id'], 'https://owned.test/preview.mp4')
    created = await trends.publish_trend(admin, task_id=source['task_id'], title='Full editor trend',
        description='Replace the subject', replacement_keys=['image:0'])
    repeated_publish = await trends.publish_trend(admin, task_id=source['task_id'], title='Full editor trend',
        description='Replace the subject', replacement_keys=['image:0'])
    assert created['trend_id'] == repeated_publish['trend_id']
    prompt = await database.get_prompt_by_id(created['trend_id'], approved_public_only=True)
    assert prompt['model'] == 'wan_3_prime'
    assert prompt['generation_settings']['wan3_recipe_version'] == 1
    viewer = await user_actor(100, telegram_id=7222)
    plan = public_plan(await trends.get_trend_plan(viewer, created['trend_id']))
    assert 'PRIVATE AUTHOR' not in str(plan)
    assert 'source.mp4' not in str(plan)
    request = {**plan['recipe'], 'trend_id': created['trend_id'], 'repeat_plan_hash': plan['repeat_plan_hash'],
               'repeat_replacements': {'image:0': 'https://owned.test/repeater.png'}}
    provider.create_result = {'success': True, 'task_id': 'provider_2'}
    quote = await lifecycle.quote(viewer, request)
    launched = await lifecycle.launch(viewer, request, quote, 'wan-trend-repeat')
    assert provider.recipe.reference_video_urls == recipe['reference_video_urls']
    assert provider.recipe.reference_audio_urls == recipe['reference_audio_urls']
    assert provider.recipe.reference_file_urls == recipe['reference_file_urls']
    assert provider.recipe.reference_image_urls == ['https://owned.test/repeater.png']
    assert provider.recipe.seed == 0 and provider.recipe.audio is False
    assert 'PRIVATE AUTHOR' in provider.recipe.prompt
    public_restore = await lifecycle.owner_recipe(viewer, launched['task_id'])
    assert public_restore['trend_id'] == created['trend_id']
    assert 'PRIVATE AUTHOR' not in str(public_restore)
    task = await database.get_task_by_id(launched['task_id'])
    assert task.action_type == 'trend'
    provider.statuses['provider_2'] = {'taskId': 'provider_2', 'state': 'success', 'resultUrls': ['https://owned.test/done.mp4']}
    await lifecycle.reconcile_once(provider_task_id='provider_2')
    await lifecycle.reconcile_once(provider_task_id='provider_2')
    assert await balance(viewer.user_id) == 80
    async with database.db_backend.connect(database.DATABASE_PATH) as db:
        count = await (await db.execute('SELECT COUNT(*) FROM prompt_repeat_events WHERE source_type = ? AND source_id = ?', ('prompt', created['trend_id']))).fetchone()
        runs = await (await db.execute('SELECT COUNT(*) FROM trend_generation_runs WHERE trend_id = ?', (created['trend_id'],))).fetchone()
    assert count[0] == 1 and runs[0] == 1


@pytest.mark.asyncio
async def test_non_admin_cannot_publish_wan_trend():
    from bot.services import wan3_prime_trends as trends
    from bot.services.wan3_prime_media import Wan3PrimeValidationError
    actor = await user_actor()
    with pytest.raises(Wan3PrimeValidationError) as error:
        await trends.publish_trend(actor, task_id='missing', title='No', description='', replacement_keys=[])
    assert error.value.status == 403
