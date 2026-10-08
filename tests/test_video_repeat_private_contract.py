"""Typed private video-repeat consent and URL-free consumer contracts."""
import inspect
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot import database, miniapp, trend_task_privacy
from bot.handlers import miniapp_video_continuity_compat as continuity
from bot.video_repeat_reference_contract import video_repeat_descriptors

FACE = "https://example.test/author-face.png"
FIXED = "https://example.test/fixed-cake.png"
MOTION = "https://example.test/author-motion.mp4"
STYLE = "https://example.test/fixed-style.mp4"


@pytest.fixture(autouse=True)
def isolated_financial_unit_receipt(monkeypatch):
    # Financial unit matrices use synthetic users and providers. Actual durable
    # rows and cross-device behavior are exercised in test_video_repeat_receipts.
    monkeypatch.setattr(continuity, "reserve_video_repeat_launch", AsyncMock(return_value=(None, None)))


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
    assert public["repeat_reference_slots"]["pricing_quality"] == "720p"
    assert public["repeat_reference_slots"]["duration_costs"]
    assert {key: value for key, value in public["repeat_reference_slots"].items()
            if key not in {"pricing_quality", "duration_costs"}} == {
        "version": 1, "available": True, "cost_multiplier": 2,
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
@pytest.mark.parametrize("change", ["grant", "withdrawal", "recipe", "availability", "provider_error", "provider_exception", "interread_withdrawal", "legacy_to_typed", "legacy_image_only_to_typed", "quality"])
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
        elif change == "quality":
            current["request_data"]["seedance25_resolution"] = "480p"
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


REAL_GENERIC = inspect.unwrap(miniapp.miniapp_generate_video)
REAL_VIDEO_LAUNCH = inspect.unwrap(miniapp._launch_video_generation_task)


@pytest.mark.asyncio
@pytest.mark.parametrize("case", [
    "provider_exception", "failed_result", "post_accept_bookkeeping", "done_accept_bookkeeping",
    "accepted_then_persistence", "predebit_error", "admin_error",
    "refund_uncertain", "debit_rejected",
])
async def test_typed_generic_failure_has_single_correct_financial_outcome(monkeypatch, typed_video_entrypoint, case):
    entry = typed_video_entrypoint
    entry.source.update(model="seedance_2", is_public_feed=True)
    entry.delegate.side_effect = REAL_GENERIC
    monkeypatch.setattr(miniapp, "get_generation_task_payload", AsyncMock(side_effect=lambda *_: dict(entry.source)))
    monkeypatch.setattr(miniapp.config, "is_admin", lambda _: case == "admin_error")
    monkeypatch.setattr(miniapp, "missing_local_upload_sources", lambda _: [])
    monkeypatch.setattr(miniapp, "touch_saved_references", AsyncMock())
    monkeypatch.setattr(miniapp.preset_manager, "get_video_cost_with_quality", lambda *_: 1)
    afford = AsyncMock(return_value=True)
    if case == "predebit_error":
        afford.side_effect = RuntimeError("synthetic balance-read failure")
    monkeypatch.setattr(miniapp, "check_can_afford", afford)
    balance = {"value": 100}

    async def debit_balance(_user, amount):
        if case == "debit_rejected":
            return False
        balance["value"] -= amount
        return True

    async def refund_balance(_user, amount):
        balance["value"] += amount
        if case == "refund_uncertain":
            raise RuntimeError("synthetic refund acknowledgement lost")
        return True

    debit = AsyncMock(side_effect=debit_balance)
    refund = AsyncMock(side_effect=refund_balance)
    monkeypatch.setattr(miniapp, "deduct_credits", debit)
    monkeypatch.setattr(miniapp, "add_credits", refund)
    launch = AsyncMock(return_value={"status": "failed", "error": "synthetic rejected"})
    if case in {"provider_exception", "admin_error"}:
        launch.side_effect = RuntimeError("synthetic launch failure")
    elif case == "accepted_then_persistence":
        async def accepted_then_raise(**kwargs):
            observer = kwargs.get("_launch_observation")
            if observer is not None:
                observer.update(accepted=True, provider_task_id="synthetic-accepted")
            raise RuntimeError("synthetic task persistence failure")
        launch.side_effect = accepted_then_raise
    elif case == "post_accept_bookkeeping":
        launch.return_value = {"status": "queued", "task_id": "synthetic-accepted"}
    elif case == "done_accept_bookkeeping":
        async def completed_result(**kwargs):
            kwargs["_launch_observation"].update(accepted=True, provider_task_id="")
            return {"status": "done", "task_id": "synthetic-accepted"}
        launch.side_effect = completed_result
    monkeypatch.setattr(miniapp, "_launch_video_generation_task", launch)
    monkeypatch.setattr(miniapp, "credit_feed_prompt_repeat", AsyncMock(side_effect=RuntimeError("synthetic bookkeeping failure")))
    request = entry.request({
        "v_model": "seedance_2", "v_type": "video", "v_duration": 5, "v_ratio": "9:16",
        "reference_images": ["https://example.test/own.png"],
        "v_reference_videos": ["https://example.test/own.mp4"],
    })
    response = await entry.call(request)
    assert response.status >= 400
    if case in {"provider_exception", "failed_result", "refund_uncertain"}:
        refund.assert_awaited_once_with(880102, 2)
        assert balance["value"] == 100
    elif case in {"post_accept_bookkeeping", "done_accept_bookkeeping", "accepted_then_persistence"}:
        refund.assert_not_awaited()
        assert balance["value"] == 98
        assert json.loads(response.text)["code"] == "video_status_pending"
        assert json.loads(response.text)["task_id"] == "synthetic-accepted"
    else:
        refund.assert_not_awaited()
        assert balance["value"] == 100
    if case in {"predebit_error", "debit_rejected"}:
        launch.assert_not_awaited()
    if case == "refund_uncertain":
        assert json.loads(response.text)["code"] == "video_refund_pending"


@pytest.mark.asyncio
@pytest.mark.parametrize("flag", ["seedance25_identity_transfer", "seedance25_video_editing"])
async def test_specialized_seedance_source_is_not_advertised_as_generic_typed_repeat(typed_video_entrypoint, flag):
    entry = typed_video_entrypoint
    entry.source["request_data"][flag] = True
    assert video_repeat_descriptors(entry.source)["available"] is False
    response = await entry.call(entry.request({
        "reference_images": ["https://example.test/own.png"], "v_reference_videos": ["https://example.test/own.mp4"],
    }))
    assert response.status == 400
    entry.delegate.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("asset_key", ["omni_audio_ids", "omni_character_ids", "omni_character_audio_ids"])
@pytest.mark.parametrize("origin", ["source", "client"])
async def test_typed_video_contract_cannot_reuse_ungranted_provider_assets(typed_video_entrypoint, asset_key, origin):
    entry = typed_video_entrypoint
    entry.source["model"] = "gemini_omni_video"
    body = {"reference_images": ["https://example.test/own.png"], "v_reference_videos": ["https://example.test/own.mp4"]}
    if origin == "source":
        entry.source["request_data"][asset_key] = ["synthetic-private-provider-asset"]
    else:
        body[asset_key] = ["synthetic-private-provider-asset"]
    response = await entry.call(entry.request(body))
    assert response.status == 400
    assert "synthetic-private-provider-asset" not in response.text
    entry.delegate.assert_not_awaited()


@pytest.mark.asyncio
async def test_protected_child_detail_never_returns_private_provider_asset_ids(monkeypatch):
    viewer = await database.get_or_create_user(881001)
    secret = "synthetic-private-provider-asset"
    await database.add_generation_task(
        viewer.id, viewer.telegram_id, "omni-private-child", "video", "gemini_omni_video",
        model="gemini_omni_video", source_feed_gen_id=42, action_type="repeat",
        request_data={key: [secret] for key in ("omni_audio_ids", "omni_character_ids", "omni_character_audio_ids")},
    )
    monkeypatch.setattr(miniapp, "DATABASE_PATH", database.DATABASE_PATH)
    monkeypatch.setattr(trend_task_privacy, "DATABASE_PATH", database.DATABASE_PATH)
    monkeypatch.setattr(miniapp, "_get_user_context", AsyncMock(return_value=(viewer.telegram_id, {"user": viewer})))
    request = SimpleNamespace(app={}, json=AsyncMock(return_value={"init_data": "signed", "task_id": "omni-private-child"}))
    response = await miniapp.miniapp_task_detail(request)
    assert response.status == 200
    assert secret not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_result", [{"task_id": "synthetic-provider-accepted"}, b"synthetic-completed-result"])
async def test_actual_video_launch_records_acceptance_before_task_persistence(monkeypatch, provider_result):
    from bot.services.seedance_service import seedance_service

    provider = AsyncMock(return_value=provider_result)
    monkeypatch.setattr(seedance_service, "generate_video", provider)
    monkeypatch.setattr(miniapp.preset_manager, "get_video_cost_with_quality", lambda *_: 1)
    persistence = AsyncMock(side_effect=RuntimeError("synthetic persistence failure"))
    monkeypatch.setattr(miniapp, "add_generation_task", persistence)
    observer = {}
    with pytest.raises(RuntimeError, match="persistence"):
        await inspect.unwrap(miniapp._launch_video_generation_task)(
            telegram_id=881002, user=SimpleNamespace(id=12), model="seedance_2",
            prompt="Synthetic recipe", duration=5, aspect_ratio="9:16",
            generation_type="video", image_url=None, image_references=[], video_references=[],
            _launch_observation=observer,
        )
    assert observer["accepted"] is True
    persistence.assert_awaited_once()
    assert "_launch_observation" not in provider.await_args.kwargs


@pytest.mark.parametrize("count,fixed", [(0, False), (1, False), (2, False), (1, True), (2, True)])
def test_typed_price_factor_uses_active_video_presence_once(typed_video_entrypoint, count, fixed):
    from bot import video_reference_policy

    source = typed_video_entrypoint.source
    urls = [f"https://example.test/video-{index}.mp4" for index in range(count)]
    source["request_data"]["v_reference_videos"] = urls
    source["feed_repeat_reference_selection"]["videos"] = urls if fixed else []
    descriptor = video_repeat_descriptors(source)
    assert descriptor["available"] is True
    assert descriptor["cost_multiplier"] == (video_reference_policy.SEEDANCE_VIDEO_REFERENCE_PRICE_MULTIPLIER if count else 1)


def test_typed_price_factor_reads_authoritative_policy(monkeypatch, typed_video_entrypoint):
    from bot import video_reference_policy

    monkeypatch.setattr(video_reference_policy, "SEEDANCE_VIDEO_REFERENCE_PRICE_MULTIPLIER", 3.5)
    assert video_repeat_descriptors(typed_video_entrypoint.source)["cost_multiplier"] == 3.5


@pytest.mark.asyncio
@pytest.mark.parametrize("flag", ["seedance25_identity_transfer", "seedance25_video_editing"])
async def test_author_cannot_save_generic_private_grant_for_specialized_seedance_mode(flag):
    owner = await database.get_or_create_user(881003)
    await database.add_generation_task(
        owner.id, owner.telegram_id, "specialized-private-source", "video", "seedance_2_5",
        model="seedance_2_5", request_data={"seedance25_scenario": "multimodal", flag: True,
                                         "reference_images": [FIXED], "v_reference_videos": [STYLE]},
    )
    await database.complete_video_task("specialized-private-source", "https://example.test/result.mp4")
    with pytest.raises(ValueError, match="специальный"):
        await database.share_to_feed("specialized-private-source", owner.id,
                                    repeat_reference_image_indices=[0], repeat_reference_video_indices=[0])
    source = await database.get_generation_task_payload("specialized-private-source")
    assert not source["is_public_feed"]
    assert source["feed_repeat_reference_selection"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["owner", "legacy"])
async def test_ordinary_owner_and_legacy_omni_keep_existing_provider_assets(typed_video_entrypoint, mode):
    entry = typed_video_entrypoint
    entry.source["model"] = "gemini_omni_video"
    entry.source["request_data"]["omni_audio_ids"] = ["synthetic-owner-audio"]
    if mode == "owner":
        entry.context.return_value = (880101, {"user": SimpleNamespace(id=1)})
    else:
        entry.source["feed_repeat_reference_selection"] = {"images": []}
    request = entry.request({
        "reference_images": ["https://example.test/own.png"],
        "v_reference_videos": ["https://example.test/own.mp4"],
    })
    assert (await entry.call(request)).status == 200
    assert (await request.json())["omni_audio_ids"] == ["synthetic-owner-audio"]


@pytest.mark.asyncio
@pytest.mark.parametrize("model,extra", [
    ("seedance_2_5", {"seedance25_identity_transfer": True}),
    ("gemini_omni_video", {"omni_audio_ids": ["synthetic-owner-provider-audio"]}),
    ("motion_control_v26", {"v_type": "motion_control", "motion_image_url": FACE, "motion_video_url": MOTION}),
])
async def test_unsupported_private_recipe_can_publish_result_with_empty_consent(model, extra):
    owner = await database.get_or_create_user(881004)
    await database.add_generation_task(
        owner.id, owner.telegram_id, "unsupported-empty-consent", "video", model, model=model,
        request_data={"v_type": "video", "seedance25_scenario": "multimodal",
                      "reference_images": [FIXED], "v_reference_videos": [STYLE], **extra},
    )
    await database.complete_video_task("unsupported-empty-consent", "https://example.test/result.mp4")
    card = await database.share_to_feed("unsupported-empty-consent", owner.id,
                                     repeat_reference_image_indices=[], repeat_reference_video_indices=[])
    assert card is not None
    public = await database.get_feed_generation_card(card["id"])
    assert public["repeat_reference_slots"]["available"] is False
    own = await database.get_feed_generation_card(card["id"], viewer_user_id=owner.id)
    assert "repeat_reference_slots" not in own


@pytest.mark.asyncio
@pytest.mark.parametrize('case', ['persistence', 'refresh', 'reward', 'rejected', 'exception', 'refund_uncertain', 'debit_rejected', 'admin_accepted'])
async def test_typed_seedance_actual_provider_acceptance_financial_boundary(monkeypatch, typed_video_entrypoint, case):
    from bot.handlers import seedance_25_public_release as public
    entry = typed_video_entrypoint
    entry.source['is_public_feed'] = True
    miniapp._get_repeat_source_card.return_value.update(model='seedance_2_5')

    async def delegate(request):
        return await public._public_miniapp_generate(request, await request.json())

    entry.delegate.side_effect = delegate
    monkeypatch.setattr(miniapp.config, 'is_admin', lambda _: case == 'admin_accepted')
    monkeypatch.setattr(public, '_validate_public_payload', AsyncMock())
    monkeypatch.setattr(public.preview_module, '_price_quote', lambda _: 2)
    monkeypatch.setattr(miniapp, 'check_can_afford', AsyncMock(return_value=True))
    balance = {'value': 100}

    async def debit(_user, amount):
        if case == 'debit_rejected':
            return False
        balance['value'] -= amount
        return True

    async def refund(_user, amount):
        balance['value'] += amount
        if case == 'refund_uncertain':
            raise RuntimeError('synthetic uncertain refund')
        return True

    monkeypatch.setattr(miniapp, 'deduct_credits', AsyncMock(side_effect=debit))
    monkeypatch.setattr(miniapp, 'add_credits', AsyncMock(side_effect=refund))
    provider = AsyncMock(return_value={'task_id': 'synthetic-seedance-accepted'})
    if case in {'rejected', 'refund_uncertain'}:
        provider.return_value = {'error': 'synthetic rejected'}
    elif case == 'exception':
        provider.side_effect = RuntimeError('synthetic transport failure')
    monkeypatch.setattr(public.seedance_25_service, 'generate_video', provider)
    persist = AsyncMock()
    if case in {'persistence', 'admin_accepted'}:
        persist.side_effect = RuntimeError('synthetic persistence failure')
    monkeypatch.setattr(public.generation_module, 'add_generation_task', persist)
    reward = AsyncMock()
    if case == 'reward':
        reward.side_effect = RuntimeError('synthetic reward failure')
    monkeypatch.setattr(miniapp, 'credit_feed_prompt_repeat', reward)
    refresh = AsyncMock(return_value=SimpleNamespace(credits=98))
    if case == 'refresh':
        refresh.side_effect = RuntimeError('synthetic refresh failure')
    monkeypatch.setattr(miniapp, 'get_or_create_user', refresh)
    response = await entry.call(entry.request({
        'v_model': 'seedance_2_5', 'v_type': 'video', 'v_duration': 5, 'v_ratio': '9:16',
        'reference_images': ['https://example.test/own.png'],
        'v_reference_videos': ['https://example.test/own.mp4'],
    }))
    data = json.loads(response.text)
    if case in {'persistence', 'refresh', 'admin_accepted'}:
        assert data['code'] == 'video_status_pending'
        assert data['task_id'] == 'synthetic-seedance-accepted'
        miniapp.add_credits.assert_not_awaited()
        assert balance['value'] == (100 if case == 'admin_accepted' else 98)
    elif case == 'reward':
        assert response.status == 200
        miniapp.add_credits.assert_not_awaited()
        assert balance['value'] == 98
    elif case == 'debit_rejected':
        assert response.status == 400
        provider.assert_not_awaited()
        miniapp.add_credits.assert_not_awaited()
    else:
        miniapp.add_credits.assert_awaited_once_with(880102, 2)
        assert balance['value'] == 100
        if case == 'refund_uncertain':
            assert data['code'] == 'video_refund_pending'


@pytest.mark.asyncio
@pytest.mark.parametrize('model,mode', [
    ('veo3_fast', 'FIRST_AND_LAST_FRAMES_2_VIDEO'),
    ('veo3_fast', 'REFERENCE_2_VIDEO'),
    ('veo3_fast', None),
    ('gemini_omni_video', None),
])
async def test_typed_provider_mode_survives_public_form_defaults_before_debit(monkeypatch, typed_video_entrypoint, model, mode):
    entry = typed_video_entrypoint
    entry.source.update(model=model, is_public_feed=True,
                        feed_repeat_reference_selection={'version': 1, 'images': [FACE, FIXED], 'videos': []},
                        request_data={'v_type': 'imgtxt', 'reference_images': [FACE, FIXED],
                                      **({'veo_generation_type': mode} if mode else {})})
    entry.delegate.side_effect = REAL_GENERIC
    monkeypatch.setattr(miniapp, 'get_generation_task_payload', AsyncMock(side_effect=lambda *_: dict(entry.source)))
    monkeypatch.setattr(miniapp.config, 'is_admin', lambda _: False)
    monkeypatch.setattr(miniapp, 'missing_local_upload_sources', lambda _: [])
    monkeypatch.setattr(miniapp, 'touch_saved_references', AsyncMock())
    monkeypatch.setattr(miniapp.preset_manager, 'get_video_cost_with_quality', lambda *_: 1)
    monkeypatch.setattr(miniapp, 'check_can_afford', AsyncMock(return_value=True))
    monkeypatch.setattr(miniapp, 'deduct_credits', AsyncMock(return_value=True))
    monkeypatch.setattr(miniapp, 'credit_feed_prompt_repeat', AsyncMock())
    monkeypatch.setattr(miniapp, 'get_or_create_user', AsyncMock(return_value=SimpleNamespace(credits=99)))
    launch = AsyncMock(return_value={'status': 'queued', 'task_id': 'synthetic-mode'})
    monkeypatch.setattr(miniapp, '_launch_video_generation_task', launch)
    response = await entry.call(entry.request({
        'v_model': 'gemini_omni' if model == 'gemini_omni_video' else model, 'v_type': 'imgtxt',
        'v_duration': 6, 'v_ratio': '9:16', 'veo_generation_type': 'TEXT_2_VIDEO',
        'reference_images': [], 'v_reference_videos': [],
    }))
    assert response.status == 200, response.text
    miniapp.deduct_credits.assert_awaited_once()
    payload = launch.await_args.kwargs
    assert payload['model'] == model
    if model.startswith('veo3'):
        expected_mode = mode or 'FIRST_AND_LAST_FRAMES_2_VIDEO'
        assert payload['veo_generation_type'] == expected_mode
        assert [payload['image_url'], *payload['image_references']] == [FACE, FIXED]
        # Continue through the actual launch helper up to the mocked provider.
        from bot.services.veo_service import veo_service
        provider = AsyncMock(return_value={'task_id': 'synthetic-veo-accepted'})
        monkeypatch.setattr(veo_service, 'generate_video', provider)
        monkeypatch.setattr(miniapp, 'add_generation_task', AsyncMock(side_effect=RuntimeError('synthetic persistence stop')))
        with pytest.raises(RuntimeError, match='persistence stop'):
            await REAL_VIDEO_LAUNCH(**payload)
        assert provider.await_args.kwargs['generation_type'] == expected_mode
        assert provider.await_args.kwargs['image_urls'] == [FACE, FIXED]
    else:
        assert payload['image_references'] == [FACE, FIXED]


@pytest.mark.asyncio
async def test_motion_control_typed_recipe_is_unavailable_before_delegate(typed_video_entrypoint):
    entry = typed_video_entrypoint
    entry.source.update(model='motion_control_v26',
        feed_repeat_reference_selection={'version': 1, 'images': [], 'videos': []},
        request_data={'v_type': 'motion_control', 'motion_image_url': FACE, 'motion_video_url': MOTION})
    assert video_repeat_descriptors(entry.source)['available'] is False
    response = await entry.call(entry.request({'v_type': 'motion', 'reference_images': [], 'v_reference_videos': []}))
    assert response.status == 400
    entry.delegate.assert_not_awaited()


@pytest.mark.asyncio
async def test_full_unpublish_installed_http_revokes_grant_and_deeplink_repeat(monkeypatch):
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer

    from bot.handlers import publication_scope_compat as publication
    owner = await create_video()
    viewer = await database.get_or_create_user(880102)
    card = await database.share_to_feed('typed-private-video', owner.id,
        repeat_reference_image_indices=[1], repeat_reference_video_indices=[1])
    current_user = {'user': owner}
    async def context(*_args):
        actor = current_user['user']
        return actor.telegram_id, {'user': actor}
    monkeypatch.setattr(miniapp, '_get_user_context', context)
    monkeypatch.setattr(miniapp, 'deduct_credits', AsyncMock())
    monkeypatch.setattr(miniapp, '_launch_video_generation_task', AsyncMock())
    monkeypatch.setattr(miniapp, 'miniapp_generation_share', miniapp.miniapp_generation_share)
    publication._patch_miniapp_module(miniapp)
    app = web.Application()
    miniapp.setup_miniapp_routes(app)
    # Route integration only: do not start background provider reconciliation.
    app.on_startup.clear()
    root = '/' + (miniapp.config.MINI_APP_PATH or '/mini-app').strip('/') + '/api'
    async with TestClient(TestServer(app)) as client:
        current_user['user'] = viewer
        denied = await client.post(root + '/generations/share', json={
            'init_data': 'signed', 'task_id': 'typed-private-video', 'publication_scope': 'private'})
        assert not (await denied.json()).get('removed')
        current = await database.get_generation_task_payload(card['id'])
        assert current['is_public_feed']
        current_user['user'] = owner
        response = await client.post(root + '/generations/share', json={
            'init_data': 'signed', 'task_id': 'typed-private-video', 'publication_scope': 'private'})
        assert response.status == 200
        assert (await response.json())['removed'] is True
        current = await database.get_generation_task_payload(card['id'])
        assert not current['is_public_feed'] and not current['is_profile_visible']
        assert json.loads(current['feed_repeat_reference_selection']) == {'version': 1, 'images': [], 'videos': []}
        current_user['user'] = viewer
        repeat = await client.post(root + '/generate-video', json={
            'init_data': 'signed', 'source_feed_gen_id': card['id'], 'v_model': 'seedance_2_5',
            'v_type': 'video', 'reference_images': ['https://example.test/own.png'],
            'v_reference_videos': ['https://example.test/own.mp4']})
        assert repeat.status in (403, 404)
        miniapp.deduct_credits.assert_not_awaited()
        miniapp._launch_video_generation_task.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['owner', 'legacy'])
async def test_motion_control_original_owner_and_legacy_continuity_unchanged(typed_video_entrypoint, mode):
    entry = typed_video_entrypoint
    entry.source.update(model='motion_control_v26',
        request_data={'v_type': 'motion_control', 'motion_image_url': FACE, 'motion_video_url': MOTION})
    if mode == 'owner':
        entry.source['user_id'] = 2
    else:
        entry.source['feed_repeat_reference_selection'] = None
    assert (await entry.call(entry.request({}))).status == 200
    entry.delegate.assert_awaited_once()


@pytest.mark.asyncio
async def test_author_motion_control_selection_rejected_without_publication_mutation():
    owner = await database.get_or_create_user(881011)
    await database.add_generation_task(owner.id, owner.telegram_id, 'typed-motion', 'video', 'motion_control_v26',
        model='motion_control_v26', request_data={'v_type': 'motion_control',
            'motion_image_url': FACE, 'motion_video_url': MOTION, 'reference_images': [FACE]})
    await database.complete_video_task('typed-motion', 'https://example.test/result.mp4')
    with pytest.raises(ValueError, match='Motion Control'):
        await database.share_to_feed('typed-motion', owner.id,
            repeat_reference_image_indices=[0], repeat_reference_video_indices=[])
    source = await database.get_generation_task_payload('typed-motion')
    assert not source['is_public_feed']
    assert source['feed_repeat_reference_selection'] is None


@pytest.mark.asyncio
async def test_veo_source_mode_change_during_affordability_blocks_before_debit(monkeypatch, typed_video_entrypoint):
    entry = typed_video_entrypoint
    entry.source.update(model='veo3_fast', is_public_feed=True,
        feed_repeat_reference_selection={'version': 1, 'images': [FACE, FIXED], 'videos': []},
        request_data={'v_type': 'imgtxt', 'reference_images': [FACE, FIXED], 'veo_generation_type': 'REFERENCE_2_VIDEO'})
    entry.delegate.side_effect = REAL_GENERIC
    monkeypatch.setattr(miniapp, 'get_generation_task_payload', AsyncMock(side_effect=lambda *_: dict(entry.source)))
    monkeypatch.setattr(miniapp.config, 'is_admin', lambda _: False)
    monkeypatch.setattr(miniapp, 'missing_local_upload_sources', lambda _: [])
    monkeypatch.setattr(miniapp, 'touch_saved_references', AsyncMock())
    monkeypatch.setattr(miniapp.preset_manager, 'get_video_cost_with_quality', lambda *_: 1)
    async def change_mode(*_args):
        entry.source['request_data']['veo_generation_type'] = 'TEXT_2_VIDEO'
        return True
    monkeypatch.setattr(miniapp, 'check_can_afford', AsyncMock(side_effect=change_mode))
    debit = AsyncMock(return_value=True)
    launch = AsyncMock(return_value={'status': 'queued', 'task_id': 'synthetic-mode'})
    monkeypatch.setattr(miniapp, 'deduct_credits', debit)
    monkeypatch.setattr(miniapp, '_launch_video_generation_task', launch)
    monkeypatch.setattr(miniapp, 'credit_feed_prompt_repeat', AsyncMock())
    monkeypatch.setattr(miniapp, 'get_or_create_user', AsyncMock(return_value=SimpleNamespace(credits=99)))
    response = await entry.call(entry.request({'v_model': 'veo3_fast', 'v_type': 'imgtxt', 'v_duration': 6,
        'v_ratio': '9:16', 'veo_generation_type': 'TEXT_2_VIDEO', 'reference_images': [], 'v_reference_videos': []}))
    assert response.status == 400
    debit.assert_not_awaited()
    launch.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('scenario,mode,images', [
    ('imgtxt', 'TEXT_2_VIDEO', [FACE, FIXED]),
    ('text', 'REFERENCE_2_VIDEO', [FACE, FIXED]),
    ('imgtxt', 'REFERENCE_2_VIDEO', [FACE, FIXED, 'https://example.test/third.png']),
])
async def test_typed_veo_never_offers_inputs_ignored_by_existing_provider_adapter(typed_video_entrypoint, scenario, mode, images):
    entry = typed_video_entrypoint
    entry.source.update(model='veo3_fast',
        feed_repeat_reference_selection={'version': 1, 'images': images, 'videos': []},
        request_data={'v_type': scenario, 'reference_images': images, 'veo_generation_type': mode})
    assert video_repeat_descriptors(entry.source)['available'] is False
    response = await entry.call(entry.request({'v_model': 'veo3_fast', 'v_type': scenario,
        'reference_images': [], 'v_reference_videos': [], 'veo_generation_type': 'TEXT_2_VIDEO'}))
    assert response.status == 400
    entry.delegate.assert_not_awaited()


def test_typed_veo_text_only_source_remains_available(typed_video_entrypoint):
    entry = typed_video_entrypoint
    entry.source.update(model='veo3_fast',
        feed_repeat_reference_selection={'version': 1, 'images': [], 'videos': []},
        request_data={'v_type': 'text', 'veo_generation_type': 'TEXT_2_VIDEO'})
    descriptor = video_repeat_descriptors(entry.source)
    assert descriptor['available'] is True
    assert descriptor['images'] == [] and descriptor['videos'] == []


@pytest.mark.asyncio
async def test_actual_generic_writer_audio_list_cannot_be_granted_as_image_video_recipe(monkeypatch):
    from bot.services.seedance_service import seedance_service
    owner = await database.get_or_create_user(881020)
    monkeypatch.setattr(seedance_service, 'generate_video', AsyncMock(return_value={'task_id': 'synthetic-audio-source'}))
    monkeypatch.setattr(miniapp.preset_manager, 'get_video_cost_with_quality', lambda *_: 1)
    await REAL_VIDEO_LAUNCH(
        telegram_id=owner.telegram_id, user=owner, model='seedance_2', prompt='Synthetic recipe',
        duration=5, aspect_ratio='9:16', generation_type='video', image_url=None,
        image_references=[FIXED], video_references=[], audio_url=None,
        audio_references=['https://example.test/synthetic-audio.mp3'],
    )
    await database.complete_video_task('synthetic-audio-source', 'https://example.test/result.mp4')
    source = await database.get_generation_task_payload('synthetic-audio-source')
    data = source['request_data']
    assert data['v_reference_audio'] == ['https://example.test/synthetic-audio.mp3']
    assert data['audio_url'] is None
    with pytest.raises(ValueError, match='аудио'):
        await database.share_to_feed('synthetic-audio-source', owner.id,
            repeat_reference_image_indices=[0], repeat_reference_video_indices=[])
    source['feed_repeat_reference_selection'] = {'version': 1, 'images': [FIXED], 'videos': []}
    assert video_repeat_descriptors(source)['available'] is False


@pytest.mark.asyncio
async def test_typed_canonical_source_audio_blocks_public_entrypoint(typed_video_entrypoint):
    entry = typed_video_entrypoint
    entry.source['request_data']['v_reference_audio'] = ['https://example.test/synthetic-audio.mp3']
    response = await entry.call(entry.request({'reference_images': ['https://example.test/own.png'],
        'v_reference_videos': ['https://example.test/own.mp4']}))
    assert response.status == 400
    entry.delegate.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('quality', ['480p', '720p'])
async def test_typed_seedance_duration_quote_matches_actual_restored_quality_debit(monkeypatch, typed_video_entrypoint, quality):
    from bot.handlers import seedance_25_public_release as public
    entry = typed_video_entrypoint
    entry.source['is_public_feed'] = True
    entry.source['request_data']['seedance25_resolution'] = quality
    miniapp._get_repeat_source_card.return_value.update(model='seedance_2_5')
    monkeypatch.setattr(miniapp.preset_manager, 'get_video_cost_with_quality',
        lambda _model, duration, resolution: duration * (2 if resolution == '480p' else 5))
    descriptor = video_repeat_descriptors(entry.source)
    assert descriptor['pricing_quality'] == quality
    assert descriptor['duration_costs']['6'] == (24 if quality == '480p' else 60)
    assert FIXED not in json.dumps(descriptor) and STYLE not in json.dumps(descriptor)
    async def delegate(request):
        return await public._public_miniapp_generate(request, await request.json())
    entry.delegate.side_effect = delegate
    monkeypatch.setattr(miniapp.config, 'is_admin', lambda _: False)
    monkeypatch.setattr(public, '_validate_public_payload', AsyncMock())
    monkeypatch.setattr(miniapp, 'check_can_afford', AsyncMock(return_value=True))
    monkeypatch.setattr(miniapp, 'deduct_credits', AsyncMock(return_value=True))
    monkeypatch.setattr(public.seedance_25_service, 'generate_video', AsyncMock(return_value={'task_id': 'synthetic-quality'}))
    monkeypatch.setattr(public.generation_module, 'add_generation_task', AsyncMock())
    monkeypatch.setattr(miniapp, 'credit_feed_prompt_repeat', AsyncMock())
    monkeypatch.setattr(miniapp, 'get_or_create_user', AsyncMock(return_value=SimpleNamespace(credits=100)))
    response = await entry.call(entry.request({'v_model': 'seedance_2_5', 'v_type': 'video',
        'v_duration': 6, 'v_ratio': '9:16', 'seedance25_resolution': '720p',
        'reference_images': ['https://example.test/own.png'], 'v_reference_videos': ['https://example.test/own.mp4']}))
    assert response.status == 200, response.text
    miniapp.deduct_credits.assert_awaited_once_with(880102, descriptor['duration_costs']['6'])
    assert public.seedance_25_service.generate_video.await_args.kwargs['resolution'] == quality


@pytest.mark.asyncio
async def test_canonical_source_audio_is_replaced_only_by_explicit_viewer_audio(typed_video_entrypoint):
    entry = typed_video_entrypoint
    source_audio = 'https://example.test/synthetic-source-audio.mp3'
    own_audio = 'https://example.test/synthetic-viewer-audio.mp3'
    entry.source['request_data']['v_reference_audio'] = [source_audio]
    request = entry.request({'reference_images': ['https://example.test/own.png'],
        'v_reference_videos': ['https://example.test/own.mp4'], 'audio_references': [own_audio]})
    assert (await entry.call(request)).status == 200
    payload = await request.json()
    assert source_audio not in json.dumps(payload)
    assert payload['seedance25_reference_audio_urls'] == [own_audio]
    assert '_private_repeat_reference_audios' not in payload
