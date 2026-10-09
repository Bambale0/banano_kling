"""Direct edit must use the original video, not a generated frame pipeline."""
from unittest.mock import AsyncMock

import pytest

from bot.services.seedance_25_service import Seedance25Service


@pytest.fixture(autouse=True)
def isolated_database():
    # These provider-boundary tests do not touch a database or real providers.
    yield


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [1, 2, 3])
async def test_direct_edit_preserves_complete_user_prompt_and_inputs(count):
    service = Seedance25Service(kie_key="test-key")
    service._kie_post = AsyncMock(return_value={"task_id": "direct-edit-test"})
    prompt = "Video edit: replace the person in @Video1 with the person in @Image1. Keep the dress."
    images = [f"https://example.test/person-{n}.png" for n in range(count)]
    videos = ["https://example.test/source.mov"]
    result = await service.generate_video(
        prompt, identity_transfer=True, duration=15, aspect_ratio="9:16",
        reference_image_urls=images, reference_video_urls=videos,
    )
    assert result["success"] is True
    service._kie_post.assert_awaited_once()
    outgoing = service._kie_post.call_args.args[1]["input"]
    assert outgoing["prompt"] == prompt
    assert outgoing["reference_image_urls"] == images
    assert outgoing["reference_video_urls"] == videos
    assert outgoing["omni_reference_task_type"] == "edit"
    assert (outgoing["duration"], outgoing["aspect_ratio"]) == (-1, "adaptive")
    assert not {"first_frame_url", "last_frame_url", "reference_audio_urls"} & outgoing.keys()


@pytest.mark.asyncio
async def test_empty_instruction_uses_concise_direct_edit_default(monkeypatch):
    from bot import database
    monkeypatch.setattr(database, "get_bot_setting", AsyncMock(return_value=""))
    service = Seedance25Service(kie_key="test-key")
    service._kie_post = AsyncMock(return_value={"task_id": "direct-default-test"})
    result = await service.generate_video(
        "", identity_transfer=True,
        reference_image_urls=["https://example.test/person.png"],
        reference_video_urls=["https://example.test/source.mov"],
    )
    assert result["success"] is True
    outgoing = service._kie_post.call_args.args[1]["input"]
    assert outgoing["prompt"].startswith("Video edit:")
    assert "replace" in outgoing["prompt"]
    assert "@Image1" in outgoing["prompt"] and "@Video1" in outgoing["prompt"]
    assert "sole authoritative" not in outgoing["prompt"]
    assert "Additional user instruction" not in outgoing["prompt"]
    assert outgoing["omni_reference_task_type"] == "edit"


@pytest.mark.asyncio
async def test_ordinary_generation_has_no_edit_field_or_prompt_changes():
    service = Seedance25Service(kie_key="test-key")
    service._kie_post = AsyncMock(return_value={"task_id": "ordinary-test"})
    prompt = "Use @Image1 and @Video1 as creative references."
    await service.generate_video(prompt, duration=6, aspect_ratio="9:16",
        reference_image_urls=["https://example.test/person.png"],
        reference_video_urls=["https://example.test/source.mov"])
    outgoing = service._kie_post.call_args.args[1]["input"]
    assert outgoing["prompt"] == prompt
    assert "omni_reference_task_type" not in outgoing
    assert (outgoing["duration"], outgoing["aspect_ratio"]) == (6, "9:16")


@pytest.mark.parametrize("count", [1, 2, 3])
def test_short_legacy_wishes_keep_explicit_edit_and_every_reference(count):
    from bot.services.seedance25_identity import build_identity_transfer_prompt
    prompt = build_identity_transfer_prompt("Keep the dress", image_count=count)
    assert prompt.startswith("Video edit:") and prompt.endswith("Keep the dress")
    assert "@Video1" in prompt
    for index in range(1, count + 1):
        assert f"@Image{index}" in prompt
    assert "sole authoritative" not in prompt


@pytest.mark.parametrize("text", [
    "", "no reference roles", "@Video1 {identity_images.__class__}",
    "@Video1 {identity_images!r}", "@Video1 {identity_images:>10}",
    "@Video1 {unknown}", "@Video1 {{identity_images}}", "@Video1 {",
    "@Video2 {identity_images}", "@Video1abc {identity_images}", "@Video1 @Audio1 {identity_images}",
    "@Video1 @Image2 {identity_images}", "@Video1 {identity_images}" + "x" * 8000,
])
def test_invalid_admin_template_is_rejected(text):
    from bot.services.seedance25_identity import validate_identity_template
    with pytest.raises(ValueError):
        validate_identity_template(text)


@pytest.mark.asyncio
async def test_default_template_is_runtime_editable_and_custom_prompt_bypasses_it(monkeypatch):
    from bot import database
    from bot.services.seedance25_identity import resolve_identity_transfer_prompt
    template = "Video edit: replace the person in @Video1 using {identity_images}. Preserve the jacket."
    getter = AsyncMock(return_value=template)
    monkeypatch.setattr(database, "get_bot_setting", getter)
    result = await resolve_identity_transfer_prompt("", image_count=2)
    assert result == template.replace("{identity_images}", "@Image1, @Image2")
    getter.assert_awaited_once()
    full = "Replace the person in @Video1 with @Image1, preserving the coat."
    assert await resolve_identity_transfer_prompt(full, image_count=1) == full
    getter.assert_awaited_once()


@pytest.mark.asyncio
async def test_template_updates_and_reset_are_audited(monkeypatch):
    from bot import database
    from bot.services.seedance25_identity import (
        IDENTITY_TEMPLATE_SETTING,
        reset_identity_edit_template,
        save_identity_edit_template,
    )
    setter = AsyncMock(return_value=True)
    monkeypatch.setattr(database, "set_bot_setting", setter)
    template = "Video edit: replace the person in @Video1 with {identity_images}."
    await save_identity_edit_template(template, admin_id=123)
    setter.assert_awaited_once_with(IDENTITY_TEMPLATE_SETTING, template, updated_by_telegram_id=123)
    await reset_identity_edit_template(admin_id=123)
    assert setter.await_count == 2
    setter.assert_awaited_with(IDENTITY_TEMPLATE_SETTING, "", updated_by_telegram_id=123)
    with pytest.raises(ValueError):
        await save_identity_edit_template("broken", admin_id=123)
    assert setter.await_count == 2


@pytest.mark.asyncio
async def test_non_admin_cannot_update_template(monkeypatch):
    from types import SimpleNamespace

    from bot.handlers import admin
    from bot.services import seedance25_identity
    monkeypatch.setattr(admin, "is_admin", lambda _: False)
    save = AsyncMock()
    monkeypatch.setattr(seedance25_identity, "save_identity_edit_template", save)
    message = SimpleNamespace(from_user=SimpleNamespace(id=123),
        text="/seedance25_edit_prompt set ignored", answer=AsyncMock())
    await admin.cmd_seedance25_edit_prompt(message)
    save.assert_not_awaited()
    message.answer.assert_awaited_once()


@pytest.mark.parametrize("count", [1, 2, 3])
def test_complete_unicode_prompt_uses_kie_limit_without_hidden_expansion(count):
    from bot.services.seedance25_identity import (
        SEEDANCE_25_PROMPT_MAX_CHARS,
        build_identity_transfer_prompt,
    )
    prefix = "Video edit: replace @Video1 with @Image1. "
    valid = prefix + "\U0001f642" * (SEEDANCE_25_PROMPT_MAX_CHARS - len(prefix))
    assert build_identity_transfer_prompt(valid, image_count=count) == valid
    with pytest.raises(ValueError):
        build_identity_transfer_prompt(valid + "x", image_count=count)
