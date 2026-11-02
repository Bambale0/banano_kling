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



@pytest.mark.asyncio
@pytest.mark.parametrize("action,parent_id", [
    ("trend", None),
    ("repeat", 153),
    ("remix", 153),
])
async def test_any_published_wan_video_repeats_its_own_recipe(monkeypatch, action, parent_id):
    # Publishing the generated result grants replay of this specific result,
    # including the creator's edits. Never swap it for a different ancestor.
    from types import SimpleNamespace

    from bot.services import wan3_prime_trends

    source = {
        "id": 315600, "user_id": 70, "telegram_id": 89170,
        "type": "video", "status": "completed", "model": "wan_3",
        "is_public_feed": True, "is_profile_visible": True,
        "action_type": action, "source_feed_gen_id": parent_id,
        "request_data": {
            "trend_id": 2048, "scenario": "reference",
            "prompt": "CHILD_PRIVATE_PROMPT",
            "reference_image_urls": ["https://child.test/one.png"],
            "reference_video_urls": ["https://child.test/original.mp4"],
            "reference_audio_urls": [], "reference_file_urls": [], "reference_link_urls": [],
            "resolution": "480P", "aspect_ratio": "9:16", "duration": 11,
            "audio": False, "nsfw_checker": False, "seed": 73,
        },
    }
    async def source_card(source_id, *, viewer_user_id, include_unavailable=False):
        assert (source_id, viewer_user_id) == (315600, 992)
        return {"id": source_id, "gen_type": "video"}
    async def source_task(_):
        return dict(source)
    async def forbidden_ancestor(*_args):
        raise AssertionError("The published child is the source; do not use an ancestor's recipe")
    monkeypatch.setattr(database, "get_profile_generation_card", source_card)
    monkeypatch.setattr(database, "get_generation_task_payload", source_task)
    monkeypatch.setattr(wan3_prime_trends, "get_trend_plan", forbidden_ancestor)

    plan = await get_repeat_plan(SimpleNamespace(user_id=992), 315600)
    public = public_plan(plan)
    assert plan["source_id"] == 315600
    assert public["source_feed_gen_id"] == 315600
    assert "trend_id" not in public
    assert plan["recipe"]["duration"] == 11 and plan["recipe"]["seed"] == 73
    assert plan["recipe"]["prompt"] == "CHILD_PRIVATE_PROMPT"
    assert len(public["slots"]) == 2
    assert all(item["binding"] == "upload" for item in public["slots"])
    assert "CHILD_PRIVATE_PROMPT" not in json.dumps(public)
    assert "child.test" not in json.dumps(public)


@pytest.mark.asyncio
async def test_published_child_permission_independent_of_ancestor(monkeypatch):
    # If the child's own publication is available, repeat it. If it was
    # withdrawn, reject regardless of the original template's status.
    from types import SimpleNamespace

    from bot.services import wan3_prime_trends

    source = {
        "id": 810, "user_id": 70, "telegram_id": 89170, "type": "video",
        "status": "completed", "model": "wan_3", "action_type": "trend",
        "source_feed_gen_id": None, "is_public_feed": True, "is_profile_visible": True,
        "request_data": {
            "trend_id": 2048, "scenario": "text", "prompt": "CHILD_AUTHOR_EDIT",
            "reference_image_urls": [], "reference_video_urls": [],
            "reference_audio_urls": [], "reference_file_urls": [], "reference_link_urls": [],
            "resolution": "720P", "aspect_ratio": "9:16", "duration": 5,
            "audio": True, "nsfw_checker": True,
        },
    }
    async def source_card(*_args, **_kwargs):
        return {"id": 810} if source["is_public_feed"] else None
    async def source_task(*_args):
        return dict(source)
    async def revoked_parent(*_args):
        raise Wan3PrimeValidationError("Original template withdrawn", status=404)
    monkeypatch.setattr(database, "get_profile_generation_card", source_card)
    monkeypatch.setattr(database, "get_generation_task_payload", source_task)
    monkeypatch.setattr(wan3_prime_trends, "get_trend_plan", revoked_parent)
    assert (await get_repeat_plan(SimpleNamespace(user_id=992), 810))["source_id"] == 810
    source["is_public_feed"] = False
    source["is_profile_visible"] = False
    with pytest.raises(Wan3PrimeValidationError) as err:
        await get_repeat_plan(SimpleNamespace(user_id=992), 810)
    assert err.value.status == 404


@pytest.mark.asyncio
async def test_unpublished_child_even_with_visible_card_never_grants_repeat(monkeypatch):
    from types import SimpleNamespace

    async def source_card(*_args, **_kwargs): return {"id": 810}
    async def source_task(*_args):
        return {
            "id": 810, "user_id": 70, "type": "video", "status": "completed",
            "is_public_feed": False, "is_profile_visible": False,
            "model": "wan_3", "action_type": "trend", "source_feed_gen_id": None,
            "request_data": {"scenario": "text", "prompt": "hidden"},
        }
    monkeypatch.setattr(database, "get_profile_generation_card", source_card)
    monkeypatch.setattr(database, "get_generation_task_payload", source_task)
    with pytest.raises(Wan3PrimeValidationError) as err:
        await get_repeat_plan(SimpleNamespace(user_id=992), 810)
    assert err.value.status == 404


@pytest.mark.asyncio
async def test_curated_wan_repeat_needs_only_one_personal_photo_and_preserves_video(monkeypatch):
    from types import SimpleNamespace

    from bot import repeat_personalization as rp
    from bot.services import wan3_prime_repeat as repeat

    image_urls = [f"https://owner.test/source-{index}.jpg" for index in range(4)]
    source = {
        "id": 501, "user_id": 70, "telegram_id": 990077,
        "model": "wan_3", "type": "video", "status": "completed",
        "is_public_feed": True, "is_profile_visible": True,
        "prompt": "Keep @Image1 as the visitor identity, preserve the cinematic motion.",
        "feed_repeat_reference_selection": {"version": 1, "images": [], "videos": [VIDEO]},
        "request_data": {
            "scenario": "reference", "prompt": "Keep @Image1 as the visitor identity, preserve the cinematic motion.",
            "reference_image_urls": image_urls, "reference_video_urls": [VIDEO],
            "reference_audio_urls": [], "reference_file_urls": [], "reference_link_urls": [],
            "resolution": "720P", "aspect_ratio": "9:16", "duration": 5,
            "audio": False, "nsfw_checker": False,
        },
    }
    fields = rp.normalize_repeat_fields([{
        "key": key, "label": label, "image_choices": [{
            "id": key, "label": label,
            "image_url": "https://neuromixbot.com/uploads/repeat-choices/" + marker * 32 + ".jpg",
        }],
    } for key, label, marker in [
        ("car", "Машина", "a"), ("outfit", "Одежда", "b"), ("cake", "Торт", "c"),
    ]], prompt=source["prompt"])
    plan = repeat.build_repeat_plan(source)
    plan["personalization_fields"] = fields
    plan["slots"] = rp.assign_catalog_image_slots(plan["slots"], fields)
    async def fake_repeat_plan(_actor, _source_id):
        return plan
    monkeypatch.setattr(repeat, "get_repeat_plan", fake_repeat_plan)
    public = repeat.public_plan(plan)
    assert [slot["binding"] for slot in public["slots"] if slot["kind"] == "image"] == [
        "upload", "choice", "choice", "choice",
    ]
    assert "private.test" not in json.dumps(public) and "owner.test" not in json.dumps(public)
    actor = SimpleNamespace(user_id=701, telegram_id=991202)
    recipe = {
        **public["recipe"], "source_feed_gen_id": 501,
        "repeat_plan_hash": public["repeat_plan_hash"], "repeat_replacements": {"image:0": USER_FACE},
        "repeat_user_values": {"car": "car", "outfit": "outfit", "cake": "cake"},
    }
    compiled, _probe, _context, _public = await repeat.compile_repeat(actor, recipe, Probe())
    assert compiled["reference_image_urls"] == [
        USER_FACE, *[field["image_choices"][0]["image_url"] for field in fields],
    ]
    assert compiled["reference_video_urls"] == [VIDEO]
    assert "@Image1" in compiled["prompt"]
    assert "«Машина»: используйте @Image2" in compiled["prompt"]
    assert "«Одежда»: используйте @Image3" in compiled["prompt"]
    assert "«Торт»: используйте @Image4" in compiled["prompt"]
    assert not any(img in json.dumps(compiled) for img in image_urls)

    recipe["repeat_replacements"] = {}
    with pytest.raises(Wan3PrimeValidationError, match="Загрузите"):
        await repeat.compile_repeat(actor, recipe, Probe())
