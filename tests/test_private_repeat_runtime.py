"""Private repeat runtime boundaries. Synthetic SQLite rows; mocked providers only."""
import importlib
import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from bot import database
from bot import db as db_backend
from bot.handlers import generation
from bot.utils.user_facing_errors import make_user_friendly_generation_error

PRIVATE = "https://example.test/private-permission-marker.png"
OWN = "https://example.test/viewer-reference.png"
OTHER = "https://example.test/viewer-second.png"


class FakeState:
    def __init__(self, data=None):
        self.data = data or {}

    async def clear(self):
        self.data = {}

    async def update_data(self, **kwargs):
        self.data.update(kwargs)

    async def set_state(self, value):
        self.state = value

    async def get_data(self):
        return dict(self.data)


async def make_tasks(*, private_first=False, marker=True):
    author = await database.get_or_create_user(970101)
    viewer = await database.get_or_create_user(970102)
    root_refs = [PRIVATE, "https://example.test/author-face.png"] if private_first else [
        "https://example.test/author-face.png", PRIVATE
    ]
    await database.add_generation_task(
        author.id, author.telegram_id, "private-runtime-root", "image", "banana_pro",
        model="banana_pro", prompt="Synthetic Image1 and Image2 recipe",
        request_data={"source_reference_images": root_refs, "reference_images": root_refs},
    )
    await database.complete_video_task("private-runtime-root", "https://example.test/result.png")
    root_card = await database.share_to_feed(
        "private-runtime-root", author.id, references_visible=False,
        repeat_reference_image_indices=[0 if private_first else 1],
    )
    child_refs = [PRIVATE, OWN] if private_first else [OWN, PRIVATE]
    request = {
        "img_service": "banana_pro", "img_ratio": "1:1", "img_quality": "2K",
        "prompt": "Synthetic Image1 and Image2 recipe",
        "reference_images": child_refs, "source_reference_images": child_refs,
    }
    if marker:
        request["private_repeat_reference_images"] = [PRIVATE]
    await database.add_generation_task(
        viewer.id, viewer.telegram_id, "private-runtime-child", "image", "banana_pro",
        model="banana_pro", prompt=request["prompt"], cost=2, request_data=request,
        source_feed_gen_id=root_card["id"], parent_generation_id=root_card["id"],
        action_type="repeat",
    )
    child = await database.get_task_by_id("private-runtime-child")
    return author, viewer, root_card["id"], child


async def update_root(root_id, assignment, parameters=()):
    async with db_backend.connect(database.DATABASE_PATH) as conn:
        await conn.execute(f"UPDATE generation_tasks SET {assignment} WHERE id = ?", (*parameters, root_id))
        await conn.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["revoke", "withdraw", "child", "missing", "malformed", "unavailable"])
async def test_live_private_grant_validation_is_all_or_nothing(monkeypatch, change):
    _author, _viewer, root_id, _child = await make_tasks()
    assert await generation.validate_private_repeat_reference_access(
        source_feed_gen_id=root_id, private_reference_images=[PRIVATE]
    )
    if change == "revoke":
        await update_root(root_id, "feed_repeat_reference_selection = ?", ('{"images":[]}',))
    elif change == "withdraw":
        await update_root(root_id, "is_public_feed = 0, is_profile_visible = 0")
    elif change == "child":
        await update_root(root_id, "source_feed_gen_id = ?", (123456,))
    elif change == "missing":
        root_id = 987654
    elif change == "malformed":
        await update_root(root_id, "feed_repeat_reference_selection = ?", ('{"images":"bad"}',))
    else:
        monkeypatch.setattr(database, "_is_feed_result_url_available", lambda *_: False)
    assert not await generation.validate_private_repeat_reference_access(
        source_feed_gen_id=root_id, private_reference_images=[PRIVATE]
    )


@pytest.mark.asyncio
async def test_own_edit_parent_is_not_mistaken_for_foreign_lineage():
    _author, _viewer, root_id, _child = await make_tasks()
    await update_root(root_id, "parent_generation_id = ?", (123456,))
    assert await generation.validate_private_repeat_reference_access(
        source_feed_gen_id=root_id, private_reference_images=[PRIVATE]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("marker", [False, True])
async def test_child_restore_never_exposes_hidden_inputs_to_fsm(marker):
    _author, viewer, root_id, child = await make_tasks(marker=marker)
    state = FakeState()
    restored, error = await generation._restore_image_task_to_state(
        child, state, include_references=True, repeat_source_task_id=child.task_id,
    )
    assert restored and error is None
    assert state.data["reference_images"] == [OWN]
    assert PRIVATE not in json.dumps(state.data)
    assert state.data["repeat_prompt_hidden"] is True
    hidden, source_id = await generation._image_repeat_private_context(child, viewer.id)
    assert hidden == [PRIVATE]
    assert source_id == root_id


@pytest.mark.asyncio
async def test_legacy_public_inputs_remain_user_visible():
    _author, viewer, root_id, child = await make_tasks(marker=False)
    await update_root(
        root_id, "feed_references_visible = 1, feed_reference_selection = ?",
        (json.dumps({"images": [PRIVATE], "videos": []}),),
    )
    hidden, source_id = await generation._image_repeat_private_context(child, viewer.id)
    assert hidden == []
    assert source_id == root_id
    state = FakeState()
    restored, _ = await generation._restore_image_task_to_state(
        child, state, include_references=True, repeat_source_task_id=child.task_id
    )
    assert restored
    assert state.data["reference_images"] == [OWN, PRIVATE]


@pytest.mark.parametrize("sources,visible,hidden,expected", [
    ([PRIVATE, OWN], [OWN], [PRIVATE], [PRIVATE, OWN]),
    ([OWN, PRIVATE, OTHER], [OWN, OTHER], [PRIVATE], [OWN, PRIVATE, OTHER]),
    ([OWN, PRIVATE], [OTHER], [PRIVATE], [OTHER, PRIVATE]),
])
def test_hidden_reference_reinsertion_preserves_image_slots(sources, visible, hidden, expected):
    assert generation._merge_repeat_private_reference_slots(
        {"source_reference_images": sources}, visible, hidden
    ) == expected


def test_missing_identity_slot_cannot_silently_shift_hidden_reference():
    with pytest.raises(ValueError, match="missing_replacement"):
        generation._merge_repeat_private_reference_slots(
            {"source_reference_images": [OWN, PRIVATE]}, [], [PRIVATE]
        )


@pytest.mark.asyncio
async def test_central_launch_preserves_private_snapshot_without_logging_urls(monkeypatch, caplog):
    _author, viewer, root_id, child = await make_tasks(private_first=True)
    provider = AsyncMock(return_value={"task_id": "synthetic-private-provider"})
    monkeypatch.setattr(generation.nano_banana_pro_service, "generate_image", provider)
    caplog.set_level(logging.INFO)
    result = await generation._start_image_generation_task(
        user=viewer, telegram_id=viewer.telegram_id, img_service="banana_pro",
        prompt="Synthetic Image1 and Image2 recipe", img_ratio="1:1",
        reference_images=[PRIVATE, OWN], private_repeat_reference_images=[PRIVATE],
        source_feed_gen_id=root_id, parent_generation_id=child.id, action_type="repeat",
        unit_cost=0,
    )
    assert result["status"] == "queued"
    assert provider.await_args.kwargs["image_input"] == [PRIVATE, OWN]
    task = await database.get_generation_task_payload("synthetic-private-provider")
    assert task["request_data"]["private_repeat_reference_images"] == [PRIVATE]
    assert task["source_feed_gen_id"] == root_id
    assert task["parent_generation_id"] == child.id
    assert PRIVATE not in caplog.text
    assert OWN not in caplog.text


@pytest.mark.asyncio
async def test_central_launch_rejects_revoked_inputs_before_task_or_provider(monkeypatch):
    _author, viewer, root_id, child = await make_tasks()
    await update_root(root_id, "feed_repeat_reference_selection = ?", ('{"images":[]}',))
    provider = AsyncMock()
    add_task = AsyncMock()
    monkeypatch.setattr(generation.nano_banana_pro_service, "generate_image", provider)
    monkeypatch.setattr(generation, "add_generation_task", add_task)
    result = await generation._start_image_generation_task(
        user=viewer, telegram_id=viewer.telegram_id, img_service="banana_pro",
        prompt="Synthetic recipe", img_ratio="1:1", reference_images=[OWN, PRIVATE],
        private_repeat_reference_images=[PRIVATE], source_feed_gen_id=root_id,
        parent_generation_id=child.id, unit_cost=0,
    )
    assert result["status"] == "failed"
    assert result["error"] == "private_repeat_permission_unavailable"
    provider.assert_not_awaited()
    add_task.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("quick", [False, True])
@pytest.mark.parametrize("revoke", [False, True])
async def test_owner_child_repeat_preserves_lineage_and_checks_before_debit(monkeypatch, quick, revoke):
    _author, viewer, root_id, child = await make_tasks(private_first=True)
    state = FakeState()
    await generation._restore_image_task_to_state(
        child, state, include_references=True, repeat_source_task_id=child.task_id
    )
    if revoke:
        await update_root(root_id, "feed_repeat_reference_selection = ?", ('{"images":[]}',))
    progress = SimpleNamespace(delete=AsyncMock(), edit_text=AsyncMock())
    callback = SimpleNamespace(
        data=("repeat_run_confirm_" if quick else "repeat_run_") + child.task_id,
        from_user=SimpleNamespace(id=viewer.telegram_id),
        message=SimpleNamespace(answer=AsyncMock(return_value=progress)),
        answer=AsyncMock(),
    )
    launch = AsyncMock(return_value={"status": "queued", "task_id": "synthetic-next"})
    debit = AsyncMock(return_value=True)
    monkeypatch.setattr(generation, "_start_image_generation_task", launch)
    monkeypatch.setattr(generation, "check_can_afford", AsyncMock(return_value=True))
    monkeypatch.setattr(generation, "deduct_credits", debit)
    monkeypatch.setattr(generation, "credit_feed_prompt_repeat", AsyncMock())
    function = generation.quick_repeat_image_confirm if quick else generation.run_repeat_image_generation
    await function(callback, state)
    if revoke:
        debit.assert_not_awaited()
        launch.assert_not_awaited()
    else:
        debit.assert_awaited_once()
        launch.assert_awaited_once()
        params = launch.await_args.kwargs
        assert params["source_feed_gen_id"] == root_id
        assert params["parent_generation_id"] == child.id
        assert params["reference_images"] == [PRIVATE, OWN]
        assert params["private_repeat_reference_images"] == [PRIVATE]
    assert PRIVATE not in str(callback.answer.call_args_list)
    assert PRIVATE not in str(callback.message.answer.call_args_list)


@pytest.mark.asyncio
async def test_upload_and_seedream_failure_logs_hide_reference_urls(monkeypatch, caplog):
    upload = importlib.import_module("bot.services.kie_file_upload_service")
    seedream = importlib.import_module("bot.services.seedream_service")
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(upload, "resolve_local_upload_path", lambda _: None)
    monkeypatch.setattr(upload, "is_local_upload_source", lambda _: True)
    assert await upload.KieFileUploadService("synthetic").upload_local_image_source(PRIVATE) == ""
    monkeypatch.setattr(seedream, "image_sources_to_supported_image_urls", lambda refs: refs)
    monkeypatch.setattr(seedream.kie_file_upload_service, "upload_local_image_sources", AsyncMock(return_value=[""]))
    assert await seedream.seedream_service._prepare_effective_image_urls([PRIVATE]) is None
    assert PRIVATE not in caplog.text


@pytest.mark.parametrize("value", [
    PRIVATE, "/var/private/reference-secret.png", "data:image/png;base64,PRIVATE_MARKER",
])
def test_provider_error_cannot_disclose_private_media(value):
    text = make_user_friendly_generation_error(f"Unable to download input {value}")
    assert value not in text
    assert "скрытый ресурс" in text


@pytest.mark.asyncio
async def test_foreign_child_cannot_authorize_its_private_snapshot():
    _author, _viewer, root_id, child = await make_tasks()
    hidden, source_id = await generation._image_repeat_private_context(child, 123456789)
    assert hidden == []
    assert source_id == root_id


def test_provider_payload_redaction_preserves_diagnostics_and_input():
    from bot.services.kie_market_service import _safe_log_payload
    payload = {
        "model": "synthetic-model", "taskId": "task-visible", "code": 400,
        "input": {"prompt": "private recipe", "image_input": [PRIVATE], "image_urls": [PRIVATE], "ratio": "1:1"},
        "param": json.dumps({"input_urls": [PRIVATE]}),
        "message": f"Download failed: {PRIVATE}",
    }
    cleaned = _safe_log_payload(payload)
    assert cleaned["taskId"] == "task-visible"
    assert cleaned["code"] == 400
    assert cleaned["input"]["ratio"] == "1:1"
    assert PRIVATE not in json.dumps(cleaned)
    assert "private recipe" not in json.dumps(cleaned)
    assert payload["input"]["image_input"] == [PRIVATE]


@pytest.mark.asyncio
async def test_nano2_raw_provider_error_logs_preserve_status_without_media(monkeypatch, caplog):
    module = importlib.import_module("bot.services.nano_banana_2_service")

    class Response:
        status = 400

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def text(self):
            return json.dumps({"code": 400, "taskId": "diagnostic-task", "message": f"Cannot fetch {PRIVATE}"})

    service = module.ProviderClient("synthetic", "https://provider.example.test")
    monkeypatch.setattr(service, "_get_session", AsyncMock(
        return_value=SimpleNamespace(post=lambda *_, **__: Response())
    ))
    caplog.set_level(logging.INFO)
    assert await service._post("/create", {"image_input": [PRIVATE]}) is None
    assert PRIVATE not in caplog.text
    assert "diagnostic-task" in caplog.text
    assert "400" in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["reject", "fallback", "status"])
async def test_rendergrid_private_error_logs_keep_operational_metadata(monkeypatch, caplog, phase):
    module = importlib.import_module("bot.services.rendergrid_nano_banana_provider")
    provider = module.RenderGridNanoBananaProvider(
        api_key="synthetic", model_name="nano-banana-2",
        base_url="https://provider.example.test", max_retries=0,
    )
    status = 400 if phase == "reject" else 503
    failure = module.RenderGridProviderError(f"Cannot download {PRIVATE}", status=status, code="SYNTHETIC")
    caplog.set_level(logging.INFO)
    if phase == "status":
        monkeypatch.setattr(provider.client, "get_creation", AsyncMock(side_effect=failure))
        result = await provider.get_task_status("synthetic-status-task")
        assert result["status"] == "pending"
        assert "synthetic-status-task" in caplog.text
    else:
        monkeypatch.setattr(provider, "_create_rendergrid_generation", AsyncMock(side_effect=failure))
        await provider.generate_image("Synthetic recipe", "1:1", "2K", [PRIVATE], "png")
        assert str(status) in caplog.text
        assert "SYNTHETIC" in caplog.text
    assert PRIVATE not in caplog.text
    assert "nano-banana-2" in caplog.text
    await provider.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["body", "response", "exception"])
async def test_gemini_private_error_logs_are_sanitized(monkeypatch, caplog, mode):
    module = importlib.import_module("bot.services.gemini_service")

    class Response:
        status = 200 if mode == "response" else 503

        async def __aenter__(self):
            if mode == "exception":
                raise RuntimeError(f"Failed to read {PRIVATE}")
            return self

        async def __aexit__(self, *_):
            return None

        async def text(self):
            return json.dumps({"code": "SYNTHETIC", "message": f"Could not read {PRIVATE}"})

        async def json(self):
            return {"code": "SYNTHETIC", "reference_images": [PRIVATE]}

    service = module.GeminiService("", nanobanana_key="synthetic")
    monkeypatch.setattr(service, "_get_session", AsyncMock(
        return_value=SimpleNamespace(post=lambda *_, **__: Response())
    ))
    caplog.set_level(logging.INFO)
    result = await service._generate_via_nanobanana(
        "Synthetic recipe", reference_image_urls=[PRIVATE]
    )
    assert result is None
    assert PRIVATE not in caplog.text
    assert ("RuntimeError" if mode == "exception" else "SYNTHETIC") in caplog.text


@pytest.mark.asyncio
async def test_grok_logs_prompt_length_without_private_prompt_prefix(monkeypatch, caplog):
    module = importlib.import_module("bot.services.grok_service")
    monkeypatch.setattr(module, "image_sources_to_provider_safe_png_urls", lambda refs: refs)
    monkeypatch.setattr(module.kie_file_upload_service, "upload_local_image_sources", AsyncMock(return_value=[PRIVATE]))
    provider = module.GrokService(kie_key="synthetic")
    launch = AsyncMock(return_value={"task_id": "synthetic-grok"})
    monkeypatch.setattr(provider, "_kie_post", launch)
    caplog.set_level(logging.INFO)
    result = await provider.generate_image_to_image([PRIVATE], prompt=f"Private source {PRIVATE}")
    assert result["task_id"] == "synthetic-grok"
    assert PRIVATE not in caplog.text
    assert "prompt_len=" in caplog.text
    assert PRIVATE in launch.await_args.args[1]["input"]["prompt"]


@pytest.mark.asyncio
async def test_profile_only_source_retains_private_grants_and_hides_prompt():
    author, viewer, root_id, _child = await make_tasks()
    await update_root(root_id, "is_public_feed = 0, is_profile_visible = 1")
    root = await database.get_task_by_id("private-runtime-root")
    assert root.is_profile_visible is True
    hidden, source_id = await generation._image_repeat_private_context(root, viewer.id)
    assert hidden == [PRIVATE]
    assert source_id == root_id
    assert generation._repeat_source_prompt_hidden(root, viewer.id) is True
    assert generation._repeat_source_prompt_hidden(root, author.id) is False
    state = FakeState()
    restored, error = await generation._restore_image_task_to_state(
        root, state, include_references=False, repeat_source_task_id=root.task_id,
        hide_prompt=generation._repeat_source_prompt_hidden(root, viewer.id),
    )
    assert restored and error is None
    assert state.data["repeat_prompt_hidden"] is True
    assert PRIVATE not in json.dumps(state.data)


@pytest.mark.asyncio
async def test_grok_partial_reference_upload_cannot_submit_changed_recipe(monkeypatch, caplog):
    module = importlib.import_module("bot.services.grok_service")
    monkeypatch.setattr(module, "image_sources_to_provider_safe_png_urls", lambda refs: refs)
    monkeypatch.setattr(module.kie_file_upload_service, "upload_local_image_sources", AsyncMock(return_value=[OWN, ""]))
    service = module.GrokService(kie_key="synthetic")
    provider = AsyncMock()
    monkeypatch.setattr(service, "_kie_post", provider)
    result = await service.generate_image_to_image([OWN, PRIVATE], prompt="Image1 person Image2 outfit")
    assert result is None
    provider.assert_not_awaited()
    assert PRIVATE not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["missing", "empty", "invalid_data"])
async def test_banana_pro_gemini_partial_reference_failure_aborts(monkeypatch, caplog, failure):
    module = importlib.import_module("bot.services.nano_banana_pro_service")

    class ImageResponse:
        content_type = "image/png"

        def __init__(self, url):
            self.url = url
            self.status = 404 if failure == "missing" and url == PRIVATE else 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return None

        async def read(self):
            return b"" if failure == "empty" and self.url == PRIVATE else b"synthetic-image"

    post = MagicMock()
    service = module.NanoBananaProGeminiProvider("synthetic", "https://provider.example.test")
    monkeypatch.setattr(service, "_get_session", AsyncMock(return_value=SimpleNamespace(
        get=lambda url: ImageResponse(url), post=post,
    )))
    second = "data:image/png;base64,invalid-private-data!" if failure == "invalid_data" else PRIVATE
    result = await service.generate_image("Image1 person Image2 outfit", image_input=[OWN, second])
    assert result is None
    post.assert_not_called()
    assert PRIVATE not in caplog.text
    assert second not in caplog.text


@pytest.mark.asyncio
async def test_banana2_missing_secondary_reference_aborts(monkeypatch, caplog):
    module = importlib.import_module("bot.services.nano_banana_2_service")
    service = module.NanoBanana2GeminiProvider("synthetic", "https://provider.example.test")
    post = MagicMock()
    monkeypatch.setattr(service, "_get_session", AsyncMock(return_value=SimpleNamespace(post=post)))
    monkeypatch.setattr(service, "_reference_part", AsyncMock(side_effect=[
        {"inlineData": {"mimeType": "image/png", "data": "c3ludGhldGlj"}}, None,
    ]))
    result = await service.generate_image("Image1 person Image2 outfit", image_input=[OWN, PRIVATE])
    assert result["retryable"] is True
    assert "required reference" in result["error"]
    post.assert_not_called()
    assert PRIVATE not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("model", ["pro", "2"])
async def test_kie_partial_reference_normalization_aborts(monkeypatch, model):
    module = importlib.import_module(f"bot.services.nano_banana_{model}_service")
    cls = module.NanoBananaProService if model == "pro" else module.NanoBanana2Service
    provider = SimpleNamespace(_post=AsyncMock())
    service = cls(provider)
    monkeypatch.setattr(module.kie_file_upload_service, "upload_local_image_sources", AsyncMock(return_value=[OWN, ""]))
    monkeypatch.setattr(module, "image_sources_to_supported_image_urls", lambda refs: [ref for ref in refs if ref])
    assert await service.create_task("Image1 person Image2 outfit", image_input=[OWN, PRIVATE]) is None
    provider._post.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("single", [False, True])
async def test_gemini_url_inputs_cannot_disappear_in_native_fallback(monkeypatch, single):
    module = importlib.import_module("bot.services.gemini_service")
    service = module.GeminiService("synthetic-native", nanobanana_key="synthetic-url")
    service._client = SimpleNamespace()
    monkeypatch.setattr(service, "_generate_via_nanobanana", AsyncMock(return_value=None))
    native = AsyncMock(return_value=b"unexpected-text-only-image")
    monkeypatch.setattr(service, "_generate_via_native_gemini", native)
    arguments = {"image_input_url": PRIVATE} if single else {"reference_image_urls": [OWN, PRIVATE]}
    assert await service.generate_image("Synthetic recipe", **arguments) is None
    native.assert_not_awaited()


@pytest.mark.asyncio
async def test_gemini_byte_inputs_keep_compatible_native_fallback(monkeypatch):
    module = importlib.import_module("bot.services.gemini_service")
    service = module.GeminiService("synthetic-native", nanobanana_key="synthetic-url")
    service._client = SimpleNamespace()
    monkeypatch.setattr(service, "_generate_via_nanobanana", AsyncMock(return_value=None))
    native = AsyncMock(return_value=b"complete-reference-image")
    monkeypatch.setattr(service, "_generate_via_native_gemini", native)
    result = await service.generate_image("Synthetic recipe", reference_images=[b"synthetic-reference"])
    assert result == b"complete-reference-image"
    assert native.await_args.kwargs["reference_images"] == [b"synthetic-reference"]
