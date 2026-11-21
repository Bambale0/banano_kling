"""Regression tests: Telegram image-document fallback keeps result actions."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot import database, keyboards, main


def _action_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Повторить", callback_data="repeat_result_123")],
            [InlineKeyboardButton(text="Оживить", callback_data="grokvid_123")],
            [InlineKeyboardButton(text="Опубликовать", callback_data="pubscope_123")],
        ]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("with_bytes", [True, False])
async def test_original_image_document_retains_actions(with_bytes):
    bot = SimpleNamespace(send_document=AsyncMock())
    markup = _action_markup()

    delivered = await main._send_original_file(
        bot,
        123,
        "https://example.test/uploads/result.jpg",
        b"example image bytes" if with_bytes else None,
        reply_markup=markup,
    )

    assert delivered
    sent = bot.send_document.await_args.kwargs
    assert sent["chat_id"] == 123
    assert sent["reply_markup"] is markup
    if with_bytes:
        assert sent["document"].filename == "result.jpg"
    else:
        assert sent["document"] == "https://example.test/uploads/result.jpg"


@pytest.mark.asyncio
@pytest.mark.parametrize("preview_delivered", [False, True])
async def test_polled_image_result_preserves_actions_if_only_document_delivers(
    monkeypatch, preview_delivered
):
    markup = _action_markup()
    original = AsyncMock(return_value=True)
    complete = AsyncMock()
    mark_delivered = AsyncMock()
    monkeypatch.setattr(main, "_send_original_file", original)
    monkeypatch.setattr(
        main, "_persist_result_url_if_needed",
        AsyncMock(return_value="https://example.test/uploads/result.jpg"),
    )
    monkeypatch.setattr(main, "_resolve_task_telegram_id", AsyncMock(return_value=123))
    monkeypatch.setattr(main, "_download_remote_bytes", AsyncMock(return_value=b"image-bytes"))
    monkeypatch.setattr(main, "_build_preview_photo_bytes", lambda *_args: b"preview-bytes")
    monkeypatch.setattr(main, "_extract_task_request_data", lambda *_args: {})
    monkeypatch.setattr(main, "_extract_reference_image_urls", lambda *_args: [])
    monkeypatch.setattr(main, "_build_single_result_caption", lambda caption, *_args: caption)
    monkeypatch.setattr(main, "_should_send_prompt_followup", lambda *_args: False)
    monkeypatch.setattr(main, "_finish_result_with_unavailable_telegram", AsyncMock(return_value=False))
    monkeypatch.setattr(keyboards, "get_image_result_keyboard", lambda *_args, **_kwargs: markup)

    monkeypatch.setattr(database, "store_task_result_ready", AsyncMock(return_value=True))
    monkeypatch.setattr(database, "can_attempt_telegram_delivery", AsyncMock(return_value=True))
    monkeypatch.setattr(database, "claim_task_delivery", AsyncMock(return_value=True))
    monkeypatch.setattr(database, "complete_video_task", complete)
    monkeypatch.setattr(database, "mark_task_delivery_status", mark_delivered)

    bot = SimpleNamespace(
        send_photo=AsyncMock(
            side_effect=None if preview_delivered else ValueError("IMAGE_PROCESS_FAILED")
        ),
        get_chat=AsyncMock(),
    )
    task = SimpleNamespace(
        id=123,
        task_id="provider-123",
        telegram_id=123,
        type="image",
        model="banana_pro",
        aspect_ratio="1:1",
        cost=2,
    )

    delivered = await main._send_polled_nexus_image_result(
        bot, task, "https://example.test/uploads/result.jpg"
    )

    assert delivered is True
    original.assert_awaited_once()
    assert original.await_args.kwargs["reply_markup"] is (
        None if preview_delivered else markup
    )
    complete.assert_awaited_once()
    mark_delivered.assert_awaited_once()


def test_both_image_delivery_paths_attach_actions_on_document_only_fallback():
    """Every document fallback is wired to the matching photo result keyboard."""
    import ast
    from pathlib import Path

    source = Path(main.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_send_original_file"
    ]
    assert len(calls) == 2  # Poller and provider-webhook paths
    for call in calls:
        markup = next((kw.value for kw in call.keywords if kw.arg == "reply_markup"), None)
        assert isinstance(markup, ast.IfExp)
        assert isinstance(markup.test, ast.UnaryOp)
        assert isinstance(markup.test.op, ast.Not)
        assert isinstance(markup.test.operand, ast.Name)
        assert markup.test.operand.id == "preview_sent"
        assert isinstance(markup.orelse, ast.Constant)
        assert markup.orelse.value is None
