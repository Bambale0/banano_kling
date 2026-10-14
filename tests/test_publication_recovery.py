"""Owned repeat/trend outputs can be published without redistributing private recipes."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from bot import database
from bot import db as db_backend
from bot.services import feed_persist


def scope_module():
    path = Path(__file__).resolve().parents[1] / "bot/handlers/publication_scope_compat.py"
    spec = importlib.util.spec_from_file_location("recovery_publication_scope", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,model,result", [
    ("image", "banana_pro", "https://example.test/derived.png"),
    ("video", "seedance_2_5", "https://example.test/derived.mp4"),
])
async def test_owner_can_publish_edit_and_unpublish_derived_result_safely(
    tmp_path, monkeypatch, kind, model, result,
):
    if db_backend.is_postgres():
        pytest.skip("SQLite publication lifecycle integration")

    scope = scope_module()
    monkeypatch.setattr(database, "DATABASE_PATH", str(tmp_path / "publication.db"))
    scope._SCHEMA_READY_PATHS.clear()

    async def persist_identity(urls, **_kw):
        return list(urls)
    monkeypatch.setattr(feed_persist, "persist_feed_result_urls", persist_identity)

    await database.init_db()
    source_author = await database.get_or_create_user(811000001)
    derivative_author = await database.get_or_create_user(811000002)
    secret = "https://example.test/source-private-reference.png"

    assert await database.add_generation_task(
        source_author.id, source_author.telegram_id, "source-gen", kind,
        model, model=model, prompt="SOURCE_AUTHOR_SECRET_PROMPT",
        request_data={"reference_images": [secret]},
    )
    await database.complete_video_task(
        "source-gen", "https://example.test/source.png" if kind == "image"
        else "https://example.test/source.mp4",
    )
    source_card = await database.share_to_feed("source-gen", source_author.id)
    assert source_card is not None

    assert await database.add_generation_task(
        derivative_author.id, derivative_author.telegram_id, "own-derived", kind,
        model, model=model, prompt="SOURCE_AUTHOR_SECRET_PROMPT",
        source_feed_gen_id=source_card["id"], action_type="remix",
        request_data={
            "reference_images": [secret],
            "v_reference_videos": ["https://example.test/source-private-video.mp4"],
            "private_recipe": True,
        },
    )
    await database.complete_video_task("own-derived", result)

    # An attacker may send reference toggles from an old or modified client.
    options = {
        "prompt_visible": True,
        "references_visible": True,
        "reference_image_indices": [0],
        "reference_video_indices": [0],
        "repeat_reference_image_indices": [0],
        "repeat_reference_video_indices": [0] if kind == "video" else [],
        "blurred": False,
    }
    card = await scope.share_to_feed_scoped("own-derived", derivative_author.id, **options)
    assert card is not None
    assert card["task_id"] == "own-derived"
    assert card["is_public_feed"] is True
    assert card["is_mine"] is True
    assert card["prompt"] == ""
    assert card["prompt_hidden"] is True
    assert card["reference_images"] == []
    assert card["reference_videos"] == []

    generation = await database.get_generation_task_payload("own-derived", user_id=derivative_author.id)
    assert not generation["feed_prompt_visible"]
    assert not generation["feed_references_visible"]
    assert generation["feed_reference_selection"] is not None
    assert json.loads(generation["feed_reference_selection"]) == {"images": [], "videos": []}

    from bot import miniapp
    from bot.trend_task_privacy import sanitize_task_api_payload

    monkeypatch.setattr(miniapp, "DATABASE_PATH", database.DATABASE_PATH)
    task = await miniapp._fetch_task_detail(derivative_author.telegram_id, "own-derived")
    assert task is not None
    clean = (await sanitize_task_api_payload({"task": task}))["task"]
    assert clean["is_public_feed"] is True
    assert clean["publication_scope"] == "feed"
    assert clean["prompt_hidden"] is True
    assert clean["prompt"] == ""
    assert clean.get("publication_reference_images") is None
    assert secret not in json.dumps(clean, ensure_ascii=False)

    # Editing preserves the same public identifier rather than creating a post.
    profile = await scope.share_to_profile(
        "own-derived", derivative_author.id,
        prompt_visible=True, references_visible=True,
        reference_image_indices=[0],
        blurred=True,
    )
    assert profile is not None
    assert profile["id"] == card["id"]
    assert profile["publication_scope"] == "profile"
    assert profile["feed_blurred"] is True
    assert profile["reference_images"] == []
    assert profile["prompt"] == ""

    again = await scope.share_to_feed_scoped(
        "own-derived", derivative_author.id,
        prompt_visible=True, references_visible=True,
        blurred=True,
    )
    assert again is not None
    assert again["id"] == card["id"]
    assert again["publication_scope"] == "feed"
    assert again["prompt_hidden"] is True
    assert again["reference_images"] == []

    assert await scope.share_to_feed_scoped("own-derived", source_author.id) is None
    assert await scope.remove_publication("own-derived", derivative_author.id) is True
    assert await scope.get_publication_scope("own-derived", derivative_author.id) == "private"

    revived = await scope.share_to_feed_scoped("own-derived", derivative_author.id)
    assert revived is not None and revived["id"] == card["id"]
    assert revived["prompt_hidden"] is True


def test_private_repeat_telegram_confirmation_never_offers_source_disclosure():
    scope = scope_module()
    message, markup = scope._feed_confirmation_components("own-derived", private_recipe=True)
    assert "Исходный промпт и референсы" in message
    buttons = [button for row in markup.inline_keyboard for button in row]
    assert "Prompt" not in " ".join(button.text for button in buttons)
    assert "Референсы" not in " ".join(button.text for button in buttons)
    assert any(button.callback_data == "feedpubok_own-derived_0_0_0" for button in buttons)
    assert any(button.callback_data == "pubblur_1_own-derived" for button in buttons)

    edited, markup = scope._feed_confirmation_components(
        "own-derived", private_recipe=True, blurred=True,
    )
    assert "включён" in edited
    assert any(
        button.callback_data == "feedpubok_own-derived_0_0_1"
        for row in markup.inline_keyboard for button in row
    )


def test_published_keyboard_reopens_editor_and_receipt_opens_own_task():
    from bot.handlers.generation import _published_feed_link_keyboard

    scope = scope_module()
    source_markup = scope._replace_publication_button(
        scope.get_video_result_keyboard_scoped(
            "https://example.test/own-derived.mp4", task_id="own-derived",
        ),
        "own-derived", scope="feed",
    )
    controls = [b for row in source_markup.inline_keyboard for b in row]
    assert any(b.text == "⚙️ Настроить публикацию" for b in controls)

    receipt = _published_feed_link_keyboard(
        "https://t.me/testbot?startapp=feed_55",
        "https://t.me/testbot?start=feed_55",
        task_id="own-derived", bot_username="testbot",
    )
    buttons = [b for row in receipt.inline_keyboard for b in row]
    assert any(
        b.text == "⚙️ Настроить публикацию в Студии"
        and b.url == "https://t.me/testbot?startapp=task_own-derived"
        for b in buttons
    )
