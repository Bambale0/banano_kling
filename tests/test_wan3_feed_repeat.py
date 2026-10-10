"""Public Wan repeats retain roles without revealing or re-granting originals."""
import json

import pytest

from bot import database, trend_task_privacy
from bot.services.wan3_prime_lifecycle import Wan3PrimeLifecycle
from bot.services.wan3_prime_media import Wan3PrimeValidationError
from bot.services.wan3_prime_repeat import get_repeat_plan, public_plan
from tests.test_wan3_prime_lifecycle import Prices, Probe, Provider, balance, user_actor

OWNER_FACE = 'https://owner.example/face.png'
FIXED = 'https://owner.example/fixed.png'
VIDEO = 'https://owner.example/source.mp4'
USER_FACE = 'https://viewer.example/person.png'
SECRET = 'Author private editing recipe: use Image1 identity and Image2 clothing on Video1'


async def published_source():
    owner = await user_actor(100, telegram_id=991201)
    await database.add_generation_task(owner.user_id, owner.telegram_id, 'wan3_author_source', 'video', 'wan_3_prime',
        model='wan_3_prime', prompt=SECRET, duration=5, cost=10,
        request_data={'v_model':'wan_3_prime', 'scenario':'edit', 'prompt':SECRET,
            'reference_images':[OWNER_FACE, FIXED], 'reference_image_urls':[OWNER_FACE, FIXED],
            'reference_video_urls':[VIDEO], 'reference_audio_urls':[], 'reference_file_urls':[], 'reference_link_urls':[],
            'resolution':'720P', 'duration':5, 'audio':False, 'seed':0, 'aspect_ratio':'9:16', 'nsfw_checker':True})
    await database.complete_video_task('wan3_author_source', 'https://result.example/video.mp4')
    card = await database.share_to_feed('wan3_author_source', owner.user_id, references_visible=False,
                                        repeat_reference_image_indices=[1], repeat_reference_video_indices=[0])
    return owner, card['id']


@pytest.mark.asyncio
async def test_feed_repeat_preserves_video1_and_hides_author_materials():
    _owner, source_id = await published_source()
    actor = await user_actor(100, telegram_id=991202)
    provider = Provider()
    lifecycle = Wan3PrimeLifecycle(probe=Probe(), preset_manager=Prices(), transport=provider)
    plan = public_plan(await get_repeat_plan(actor, source_id))
    assert OWNER_FACE not in json.dumps(plan) and FIXED not in json.dumps(plan) and SECRET not in json.dumps(plan)
    recipe = {**plan['recipe'], 'source_feed_gen_id':source_id, 'repeat_plan_hash':plan['repeat_plan_hash'],
              'repeat_replacements':{'image:0':USER_FACE}, 'prompt':'Make the jacket blue'}
    quote = await lifecycle.quote(actor, recipe)
    launched = await lifecycle.launch(actor, recipe, quote, 'repeat-once')
    assert provider.recipe.reference_video_urls == [VIDEO]
    assert provider.recipe.reference_image_urls == [USER_FACE, FIXED]
    assert SECRET in provider.recipe.prompt and 'Make the jacket blue' in provider.recipe.prompt
    restored = await lifecycle.owner_recipe(actor, launched['task_id'])
    assert SECRET not in json.dumps(restored) and FIXED not in json.dumps(restored) and VIDEO not in json.dumps(restored)
    assert restored['source_feed_gen_id'] == source_id
    task = await database.get_generation_task_payload(launched['task_id'])
    assert task['source_feed_gen_id'] == source_id
    clean = await trend_task_privacy.sanitize_task_api_payload({'task':task})
    assert SECRET not in json.dumps(clean) and FIXED not in json.dumps(clean) and VIDEO not in json.dumps(clean)
    assert await balance(actor.user_id) == 80
    again = await lifecycle.launch(actor, recipe, quote, 'repeat-once')
    assert again['task_id'] == launched['task_id'] and provider.creates == 1


@pytest.mark.asyncio
async def test_repeat_permission_change_invalidates_quote_without_debit():
    _owner, source_id = await published_source()
    actor = await user_actor(100, telegram_id=991203)
    provider = Provider()
    lifecycle = Wan3PrimeLifecycle(probe=Probe(), preset_manager=Prices(), transport=provider)
    plan = public_plan(await get_repeat_plan(actor, source_id))
    recipe = {**plan['recipe'], 'source_feed_gen_id':source_id, 'repeat_plan_hash':plan['repeat_plan_hash'],
              'repeat_replacements':{'image:0':USER_FACE}}
    quote = await lifecycle.quote(actor, recipe)
    await database.share_to_feed('wan3_author_source', _owner.user_id, references_visible=False,
                                repeat_reference_image_indices=[], repeat_reference_video_indices=[])
    with pytest.raises(Wan3PrimeValidationError):
        await lifecycle.launch(actor, recipe, quote, 'revoked-permission')
    assert provider.creates == 0 and await balance(actor.user_id) == 100
