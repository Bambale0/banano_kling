"""Gemini photo instructions at public service and admin boundaries."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from bot import database
from bot.config import config
from bot.services.photo_prompt_service import PhotoPromptService
from bot.services.prompt_analyzer_v2_service import PromptAnalyzerV2Service


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch):
    monkeypatch.setattr(database, "_BOT_SETTING_CACHE", {})


@pytest.mark.asyncio
@pytest.mark.parametrize("surface", ["photo", "v2"])
async def test_saved_gemini_guidance_reaches_both_photo_surfaces(
    surface, monkeypatch, caplog
):
    caplog.set_level("INFO")
    guidance = "Preserve the visible illustration style and exact object arrangement."
    await database.set_bot_setting("gemini_photo_instructions", guidance)
    captured = {}

    async def provider(request):
        captured.update(await request.json())
        return web.json_response(
            {
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "prompt_ru": "Синий круг слева.",
                                    "prompt_en": "A blue circle on the left.",
                                }
                            )
                        }
                    }
                ]
            }
        )

    app = web.Application()
    app.router.add_post("/gemini-3.1-pro/v1/chat/completions", provider)
    async with TestServer(app) as server:
        monkeypatch.setattr(
            config, "KIE_BASE_URL", str(server.make_url("")).rstrip("/")
        )
        if surface == "photo":
            result = await PhotoPromptService(api_key="test").analyze_photo(
                image_url="https://example.test/reference.png",
                user_note="Change only the background to pink.",
            )
        else:
            result = await PromptAnalyzerV2Service(api_key="test").analyze_prompt(
                image_url="https://example.test/reference.png",
                text="Change only the background to pink.",
            )

    instructions = captured["messages"][0]["content"]
    assert guidance in instructions
    assert '"prompt_ru"' in instructions and '"prompt_en"' in instructions
    assert ('"negative_prompt"' in instructions) == (surface == "photo")
    assert (
        "Change only the background to pink."
        in captured["messages"][1]["content"][0]["text"]
    )
    assert (
        captured["messages"][1]["content"][1]["image_url"]["url"]
        == "https://example.test/reference.png"
    )
    assert result["prompt_ru"] == "Синий круг слева."
    events = {
        getattr(record, "analysis_event", ""): record for record in caplog.records
    }
    selected = events["instructions_selected"]
    completed = events["operation_success"]
    assert selected.request_id == completed.request_id
    assert selected.analysis_instruction_revision
    assert (
        selected.analysis_instruction_revision
        == completed.analysis_instruction_revision
    )
    assert guidance not in caplog.text


@pytest.mark.asyncio
async def test_admin_can_edit_view_and_reset_gemini_photo_guidance(monkeypatch):
    from bot.handlers import admin
    from bot.services.gemini_photo_instructions import get_photo_instructions

    monkeypatch.setattr(admin, "is_admin", lambda value: value == 700001)
    original = await get_photo_instructions()
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=700001),
        text="/gemini_photo_prompt set",
        reply_to_message=SimpleNamespace(
            text="Keep exact visible object counts and no invented details."
        ),
        answer=AsyncMock(),
        answer_document=AsyncMock(),
    )
    await admin.cmd_gemini_photo_prompt(message)
    assert await get_photo_instructions() == message.reply_to_message.text
    async with database.db_backend.connect(database.DATABASE_PATH) as conn:
        cur = await conn.execute(
            "SELECT updated_by_telegram_id FROM bot_settings WHERE key=?",
            ("gemini_photo_instructions",),
        )
        assert (await cur.fetchone())[0] == 700001
    message.text = "/gemini_photo_prompt"
    await admin.cmd_gemini_photo_prompt(message)
    document = message.answer_document.call_args.kwargs["document"]
    assert document.data.decode() == message.reply_to_message.text
    message.text = "/gemini_photo_prompt reset"
    await admin.cmd_gemini_photo_prompt(message)
    assert await get_photo_instructions() == original


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "user_id,text,reply",
    [
        (700002, "/gemini_photo_prompt set stolen", None),
        (700001, "/gemini_photo_prompt set", None),
        (700001, "/gemini_photo_prompt set " + "x" * 8001, None),
        (700001, "/gemini_photo_prompt reset typo", None),
    ],
    ids=["unauthorized", "empty", "oversized", "bad-reset"],
)
async def test_invalid_or_unauthorized_guidance_edit_preserves_setting(
    monkeypatch, user_id, text, reply
):
    from bot.handlers import admin
    from bot.services.gemini_photo_instructions import get_photo_instructions

    monkeypatch.setattr(admin, "is_admin", lambda value: value == 700001)
    await database.set_bot_setting(
        "gemini_photo_instructions", "Keep this approved instruction."
    )
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=user_id),
        text=text,
        reply_to_message=reply,
        answer=AsyncMock(),
        answer_document=AsyncMock(),
    )
    await admin.cmd_gemini_photo_prompt(message)
    assert await get_photo_instructions() == "Keep this approved instruction."
    message.answer_document.assert_not_called()


@pytest.mark.asyncio
async def test_admin_inline_edit_applies_without_restart(monkeypatch):
    from bot.handlers import admin
    from bot.services.gemini_photo_instructions import get_photo_instructions

    monkeypatch.setattr(admin, "is_admin", lambda value: value == 700001)
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=700001),
        text="/gemini_photo_prompt set Preserve the original medium.",
        reply_to_message=None,
        answer=AsyncMock(),
    )
    await admin.cmd_gemini_photo_prompt(message)
    assert await get_photo_instructions() == "Preserve the original medium."


@pytest.mark.asyncio
async def test_non_admin_cannot_download_instructions(monkeypatch):
    from bot.handlers import admin

    monkeypatch.setattr(admin, "is_admin", lambda value: False)
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=700002),
        text="/gemini_photo_prompt",
        answer=AsyncMock(),
        answer_document=AsyncMock(),
    )
    await admin.cmd_gemini_photo_prompt(message)
    message.answer_document.assert_not_called()
