"""VK video UI readiness is owned by the signed VK actor, never linked TG money."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiohttp.test_utils import make_mocked_request

from bot.shared_accounts import api
from bot.shared_accounts.actor import PlatformActor


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "video_flag,linked,registered,blocked,expected",
    [
        ("0", False, True, False, False),
        ("1", False, True, False, True),
        ("1", True, True, False, False),
        ("1", False, False, False, False),
        ("1", False, True, True, False),
    ],
)
async def test_vk_video_button_gate_requires_native_owner_and_explicit_flag(
    monkeypatch, video_flag, linked, registered, blocked, expected,
):
    actor = PlatformActor(
        platform="vk", external_id=2001, shared_account_id="a" * 32,
        linked_platforms=("vk", "telegram") if linked else ("vk",),
        linked_telegram_id=987 if linked else None,
    )
    monkeypatch.setenv("VK_MINIAPP_VIDEO_WRITES_ENABLED", video_flag)
    monkeypatch.setattr(api, "load_policy", AsyncMock(return_value=SimpleNamespace(enabled=True)))
    monkeypatch.setattr(api, "resolve_platform_actor", AsyncMock(return_value=actor))
    native = AsyncMock(return_value={
        "registered": registered, "is_blocked": blocked, "balance": 5, "tasks": [],
    })
    monkeypatch.setattr(api, "fetch_native_vk_state", native)
    request = make_mocked_request(
        "GET", "/mini-app/api/account-preview/vk-native-state",
        headers={"Authorization": "Bearer test-session"},
    )
    result = await api.vk_native_state(request)
    assert result.status == 200
    body = json.loads(result.text)
    assert body["video_generation_enabled"] is expected
    assert body["recent_tasks"] == []
    native.assert_awaited_once_with(2001)
    assert "telegram_id" not in body
