"""Identity transfer contracts: roles, pricing and pre-charge validation."""
from unittest.mock import AsyncMock

import pytest

from bot.handlers.seedance_25_public_release import (
    _launch_provider as real_launch_provider,
)
from bot.services.seedance_25_service import Seedance25Service


@pytest.fixture(autouse=True)
def isolated_database():
    yield


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [1, 2, 3])
async def test_explicit_identity_assigns_roles_and_preserves_order(count):
    service = Seedance25Service(kie_key="mock-key")
    service._kie_post = AsyncMock(return_value={"task_id": "identity-test"})
    images = [f"https://example.test/identity-{i}.jpg" for i in range(count)]
    result = await service.generate_video(
        "Keep the dance", identity_transfer=True, duration=15, aspect_ratio="9:16",
        reference_image_urls=images, reference_video_urls=["https://example.test/source.mp4"],
    )
    assert result["success"] is True
    payload = service._kie_post.call_args.args[1]
    assert payload["model"] == "bytedance/seedance-2-5"
    assert payload["input"]["reference_image_urls"] == images
    assert payload["input"]["duration"] == -1
    assert payload["input"]["aspect_ratio"] == "adaptive"
    assert payload["input"]["prompt"].startswith("Video edit:")
    assert "@Video1" in payload["input"]["prompt"]
    for index in range(1, count + 1):
        assert f"@Image{index}" in payload["input"]["prompt"]
    assert "sole authoritative" not in payload["input"]["prompt"]
    assert payload["input"]["omni_reference_task_type"] == "edit"
    assert payload["input"]["prompt"].endswith("Keep the dance")
    assert "identity_transfer" not in payload["input"]


@pytest.mark.asyncio
@pytest.mark.parametrize("images,videos,extra", [
    ([], ["v"], {}), (["i"], [], {}),
    (["i1", "i2", "i3", "i4"], ["v"], {}), (["i"], ["v1", "v2"], {}),
    (["i"], ["v"], {"reference_audio_urls": ["a"]}),
    (["i"], ["v"], {"first_frame_url": "f"}),
    (["i"], ["v"], {"last_frame_url": "f"}),
])
async def test_invalid_identity_refs_never_submit(images, videos, extra):
    service = Seedance25Service(kie_key="mock-key")
    service._kie_post = AsyncMock()
    result = await service.generate_video("", identity_transfer=True,
        reference_image_urls=images, reference_video_urls=videos, **extra)
    assert result["success"] is False
    service._kie_post.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("prompt", ["x" * 30001, "x" * 29990, "Use @Image4", "Use @Video2"])
async def test_original_and_expanded_prompt_limits_and_tags(prompt):
    service = Seedance25Service(kie_key="mock-key")
    service._kie_post = AsyncMock()
    result = await service.generate_video(prompt, identity_transfer=True,
        reference_image_urls=["i"], reference_video_urls=["v"])
    assert result["success"] is False
    service._kie_post.assert_not_awaited()


@pytest.mark.asyncio
async def test_ordinary_references_keep_fifteen_seconds_and_prompt():
    service = Seedance25Service(kie_key="mock-key")
    service._kie_post = AsyncMock(return_value={"task_id": "ordinary"})
    await service.generate_video("Use @Image1 and @Video1", duration=15, aspect_ratio="9:16",
        reference_image_urls=["i"], reference_video_urls=["v"])
    payload = service._kie_post.call_args.args[1]["input"]
    assert (payload["duration"], payload["aspect_ratio"]) == (15, "9:16")
    assert payload["prompt"] == "Use @Image1 and @Video1"


def identity_body(**overrides):
    return dict({"v_model": "seedance_2_5", "seedance25_scenario": "multimodal",
        "seedance25_identity_transfer": True, "v_duration": 15, "v_ratio": "9:16",
        "reference_images": ["https://example.test/uploads/refs/image/123/202610/i.jpg"],
        "v_reference_videos": ["https://example.test/uploads/refs/video/123/202610/v.mp4"],
        "seedance25_resolution": "720p", "prompt": "Keep the dance"}, **overrides)


@pytest.fixture
def public_mocks(monkeypatch):
    from types import SimpleNamespace

    from bot import miniapp
    from bot.handlers import seedance_25_public_release as public
    user = SimpleNamespace(id=1, credits=1000)
    monkeypatch.setattr(miniapp, "_get_user_context", AsyncMock(return_value=(123, {"user": user})))
    monkeypatch.setattr(public.config, "is_admin", lambda _: False)
    monkeypatch.setattr(public, "_identity_local_path", lambda *_: "mock-owned-path")
    monkeypatch.setattr(public.fullstack, "_validate_local_source", AsyncMock(return_value=12.2))
    monkeypatch.setattr(public.fullstack, "_validate_seedance_sources", AsyncMock())
    # Current configured rate: 4 bananas/second; existing video-reference factor = 2.
    monkeypatch.setattr(public.preset_manager, "get_video_cost_with_quality", lambda _m, d, _q: d * 4)
    for name, value in (("check_can_afford", True), ("deduct_credits", None), ("add_credits", None), ("get_or_create_user", user)):
        monkeypatch.setattr(miniapp, name, AsyncMock(return_value=value))
    monkeypatch.setattr(public, "_launch_provider", AsyncMock(return_value={"task_id": "paid-identity"}))
    monkeypatch.setattr(public.generation_module, "add_generation_task", AsyncMock())
    return public, miniapp, SimpleNamespace(app={})


@pytest.mark.asyncio
async def test_paid_identity_quote_debit_and_persistence_match(public_mocks):
    import json
    public, miniapp, request = public_mocks
    body = identity_body(seedance25_quote_only=True)
    response = await public._public_miniapp_generate(request, body)
    assert response.status == 200
    quote = json.loads(response.body)
    assert quote["cost"] == 104  # ceil(12.2) * 4 * 2
    assert quote["billing_duration"] == 13
    assert quote["source_video_duration_seconds"] == 12.2
    miniapp.deduct_credits.assert_not_awaited()
    public._launch_provider.assert_not_awaited()
    public.generation_module.add_generation_task.assert_not_awaited()
    body.update(seedance25_quote_only=False, seedance25_identity_quote=quote["seedance25_identity_quote"])
    response = await public._public_miniapp_generate(request, body)
    assert response.status == 200
    miniapp.deduct_credits.assert_awaited_once_with(123, 104)
    payload = public._launch_provider.call_args.args[0]
    assert (payload["duration"], payload["ratio"], payload["billing_duration"]) == (-1, "adaptive", 13)
    record = public.generation_module.add_generation_task.call_args.kwargs
    assert record["prompt"] == "Keep the dance"
    assert record["cost"] == record["request_data"]["charged_cost"] == 104
    assert record["request_data"]["seedance25_identity_role_version"] == "direct-edit-v1"
    assert record["request_data"]["seedance25_video_editing"] is True
    assert record["request_data"]["seedance25_identity_transfer"] is True
    assert "authoritative" not in str(record)


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [
    {"prompt": "x" * 29990}, {"prompt": "Use @Image4"},
    {"reference_images": []}, {"reference_images": ["a", "b", "c", "d"]},
    {"v_reference_videos": []}, {"v_reference_videos": ["a", "b"]},
    {"seedance25_first_frame_url": "f"}, {"seedance25_last_frame_url": "f"},
    {"seedance25_reference_audio_urls": ["a"]}, {"seedance25_scenario": "text"},
    {"seedance25_identity_transfer": "true"}, {"seedance25_identity_transfer": 1},
    {"seedance25_identity_transfer": None}, {"identityTransfer": False},
])
async def test_invalid_public_identity_fails_before_any_paid_action(public_mocks, changes):
    public, miniapp, request = public_mocks
    response = await public._public_miniapp_generate(request, identity_body(**changes))
    assert response.status == 400
    miniapp.deduct_credits.assert_not_awaited()
    public._launch_provider.assert_not_awaited()
    public.generation_module.add_generation_task.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("measured", [None, 3.99, 30.01, float("nan"), float("inf")])
async def test_unknown_or_invalid_duration_cannot_quote_or_charge(public_mocks, measured):
    public, miniapp, request = public_mocks
    public.fullstack._validate_local_source.return_value = measured
    response = await public._public_miniapp_generate(request, identity_body(seedance25_quote_only=True))
    assert response.status == 400
    miniapp.deduct_credits.assert_not_awaited()
    public._launch_provider.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("changed", ["price", "duration", "source", "resolution", "missing"])
async def test_stale_or_missing_quote_cannot_charge(public_mocks, monkeypatch, changed):
    import json
    public, miniapp, request = public_mocks
    body = identity_body(seedance25_quote_only=True)
    quote = json.loads((await public._public_miniapp_generate(request, body)).body)["seedance25_identity_quote"]
    body.update(seedance25_quote_only=False, seedance25_identity_quote=quote)
    if changed == "price":
        monkeypatch.setattr(public.preset_manager, "get_video_cost_with_quality", lambda *_: 99)
    elif changed == "duration":
        public.fullstack._validate_local_source.return_value = 15
    elif changed == "source":
        body["v_reference_videos"] = ["https://example.test/new.mp4"]
    elif changed == "resolution":
        body["seedance25_resolution"] = "480p"
    else:
        body.pop("seedance25_identity_quote")
    response = await public._public_miniapp_generate(request, body)
    assert response.status == 400
    miniapp.deduct_credits.assert_not_awaited()
    public._launch_provider.assert_not_awaited()


def test_identity_paths_require_owner_and_realpath_containment(tmp_path, monkeypatch):
    from bot.handlers import seedance_25_public_release as public
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(public.config, "STATIC_BASE_URL", "https://example.test")
    root = tmp_path / "static/uploads/refs/video/123/202610"
    root.mkdir(parents=True)
    video = root / "video.mp4"
    video.write_bytes(b"mock")
    monkeypatch.setattr(public.fullstack, "resolve_local_upload_path", lambda _: str(video))
    source = "https://example.test/uploads/refs/video/123/202610/video.mp4"
    assert public._identity_local_path(source, "video", 123) == str(video)
    for bad in (source.replace("/123/", "/456/"), source.replace("202610/", "../"), source.replace("202610/", "%2e%2e/"), source.replace("example.test", "example.test:444"), source.replace("https://", "https://user@"), source + "?other=file", "asset://x"):
        with pytest.raises(ValueError):
            public._identity_local_path(bad, "video", 123)
    other = tmp_path / "outside.mp4"
    other.write_bytes(b"mock")
    video.unlink()
    video.symlink_to(other)
    with pytest.raises(ValueError):
        public._identity_local_path(source, "video", 123)


@pytest.mark.asyncio
@pytest.mark.parametrize("admin_free", [True, False])
async def test_identity_never_implicitly_retries(monkeypatch, admin_free):
    import json

    from bot.handlers import seedance_25_fullstack as fullstack
    monkeypatch.setattr(fullstack, "_load_task_row", AsyncMock(return_value={
        "status": "pending", "model": "seedance_2_5", "type": "video",
        "request_data": json.dumps({"admin_free": admin_free, "seedance25_identity_transfer": True}),
    }))
    generate = AsyncMock()
    monkeypatch.setattr(fullstack.seedance_25_service, "generate_video", generate)
    assert await fullstack._auto_retry_seedance25_video_editing("mock", "video editing duration must be -1") is False
    generate.assert_not_awaited()


def test_identity_repeat_preserves_explicit_choice():
    from bot.handlers.miniapp_video_continuity_compat import enrich_video_repeat_body
    from bot.video_generation_contract import normalize_video_request
    assert normalize_video_request(identity_body())["seedance25_identity_transfer"] is True
    source = {"model": "seedance_2_5", "duration": -1, "aspect_ratio": "adaptive", "prompt": "original", "request_data": identity_body()}
    repeated = enrich_video_repeat_body({"source_feed_gen_id": 1}, source)
    assert repeated["seedance25_identity_transfer"] is True
    assert (repeated["v_duration"], repeated["v_ratio"]) == (-1, "adaptive")
    assert enrich_video_repeat_body({"source_feed_gen_id": 1, "seedance25_identity_transfer": False}, source)["seedance25_identity_transfer"] is False


@pytest.mark.asyncio
async def test_telegram_shows_current_quote_and_uses_callback_actor(public_mocks, monkeypatch):
    from types import SimpleNamespace
    public, _miniapp, _request = public_mocks
    data = identity_body()
    state = SimpleNamespace(get_data=AsyncMock(side_effect=lambda: dict(data)), clear=AsyncMock(), set_state=AsyncMock())
    async def update(**values):
        data.update(values)
    state.update_data = AsyncMock(side_effect=update)
    bot_message = SimpleNamespace(from_user=SimpleNamespace(id=999), answer=AsyncMock())
    bot_message.answer.return_value = SimpleNamespace(delete=AsyncMock())
    owner_check = __import__('unittest.mock', fromlist=['Mock']).Mock(return_value="mock-owned")
    monkeypatch.setattr(public, "_identity_local_path", owner_check)
    monkeypatch.setattr(public.generation_module, "check_can_afford", AsyncMock(return_value=True))
    monkeypatch.setattr(public.generation_module, "deduct_credits", AsyncMock())
    monkeypatch.setattr(public.generation_module, "get_or_create_user", AsyncMock(return_value=SimpleNamespace(id=1)))
    await public._public_show_screen(bot_message, state, edit=False, actor_id=123)
    assert "104" in bot_message.answer.call_args.args[0]
    assert "Замена персонажа" in bot_message.answer.call_args.args[0]
    assert data["seedance25_identity_quote"]["cost"] == 104
    await public._public_message_launch(bot_message, state, "Keep the dance", actor_id=123)
    public.generation_module.deduct_credits.assert_awaited_once_with(123, 104)
    assert all(call.args[2] == 123 for call in owner_check.call_args_list)


@pytest.mark.asyncio
async def test_telegram_stale_quote_requotes_without_debit(public_mocks, monkeypatch):
    from types import SimpleNamespace
    public, _miniapp, _request = public_mocks
    state = SimpleNamespace(get_data=AsyncMock(return_value=identity_body(seedance25_identity_quote={"cost": 1})))
    message = SimpleNamespace(from_user=SimpleNamespace(id=123), answer=AsyncMock())
    monkeypatch.setattr(public, "_public_show_screen", AsyncMock())
    monkeypatch.setattr(public.generation_module, "deduct_credits", AsyncMock())
    await public._public_message_launch(message, state, "Keep dance")
    public._public_show_screen.assert_awaited_once()
    public.generation_module.deduct_credits.assert_not_awaited()
    public._launch_provider.assert_not_awaited()


def test_effective_telegram_keyboard_and_repeat_keep_identity():
    from types import SimpleNamespace

    from bot.handlers import seedance_25_telegram_compat as telegram
    data = identity_body()
    keyboard = telegram._clear_seedance_keyboard(data)
    callbacks = [button.callback_data for row in keyboard.inline_keyboard for button in row]
    assert "s25_toggle_identity" in callbacks
    assert "s25_duration_plus" not in callbacks
    assert "s25_ratio_16_9" not in callbacks
    restored = telegram._repeat_state_payload(SimpleNamespace(duration=-1, aspect_ratio="adaptive"), data, "original")
    assert restored["seedance25_identity_transfer"] is True
    assert restored["seedance25_identity_quote"] is None


@pytest.mark.asyncio
async def test_completed_identity_caption_shows_source_and_billing(public_mocks):
    from types import SimpleNamespace
    public, _miniapp, _request = public_mocks
    bot = SimpleNamespace(send_video=AsyncMock(), send_message=AsyncMock())
    await public._public_send_results({"bot": bot}, 123, "mock-result", "https://example.test/result.mp4", None,
        {"seedance25_identity_transfer": True, "seedance25_scenario": "multimodal", "duration": -1,
         "source_video_duration_seconds": 12.2, "billing_duration": 13, "charged_cost": 104})
    caption = bot.send_video.call_args.kwargs["caption"]
    assert "Замена персонажа" in caption
    assert "12.2с" in caption and "13с" in caption and "104" in caption
    assert "Auto" not in caption


@pytest.mark.asyncio
async def test_paid_launch_captures_exact_kie_contract(public_mocks, monkeypatch):
    import json
    public, miniapp, request = public_mocks
    monkeypatch.setattr(public, "_launch_provider", real_launch_provider)
    monkeypatch.setattr(public.seedance_25_service, "kie_key", "mock-key")
    post = AsyncMock(return_value={"task_id": "captured-identity"})
    monkeypatch.setattr(public.seedance_25_service, "_kie_post", post)
    body = identity_body(seedance25_quote_only=True)
    quote = json.loads((await public._public_miniapp_generate(request, body)).body)["seedance25_identity_quote"]
    post.assert_not_awaited()
    body.update(seedance25_quote_only=False, seedance25_identity_quote=quote)
    response = await public._public_miniapp_generate(request, body)
    assert response.status == 200
    post.assert_awaited_once()
    path, payload = post.call_args.args
    assert path == "/api/v1/jobs/createTask"
    assert payload["model"] == "bytedance/seedance-2-5"
    assert payload["input"]["duration"] == -1
    assert payload["input"]["aspect_ratio"] == "adaptive"
    assert payload["input"]["reference_image_urls"] == body["reference_images"]
    assert payload["input"]["reference_video_urls"] == body["v_reference_videos"]
    assert payload["input"]["prompt"].startswith("Video edit:")
    assert "@Video1" in payload["input"]["prompt"]
    assert payload["input"]["omni_reference_task_type"] == "edit"
    assert "identity_transfer" not in payload["input"] and "video_editing" not in payload["input"]
    assert "billing_duration" not in payload["input"]
    miniapp.deduct_credits.assert_awaited_once_with(123, 104)


@pytest.mark.asyncio
async def test_telegram_identity_mode_preserves_inactive_media_on_normal_switch(monkeypatch):
    from types import SimpleNamespace

    from bot.handlers import seedance_25_preview as preview
    data = identity_body(seedance25_identity_transfer=False, seedance25_reference_audio_urls=["audio"], seedance25_first_frame_url="first")
    state = SimpleNamespace()
    async def update(**values):
        data.update(values)
    state.update_data = AsyncMock(side_effect=update)
    monkeypatch.setattr(preview, "_assert_preview", AsyncMock(side_effect=lambda *_: dict(data)))
    monkeypatch.setattr(preview, "_show_seedance_25_screen", AsyncMock())
    callback = SimpleNamespace(from_user=SimpleNamespace(id=123), data="s25_toggle_identity", answer=AsyncMock())
    await preview.seedance25_toggle_identity(callback, state)
    assert data["seedance25_reference_audio_urls"] == []
    assert data["seedance25_identity_inactive_media"]["seedance25_first_frame_url"] == "first"
    callback.data = "s25_scenario_multimodal"
    await preview.seedance25_scenario(callback, state)
    assert data["seedance25_identity_transfer"] is False
    assert data["seedance25_reference_audio_urls"] == ["audio"]
    await preview.seedance25_toggle_identity(callback, state)
    assert data["seedance25_identity_inactive_media"]["seedance25_first_frame_url"] == "first"
    assert data["seedance25_identity_inactive_media"]["seedance25_reference_audio_urls"] == ["audio"]


@pytest.mark.asyncio
@pytest.mark.parametrize("flag", ["true", 1, None])
async def test_malformed_quote_only_cannot_launch_even_for_admin(public_mocks, monkeypatch, flag):
    public, miniapp, request = public_mocks
    monkeypatch.setattr(public.config, "is_admin", lambda _: True)
    response = await public._public_miniapp_generate(request, identity_body(seedance25_quote_only=flag))
    assert response.status == 400
    public._launch_provider.assert_not_awaited()
    miniapp.deduct_credits.assert_not_awaited()


@pytest.mark.parametrize("key", ["reference_images", "v_reference_videos", "seedance25_reference_audio_urls"])
def test_explicit_identity_repeat_never_resurrects_removed_media(key):
    from bot.handlers.miniapp_video_continuity_compat import enrich_video_repeat_body
    source = {"model": "seedance_2_5", "prompt": "private original", "request_data": identity_body(seedance25_reference_audio_urls=["private-audio"])}
    body = identity_body(prompt="", **{key: []})
    restored = enrich_video_repeat_body(body, source)
    assert restored[key] == []
    assert restored["prompt"] == "private original"
    assert restored["seedance25_scenario"] == "multimodal"


def test_explicit_identity_repeat_preserves_new_scenario_for_validation():
    from bot.handlers.miniapp_video_continuity_compat import enrich_video_repeat_body
    source = {"model": "seedance_2_5", "prompt": "private original", "request_data": identity_body()}
    restored = enrich_video_repeat_body(identity_body(seedance25_scenario="text"), source)
    assert restored["seedance25_scenario"] == "text"


def test_omitted_identity_repeat_media_can_restore_original_selection():
    from bot.handlers.miniapp_video_continuity_compat import enrich_video_repeat_body
    source = {"model": "seedance_2_5", "prompt": "private original", "request_data": identity_body()}
    restored = enrich_video_repeat_body({"seedance25_identity_transfer": True}, source)
    assert restored["reference_images"] == source["request_data"]["reference_images"]
    assert restored["v_reference_videos"] == source["request_data"]["v_reference_videos"]


@pytest.mark.asyncio
async def test_identity_quote_binds_repeat_lineage(public_mocks, monkeypatch):
    import json
    public, miniapp, request = public_mocks
    monkeypatch.setattr(miniapp, "_get_repeat_source_card", AsyncMock(return_value={"gen_type": "video", "model": "seedance_2_5", "source_feed_gen_id": 100}))
    body = identity_body(source_feed_gen_id=1, seedance25_quote_only=True)
    quote = json.loads((await public._public_miniapp_generate(request, body)).body)["seedance25_identity_quote"]
    assert quote["source_feed_gen_id"] == 100
    assert quote["parent_generation_id"] == 1
    body.update(source_feed_gen_id=2, seedance25_quote_only=False, seedance25_identity_quote=quote)
    response = await public._public_miniapp_generate(request, body)
    assert response.status == 400
    miniapp.deduct_credits.assert_not_awaited()
    public._launch_provider.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("selection", [
    "complete", "omitted_images", "omitted_videos", "empty_images", "empty_videos", "wrong_owner",
])
async def test_explicit_identity_repeat_quotes_only_required_current_media(
    public_mocks, monkeypatch, selection,
):
    import json

    from bot.handlers import miniapp_video_continuity_compat as continuity

    public, miniapp, _request = public_mocks
    source = {
        "model": "seedance_2_5", "prompt": "Synthetic original recipe",
        "feed_references_visible": True,
        "feed_reference_selection": {
            "images": ["https://example.test/old-image.png"],
            "videos": ["https://example.test/old-video.mp4"],
        },
        # Deliberately incomplete old snapshot: neither fixed input is needed
        # when the identity form explicitly replaces both complete media types.
        "request_data": {"seedance25_scenario": "multimodal"},
    }
    if selection == "wrong_owner":
        def reject_foreign_upload(*_args):
            raise ValueError("Загрузите своё исходное видео")
        monkeypatch.setattr(public, "_identity_local_path", reject_foreign_upload)
    body = identity_body(source_feed_gen_id=42, seedance25_quote_only=True)
    if selection == "omitted_images":
        body.pop("reference_images")
    elif selection == "omitted_videos":
        body.pop("v_reference_videos")
    elif selection == "empty_images":
        body["reference_images"] = []
    elif selection == "empty_videos":
        body["v_reference_videos"] = []

    class Request:
        def __init__(self):
            self.app = {}
            self._read_bytes = json.dumps(body).encode()

        async def json(self):
            return json.loads(self._read_bytes)

    async def quote_delegate(request):
        return await public._public_miniapp_generate(request, await request.json())

    delegate = AsyncMock(side_effect=quote_delegate)
    monkeypatch.setattr(miniapp, "miniapp_generate_video", delegate)
    monkeypatch.setattr(miniapp, "miniapp_feed_share", AsyncMock())
    monkeypatch.setattr(miniapp, "_video_continuity_compat_installed", False, raising=False)
    monkeypatch.setattr(miniapp, "_get_repeat_source_card", AsyncMock(return_value={
        "id": 42, "gen_type": "video", "model": "seedance_2_5",
        "reference_images": [], "reference_videos": [], "prompt_hidden": True,
    }))
    monkeypatch.setattr(continuity, "get_generation_task_payload", AsyncMock(return_value=source))
    monkeypatch.setattr(continuity, "missing_local_upload_sources", lambda _values: [])
    continuity.install_miniapp_video_continuity_compat()
    request = Request()
    response = await miniapp.miniapp_generate_video(request)

    if selection == "complete":
        assert response.status == 200
        result = json.loads(response.body)
        assert result["quote_only"] is True
        assert result["cost"] == 104
        restored = await request.json()
        assert restored["reference_images"] == body["reference_images"]
        assert restored["v_reference_videos"] == body["v_reference_videos"]
        delegate.assert_awaited_once()
    else:
        assert response.status == 400
        if selection.startswith("omitted"):
            assert json.loads(response.body)["code"] == "repeat_reference_incomplete"
            delegate.assert_not_awaited()
        else:
            # Explicit empties are removals, then the actual identity validator
            # rejects the missing required media rather than restoring old refs.
            delegate.assert_awaited_once()
    miniapp.deduct_credits.assert_not_awaited()
    public._launch_provider.assert_not_awaited()
    public.generation_module.add_generation_task.assert_not_awaited()


@pytest.mark.asyncio
async def test_direct_edit_freezes_configured_prompt_before_paid_launch(public_mocks, monkeypatch):
    from bot import database
    public, miniapp, _request = public_mocks
    template = "Video edit: replace the person in @Video1 using {identity_images}. Keep the coat."
    getter = AsyncMock(return_value=template)
    monkeypatch.setattr(database, "get_bot_setting", getter)
    payload = public._scenario_payload(identity_body(prompt=""), "")
    await public._validate_public_payload(payload, is_admin=False, telegram_id=123)
    frozen = template.replace("{identity_images}", "@Image1")
    assert payload["provider_prompt"] == frozen
    assert payload["prompt"] == ""
    getter.assert_awaited_once()
    monkeypatch.setattr(database, "get_bot_setting", AsyncMock(side_effect=AssertionError("configuration reread after validation")))
    monkeypatch.setattr(public.seedance_25_service, "kie_key", "mock-key")
    post = AsyncMock(return_value={"task_id": "frozen-direct-edit"})
    monkeypatch.setattr(public.seedance_25_service, "_kie_post", post)
    result = await real_launch_provider(payload)
    assert result["success"] is True
    post.assert_awaited_once()
    assert post.call_args.args[1]["input"]["prompt"] == frozen
    metadata = public._request_data(payload, is_admin=False, quote=104, source="miniapp")
    assert metadata["seedance25_provider_prompt_sha256"] == result["provider_prompt_sha256"]
    miniapp.deduct_credits.assert_not_awaited()


@pytest.mark.asyncio
async def test_invalid_configured_direct_template_stops_before_debit(public_mocks, monkeypatch):
    from bot import database
    public, miniapp, request = public_mocks
    monkeypatch.setattr(database, "get_bot_setting", AsyncMock(return_value="missing roles"))
    response = await public._public_miniapp_generate(request, identity_body(prompt=""))
    assert response.status == 400
    miniapp.deduct_credits.assert_not_awaited()
    public._launch_provider.assert_not_awaited()
    public.generation_module.add_generation_task.assert_not_awaited()
