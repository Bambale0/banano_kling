"""Typed private video-repeat consent and URL-free consumer contracts."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot import database, miniapp
from bot.handlers import miniapp_video_continuity_compat as continuity

FACE = "https://example.test/author-face.png"
FIXED = "https://example.test/fixed-cake.png"
MOTION = "https://example.test/author-motion.mp4"
STYLE = "https://example.test/fixed-style.mp4"


async def create_video():
    owner = await database.get_or_create_user(880101)
    await database.add_generation_task(
        owner.id, owner.telegram_id, "typed-private-video", "video", "seedance_2_5",
        model="seedance_2_5", prompt="Synthetic private recipe",
        request_data={"seedance25_scenario": "multimodal", "v_type": "video",
                      "reference_images": [FACE, FIXED],
                      "v_reference_videos": [MOTION, STYLE]},
    )
    await database.complete_video_task("typed-private-video", "https://example.test/result.mp4")
    return owner


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", ["feed", "profile"])
async def test_private_video_grant_has_url_free_ordered_consumer_slots(scope):
    owner = await create_video()
    card = await database.share_to_feed(
        "typed-private-video", owner.id, publication_scope=scope,
        references_visible=False, repeat_reference_image_indices=[1],
        repeat_reference_video_indices=[1],
    )
    source = await database.get_generation_task_payload(card["id"])
    grant = json.loads(source["feed_repeat_reference_selection"])
    assert grant == {"version": 1, "images": [FIXED], "videos": [STYLE]}
    get_card = database.get_feed_generation_card if scope == "feed" else database.get_profile_generation_card
    public = await get_card(card["id"])
    assert public["repeat_reference_slots"] == {
        "version": 1, "available": True,
        "images": [{"index": 0, "role": "reference", "binding": "upload"},
                   {"index": 1, "role": "reference", "binding": "fixed"}],
        "videos": [{"index": 0, "role": "reference", "binding": "upload"},
                   {"index": 1, "role": "reference", "binding": "fixed"}],
    }
    serialized = json.dumps(public)
    for secret in (FACE, FIXED, MOTION, STYLE, "Synthetic private recipe"):
        assert secret not in serialized
    own = await get_card(card["id"], viewer_user_id=owner.id)
    assert "repeat_reference_slots" not in own


@pytest.mark.parametrize("grant", [
    "{broken-json", {"version": 99, "images": [FIXED], "videos": [STYLE]},
    {"version": 1, "images": [FIXED], "videos": "bad"},
])
def test_malformed_typed_video_grant_never_falls_back_to_legacy_reuse(grant):
    source = {
        "type": "video", "model": "seedance_2_5", "status": "completed",
        "prompt": "Synthetic", "feed_repeat_reference_selection": grant,
        "feed_reference_selection": None,
        "request_data": {"seedance25_scenario": "multimodal",
                         "reference_images": [FIXED], "v_reference_videos": [STYLE]},
    }
    with pytest.raises(continuity.VideoRepeatReferenceError):
        continuity.enrich_video_repeat_body({"source_feed_gen_id": 42}, source)


@pytest.mark.asyncio
@pytest.mark.parametrize("model", ["seedance_2", "seedance_2_5"])
@pytest.mark.parametrize("change", ["grant", "withdrawal", "recipe", "availability", "provider_error", "provider_exception", "interread_withdrawal", "legacy_to_typed", "legacy_image_only_to_typed"])
async def test_video_permission_is_rechecked_immediately_before_debit(monkeypatch, caplog, model, change):
    import inspect

    from bot.handlers import seedance_25_public_release as public

    current = {
        "id": 42, "user_id": 1, "type": "video", "model": model, "status": "completed",
        "is_public_feed": True, "prompt": "Synthetic private recipe",
        "feed_repeat_reference_selection": {"version": 1, "images": [FIXED], "videos": [STYLE]},
        "request_data": {"v_type": "video", "seedance25_scenario": "multimodal",
                         "reference_images": [FACE, FIXED], "v_reference_videos": [MOTION, STYLE]},
    }
    card = {"id": 42, "gen_type": "video", "model": model, "result_url": "https://example.test/result.mp4"}
    withdraw_on_card_read = []
    if change == "interread_withdrawal":
        current["feed_repeat_reference_selection"] = {"version": 1, "images": [], "videos": []}
    elif change == "legacy_to_typed":
        current["feed_repeat_reference_selection"] = None
    elif change == "legacy_image_only_to_typed":
        current["feed_repeat_reference_selection"] = {"images": []}

    async def read_card(*_args, **_kwargs):
        snapshot = dict(card) if card else None
        if withdraw_on_card_read:
            current["is_public_feed"] = False
            current["is_profile_visible"] = False
        return snapshot

    card_lookup = AsyncMock(side_effect=read_card)
    source_lookup = AsyncMock(side_effect=lambda *_args, **_kwargs: dict(current))
    context = AsyncMock(return_value=(880102, {"user": SimpleNamespace(id=2, credits=10000)}))
    original = inspect.unwrap(miniapp.miniapp_generate_video)

    async def delegate(request):
        if model == "seedance_2_5":
            return await public._public_miniapp_generate(request, await request.json())
        return await original(request)

    missing = []

    async def revoke_before_charge(*_args):
        if change in {"grant", "legacy_to_typed", "legacy_image_only_to_typed"}:
            current["feed_repeat_reference_selection"] = {"version": 1, "images": [], "videos": []}
        elif change == "withdrawal":
            card.clear()
        elif change == "recipe":
            current["request_data"] = {**current["request_data"], "reference_images": [FACE]}
        elif change == "availability":
            missing.append(FIXED)
        elif change == "interread_withdrawal":
            withdraw_on_card_read.append(True)
        return True

    monkeypatch.setattr(miniapp, "miniapp_generate_video", delegate)
    monkeypatch.setattr(miniapp, "miniapp_feed_share", AsyncMock())
    monkeypatch.setattr(miniapp, "_video_continuity_compat_installed", False, raising=False)
    monkeypatch.setattr(miniapp, "_get_user_context", context)
    monkeypatch.setattr(miniapp, "_get_repeat_source_card", card_lookup)
    monkeypatch.setattr(miniapp, "get_generation_task_payload", source_lookup)
    monkeypatch.setattr(continuity, "get_generation_task_payload", source_lookup)
    monkeypatch.setattr(continuity, "missing_local_upload_sources", lambda values: [url for url in missing if url in values])
    monkeypatch.setattr(miniapp, "missing_local_upload_sources", lambda _values: [])
    monkeypatch.setattr(miniapp, "touch_saved_references", AsyncMock())
    monkeypatch.setattr(miniapp.config, "is_admin", lambda _telegram_id: False)
    monkeypatch.setattr(miniapp.preset_manager, "get_video_cost_with_quality", lambda *_args: 1)
    monkeypatch.setattr(public.preview_module, "_price_quote", lambda _data: 1)
    monkeypatch.setattr(public, "_validate_public_payload", AsyncMock())
    monkeypatch.setattr(miniapp, "check_can_afford", AsyncMock(side_effect=revoke_before_charge))
    debit = AsyncMock()
    monkeypatch.setattr(miniapp, "deduct_credits", debit)
    monkeypatch.setattr(miniapp, "add_credits", AsyncMock())
    private_error = FIXED + " Synthetic private recipe"
    launch = AsyncMock(return_value={"status": "failed", "error": private_error})
    if change == "provider_exception":
        launch.side_effect = RuntimeError(private_error)
    monkeypatch.setattr(miniapp, "_launch_video_generation_task", launch)
    monkeypatch.setattr(public, "_launch_provider", launch)
    continuity.install_miniapp_video_continuity_compat()

    class Request:
        def __init__(self):
            self.app = {}
            self._read_bytes = json.dumps({
                "init_data": "signed", "source_feed_gen_id": 42,
                "v_model": model, "v_type": "video", "v_duration": 5, "v_ratio": "9:16",
                "seedance25_scenario": "multimodal",
                "reference_images": (["https://example.test/viewer.png", "https://example.test/viewer-second.png"]
                                     if change == "interread_withdrawal" else [] if change.startswith("legacy_") else ["https://example.test/viewer.png"]),
                "v_reference_videos": (["https://example.test/viewer.mp4", "https://example.test/viewer-second.mp4"]
                                      if change == "interread_withdrawal" else [] if change.startswith("legacy_") else ["https://example.test/viewer.mp4"]),
            }).encode()

        async def json(self):
            return json.loads(self._read_bytes)

    response = await miniapp.miniapp_generate_video(Request())
    miniapp.check_can_afford.assert_awaited_once()
    if change.startswith("provider"):
        assert response.status in (500, 502)
        debit.assert_awaited_once()
        launch.assert_awaited_once()
    else:
        assert response.status in (400, 403, 404)
        debit.assert_not_awaited()
        launch.assert_not_awaited()
    for secret in (FACE, FIXED, MOTION, STYLE, "Synthetic private recipe"):
        assert secret not in response.text
        assert secret not in caplog.text


@pytest.fixture
def typed_video_entrypoint(monkeypatch):
    from unittest.mock import MagicMock

    from aiohttp import web

    source = {
        "id": 42, "user_id": 1, "type": "video", "status": "completed",
        "model": "seedance_2_5", "prompt": "Synthetic private recipe",
        "feed_repeat_reference_selection": {"version": 1, "images": [FIXED], "videos": [STYLE]},
        "request_data": {"seedance25_scenario": "multimodal", "v_type": "video",
                         "reference_images": [FACE, FIXED], "v_reference_videos": [MOTION, STYLE]},
    }
    delegate = AsyncMock(return_value=web.json_response({"ok": True}))
    context = AsyncMock(return_value=(880102, {"user": SimpleNamespace(id=2, credits=100)}))
    monkeypatch.setattr(miniapp, "miniapp_generate_video", delegate)
    monkeypatch.setattr(miniapp, "miniapp_feed_share", AsyncMock())
    monkeypatch.setattr(miniapp, "_video_continuity_compat_installed", False, raising=False)
    monkeypatch.setattr(miniapp, "_get_user_context", context)
    monkeypatch.setattr(miniapp, "_get_repeat_source_card", AsyncMock(return_value={
        "id": 42, "gen_type": "video", "prompt": "", "prompt_hidden": True,
        "reference_images": [], "reference_videos": [], "references_hidden": True,
    }))
    monkeypatch.setattr(continuity, "get_generation_task_payload", AsyncMock(side_effect=lambda *_args: dict(source)))
    availability = MagicMock(return_value=[])
    monkeypatch.setattr(continuity, "missing_local_upload_sources", availability)
    continuity.install_miniapp_video_continuity_compat()

    class Request:
        def __init__(self, body):
            self.app = {}
            self._read_bytes = json.dumps({"source_feed_gen_id": 42, **body}).encode()

        async def json(self):
            return json.loads(self._read_bytes)

    return SimpleNamespace(call=miniapp.miniapp_generate_video, source=source,
                           delegate=delegate, context=context, request=Request, availability=availability)


@pytest.mark.asyncio
async def test_typed_video_api_keeps_fixed_slots_server_only(typed_video_entrypoint):
    entry = typed_video_entrypoint
    own_image, own_video = "https://example.test/own.png", "https://example.test/own.mp4"
    request = entry.request({"reference_images": [own_image], "v_reference_videos": [own_video]})
    response = await entry.call(request)
    assert response.status == 200
    internal = await request.json()
    assert internal["reference_images"] == [own_image, FIXED]
    assert internal["v_reference_videos"] == [own_video, STYLE]
    assert internal["_private_repeat_reference_images"] == [FIXED]
    assert internal["_private_repeat_reference_videos"] == [STYLE]
    assert FIXED not in response.text and STYLE not in response.text
    assert "Synthetic private recipe" not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [
    {}, {"reference_images": []}, {"reference_images": [FACE]},
    {"reference_images": ["https://example.test/one.png", "https://example.test/two.png"]},
    {"v_model": "grok_imagine_v15", "reference_images": ["https://example.test/one.png"]},
    {"seedance25_scenario": "text", "reference_images": ["https://example.test/one.png"]},
    {"_repeat_is_owner": True, "_private_repeat_reference_images": [FACE],
     "repeat_reference_slots": {"version": 1, "available": True, "images": [], "videos": []}},
])
async def test_client_metadata_cannot_authorize_or_shift_typed_slots(typed_video_entrypoint, body):
    entry = typed_video_entrypoint
    request = entry.request({"v_reference_videos": ["https://example.test/own.mp4"], **body})
    response = await entry.call(request)
    assert response.status == 400
    entry.delegate.assert_not_awaited()
    assert FIXED not in response.text and FACE not in response.text


@pytest.mark.asyncio
async def test_typed_all_fixed_recipe_needs_no_extra_upload(typed_video_entrypoint):
    entry = typed_video_entrypoint
    entry.source["feed_repeat_reference_selection"] = {"version": 1, "images": [FACE, FIXED], "videos": [MOTION, STYLE]}
    request = entry.request({})
    assert (await entry.call(request)).status == 200
    assert (await request.json())["reference_images"] == [FACE, FIXED]


@pytest.mark.asyncio
async def test_ordinary_owner_keeps_editable_repeat_after_revoking_foreign_grant(typed_video_entrypoint):
    entry = typed_video_entrypoint
    entry.context.return_value = (880101, {"user": SimpleNamespace(id=1, credits=100)})
    entry.source["feed_repeat_reference_selection"] = {"version": 1, "images": [], "videos": []}
    own_image, own_video = "https://example.test/new-own.png", "https://example.test/new-own.mp4"
    request = entry.request({"reference_images": [own_image], "v_reference_videos": [own_video]})
    assert (await entry.call(request)).status == 200
    assert (await request.json())["reference_images"] == [own_image]
    assert (await request.json())["v_reference_videos"] == [own_video]


@pytest.mark.asyncio
async def test_typed_first_last_uses_upload_slots_not_raw_source_aliases(typed_video_entrypoint):
    entry = typed_video_entrypoint
    entry.source["request_data"] = {
        "seedance25_scenario": "first_last", "v_type": "imgtxt",
        "first_frame_url": FACE, "v_image_url": FACE, "last_frame_url": FIXED,
    }
    entry.source["feed_repeat_reference_selection"] = {"version": 1, "images": [FIXED], "videos": []}
    request = entry.request({"v_type": "imgtxt", "reference_images": ["https://example.test/own.png"]})
    assert (await entry.call(request)).status == 200
    internal = await request.json()
    assert internal["seedance25_first_frame_url"] == "https://example.test/own.png"
    assert internal["seedance25_last_frame_url"] == FIXED
    assert internal["reference_images"] == []
    assert entry.availability.call_args.args[0] == ["https://example.test/own.png", FIXED]


@pytest.mark.asyncio
async def test_image_only_multimodal_preserves_provider_scenario_from_generic_card(typed_video_entrypoint):
    entry = typed_video_entrypoint
    entry.source["request_data"]["v_reference_videos"] = []
    entry.source["feed_repeat_reference_selection"]["videos"] = []
    request = entry.request({"v_type": "imgtxt", "reference_images": ["https://example.test/own.png"]})
    assert (await entry.call(request)).status == 200
    internal = await request.json()
    assert internal["seedance25_scenario"] == "multimodal"
    assert internal["reference_images"] == ["https://example.test/own.png", FIXED]


@pytest.mark.asyncio
async def test_legacy_single_photo_i2v_snapshot_can_receive_a_typed_grant(monkeypatch):
    owner = await database.get_or_create_user(880111)
    await database.add_generation_task(
        owner.id, owner.telegram_id, "legacy-photo-video", "video", "seedance_2_5",
        prompt="Synthetic", request_data={"v_model": "seedance_2_5", "v_type": "imgtxt", "reference_images": [FIXED]},
    )
    await database.complete_video_task("legacy-photo-video", "https://example.test/result.mp4")
    card = await database.share_to_feed("legacy-photo-video", owner.id, repeat_reference_image_indices=[0], repeat_reference_video_indices=[])
    public = await database.get_feed_generation_card(card["id"])
    assert public["repeat_reference_slots"]["images"] == [{"index": 0, "role": "first_frame", "binding": "fixed"}]


@pytest.mark.asyncio
async def test_withdrawal_then_legacy_republish_cannot_restore_revoked_video_grant():
    from bot.handlers import publication_scope_compat as publication
    owner = await create_video()
    card = await database.share_to_feed("typed-private-video", owner.id,
        repeat_reference_image_indices=[1], repeat_reference_video_indices=[1])
    assert await publication.remove_publication(card["id"], owner.id)
    await database.share_to_feed("typed-private-video", owner.id)
    current = await database.get_generation_task_payload(card["id"])
    assert json.loads(current["feed_repeat_reference_selection"]) == {"version": 1, "images": [], "videos": []}


@pytest.mark.asyncio
async def test_legacy_video_publication_without_new_consent_remains_legacy():
    owner = await create_video()
    card = await database.share_to_feed("typed-private-video", owner.id)
    source = await database.get_generation_task_payload(card["id"])
    assert json.loads(source["feed_repeat_reference_selection"]) == {"images": []}
    assert "repeat_reference_slots" not in (await database.get_feed_generation_card(card["id"]))


@pytest.mark.asyncio
async def test_video_permission_save_rejects_missing_selected_asset_without_mutation(monkeypatch):
    owner = await create_video()
    old = database._is_feed_result_url_available
    monkeypatch.setattr(database, "_is_feed_result_url_available",
                        lambda row, url: False if url == FIXED else old(row, url))
    with pytest.raises(ValueError, match="недоступны"):
        await database.share_to_feed("typed-private-video", owner.id,
            repeat_reference_image_indices=[1], repeat_reference_video_indices=[])
    source = await database.get_generation_task_payload("typed-private-video")
    assert not source["is_public_feed"]
    assert source["feed_repeat_reference_selection"] is None


@pytest.mark.asyncio
async def test_audio_bearing_video_rejects_private_image_video_grant_but_legacy_publish_remains():
    owner = await database.get_or_create_user(880121)
    await database.add_generation_task(
        owner.id, owner.telegram_id, "audio-video", "video", "seedance_2_5", model="seedance_2_5",
        request_data={"seedance25_scenario": "multimodal", "reference_images": [FIXED],
                      "reference_audios": ["https://example.test/private-audio.mp3"]},
    )
    await database.complete_video_task("audio-video", "https://example.test/result.mp4")
    with pytest.raises(ValueError, match="аудио"):
        await database.share_to_feed("audio-video", owner.id, repeat_reference_image_indices=[0], repeat_reference_video_indices=[])
    card = await database.share_to_feed("audio-video", owner.id)
    assert card is not None
    assert "repeat_reference_slots" not in (await database.get_feed_generation_card(card["id"]))


@pytest.mark.asyncio
@pytest.mark.parametrize("request_data,kind,expected", [
    ({"v_image_url": FACE}, "images", "imgtxt"),
    ({"v_reference_videos": [MOTION]}, "videos", "video"),
    ({"generation_type": "imgtxt", "v_image_url": FACE}, "images", "imgtxt"),
])
async def test_typed_legacy_generic_card_scenario_matches_its_repeat_request(request_data, kind, expected):
    owner = await database.get_or_create_user(880131)
    await database.add_generation_task(owner.id, owner.telegram_id, "legacy-mode", "video", "seedance_2",
        model="seedance_2", prompt="Synthetic", request_data=request_data)
    await database.complete_video_task("legacy-mode", "https://example.test/result.mp4")
    card = await database.share_to_feed("legacy-mode", owner.id,
        repeat_reference_image_indices=[0] if kind == "images" else [],
        repeat_reference_video_indices=[0] if kind == "videos" else [])
    public = await database.get_feed_generation_card(card["id"])
    assert public["scenario"] == expected
    source = await database.get_generation_task_payload(card["id"])
    restored = continuity.enrich_video_repeat_body(
        {"source_feed_gen_id": card["id"], "v_type": public["scenario"],
         "reference_images": [], "v_reference_videos": []}, source)
    assert restored["v_type"] == expected
    assert restored["v_image_url"] == FACE if kind == "images" else restored["v_reference_videos"] == [MOTION]


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,field,suffix", [
    ("images", "reference_images", "png"), ("videos", "v_reference_videos", "mp4"),
])
async def test_typed_fixed_provider_list_rejects_collapsing_local_aliases(
    typed_video_entrypoint, kind, field, suffix,
):
    from bot.services.seedance_25_service import Seedance25Service

    entry = typed_video_entrypoint
    first = f"/uploads/synthetic-alias.{suffix}"
    second = f"https://media.chillcreative.ru/uploads/synthetic-alias.{suffix}"
    assert len(Seedance25Service._clean_urls([first, second])) == 1
    entry.source["request_data"] = {"seedance25_scenario": "multimodal", field: [first, second]}
    entry.source["feed_repeat_reference_selection"] = {"version": 1, "images": [], "videos": [], kind: [first, second]}
    response = await entry.call(entry.request({}))
    assert response.status == 400
    entry.delegate.assert_not_awaited()


@pytest.mark.asyncio
async def test_typed_first_and_last_can_intentionally_use_same_file_identity(typed_video_entrypoint):
    entry = typed_video_entrypoint
    first = "/uploads/synthetic-same-frame.png"
    last = "https://media.chillcreative.ru/uploads/synthetic-same-frame.png"
    entry.source["request_data"] = {"seedance25_scenario": "first_last", "first_frame_url": first, "last_frame_url": last}
    entry.source["feed_repeat_reference_selection"] = {"version": 1, "images": [first, last], "videos": []}
    request = entry.request({})
    response = await entry.call(request)
    assert response.status == 200
    assert (await request.json())["seedance25_first_frame_url"] == first
    assert (await request.json())["seedance25_last_frame_url"] == last
