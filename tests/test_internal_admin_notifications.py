import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiohttp.test_utils import make_mocked_request

from bot.handlers import repeat_result_compat
from bot.internal_admin_dispatch import _AuthenticatedBody
from bot.internal_admin_notifications import (
    _segment_query,
    _validate_message,
    _validate_segment,
    campaign_preview_handler,
)
from bot.internal_admin_user_commands import CommandValidationError


def test_repeat_result_compat_restores_safe_repeat_flow(monkeypatch) -> None:
    callback = SimpleNamespace(
        data="repeat_result_42",
        from_user=SimpleNamespace(id=9001),
        answer=AsyncMock(),
    )
    state = AsyncMock()
    task = SimpleNamespace(
        id=42,
        user_id=7,
        is_public_feed=False,
        feed_references_visible=False,
    )
    monkeypatch.setattr(repeat_result_compat, "get_task_by_id", AsyncMock(return_value=task))
    monkeypatch.setattr(
        repeat_result_compat,
        "get_or_create_user",
        AsyncMock(return_value=SimpleNamespace(id=7)),
    )
    restore = AsyncMock(return_value=(True, None))
    show = AsyncMock()
    monkeypatch.setattr(repeat_result_compat, "_restore_image_task_to_state", restore)
    monkeypatch.setattr(repeat_result_compat, "_show_repeat_image_screen", show)

    pytest.run = None

    async def execute() -> None:
        await repeat_result_compat.repeat_result_compat(callback, state)

    import asyncio

    asyncio.run(execute())

    restore.assert_awaited_once_with(
        task,
        state,
        include_references=True,
        repeat_source_task_id="42",
        hide_prompt=False,
    )
    show.assert_awaited_once_with(callback, state)
    callback.answer.assert_awaited_once()


def test_notification_segments_are_strictly_validated() -> None:
    assert _validate_segment({"type": "recent", "days": 14}) == {
        "type": "recent",
        "days": 14,
    }
    assert _validate_segment({"type": "balance_gte", "amount": 10}) == {
        "type": "balance_gte",
        "amount": 10,
    }
    assert _validate_segment(
        {"type": "explicit", "telegram_ids": [123, "123", 456]}
    ) == {"type": "explicit", "telegram_ids": [123, 456]}

    with pytest.raises(CommandValidationError, match="unsupported segment"):
        _validate_segment({"type": "sql", "where": "TRUE"})
    with pytest.raises(CommandValidationError, match="at most 1000"):
        _validate_segment({"type": "explicit", "telegram_ids": list(range(1, 1002))})


def test_explicit_segment_uses_placeholders_not_values() -> None:
    sql, parameters = _segment_query(
        {"type": "explicit", "telegram_ids": [111, 222]},
        count_only=False,
    )

    assert "u.telegram_id IN (?,?)" in sql
    assert "111" not in sql
    assert parameters == (111, 222)


def test_notification_message_rejects_unsafe_button_url() -> None:
    with pytest.raises(CommandValidationError, match="https:// or tg://"):
        _validate_message(
            {
                "text": "Hello",
                "button_label": "Open",
                "button_url": "javascript:alert(1)",
            }
        )

    assert _validate_message(
        {
            "text": "Hello",
            "button_label": "Open",
            "button_url": "https://example.com/path",
        }
    )["button_url"] == "https://example.com/path"


@pytest.mark.asyncio
async def test_campaign_preview_returns_count(monkeypatch) -> None:
    request = make_mocked_request("POST", "/internal/admin/notifications/preview")
    request["internal_body"] = _AuthenticatedBody(
        json.dumps({"segment": {"type": "paid"}}).encode()
    )
    monkeypatch.setattr(
        "bot.internal_admin_notifications._audience_count",
        AsyncMock(return_value=17),
    )

    response = await campaign_preview_handler.__wrapped__(request)
    payload = json.loads(response.text)

    assert response.status == 200
    assert payload["data"] == {
        "segment": {"type": "paid"},
        "audience_count": 17,
    }
