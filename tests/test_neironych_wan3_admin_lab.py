"""Admin-only WAN 3.0 Neironych entry/launch regressions (no paid requests)."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot.handlers import admin_wan3_neironych_lab as lab
from bot.handlers.admin_test_lab import get_admin_test_lab_keyboard
from bot.services.neironych_wan3_admin_service import NeironychWan3AdminService


class DummyState:
    def __init__(self, data=None):
        self.data = dict(data or {})
        self.set_state = AsyncMock()
        self.clear = AsyncMock()

    async def get_data(self):
        return dict(self.data)

    async def update_data(self, **kwargs):
        self.data.update(kwargs)


def callback():
    return SimpleNamespace(
        data="admin_wan3:generate",
        from_user=SimpleNamespace(id=10001),
        message=SimpleNamespace(edit_text=AsyncMock(), answer=AsyncMock()),
        bot=SimpleNamespace(send_message=AsyncMock()),
        answer=AsyncMock(),
    )


def test_admin_test_menu_exposes_native_wan_without_replacing_kie_routes():
    buttons = [button for row in get_admin_test_lab_keyboard().inline_keyboard for button in row]
    assert sum(button.callback_data == "admin_wan3:open" for button in buttons) == 1
    assert any(button.callback_data == "admin_seedance_lab" for button in buttons)
    assert any(button.callback_data == "admin_wan3:open" and "Нейроныч" in button.text
               for button in buttons)


@pytest.mark.parametrize("action", [lab.open_lab, lab.back, lab.refresh_model, lab.toggle_audio])
async def test_admin_callbacks_fail_closed(monkeypatch, action):
    monkeypatch.setattr(lab.config, "is_admin", lambda _tid: False)
    cb = callback()
    state = DummyState()
    if action == lab.refresh_model:
        await action(cb)
    else:
        await action(cb, state)
    cb.answer.assert_awaited_once_with("⛔ Нет доступа", show_alert=True)
    cb.message.edit_text.assert_not_awaited()


async def test_admin_submit_uses_neironych_and_does_not_debit_credits(monkeypatch):
    cb = callback()
    state = DummyState({"wan_lab_prompt": "A train in the mountains"})
    provider = SimpleNamespace(
        enabled=True,
        list_enabled_wan_models=AsyncMock(return_value={"wan-3"}),
        submit=AsyncMock(return_value={"request_id": "wan-admin-request-987"}),
    )
    monkeypatch.setattr(lab.config, "is_admin", lambda _tid: True)
    monkeypatch.setattr(lab, "neironych_wan3_admin_service", provider)
    captured = []
    monkeypatch.setattr(lab, "_track", lambda coro: captured.append(coro))
    try:
        await lab.generate(cb, state)
        provider.submit.assert_awaited_once()
        args, kwargs = provider.submit.await_args
        assert args[0] == NeironychWan3AdminService.build_payload(
            mode="text", prompt="A train in the mountains", duration=5,
            resolution="720p", aspect_ratio="16:9",
        )
        assert kwargs["idempotency_key"]
        assert state.data["wan_lab_last_id"] == "wan-admin-request-987"
        assert state.data["wan_lab_pending_key"] == ""
        assert cb.message.edit_text.await_count == 1
        await lab.generate(cb, state)
        assert provider.submit.await_count == 1
    finally:
        for coro in captured:
            coro.close()


async def test_unknown_acceptance_reuses_same_idempotency_key(monkeypatch):
    cb = callback()
    state = DummyState({"wan_lab_prompt": "A fox in a green forest"})
    provider = SimpleNamespace(
        enabled=True, list_enabled_wan_models=AsyncMock(return_value={"wan-3"}),
        submit=AsyncMock(side_effect=[TimeoutError("unknown"), {"request_id": "wan-accepted"}]),
    )
    monkeypatch.setattr(lab.config, "is_admin", lambda _tid: True)
    monkeypatch.setattr(lab, "neironych_wan3_admin_service", provider)
    captured = []
    monkeypatch.setattr(lab, "_track", lambda coro: captured.append(coro))
    try:
        await lab.generate(cb, state)
        assert state.data["wan_lab_last_id"] == ""
        preserved = state.data["wan_lab_pending_key"]
        assert preserved
        await lab.generate(cb, state)
        assert provider.submit.await_count == 2
        assert provider.submit.await_args_list[0].kwargs["idempotency_key"] == preserved
        assert provider.submit.await_args_list[1].kwargs["idempotency_key"] == preserved
        assert state.data["wan_lab_last_id"] == "wan-accepted"
    finally:
        for coro in captured:
            coro.close()


async def test_catalog_failure_blocks_provider_submission(monkeypatch):
    cb = callback()
    state = DummyState({"wan_lab_prompt": "A small train"})
    provider = SimpleNamespace(
        enabled=True, list_enabled_wan_models=AsyncMock(side_effect=TimeoutError("down")),
        submit=AsyncMock(),
    )
    monkeypatch.setattr(lab.config, "is_admin", lambda _tid: True)
    monkeypatch.setattr(lab, "neironych_wan3_admin_service", provider)
    await lab.generate(cb, state)
    provider.submit.assert_not_awaited()


async def test_unprivileged_generate_never_contacts_provider(monkeypatch):
    cb = callback()
    state = DummyState({"wan_lab_prompt": "A train"})
    provider = SimpleNamespace(
        enabled=True, list_enabled_wan_models=AsyncMock(), submit=AsyncMock(),
    )
    monkeypatch.setattr(lab.config, "is_admin", lambda _tid: False)
    monkeypatch.setattr(lab, "neironych_wan3_admin_service", provider)
    await lab.generate(cb, state)
    provider.list_enabled_wan_models.assert_not_awaited()
    provider.submit.assert_not_awaited()
    cb.answer.assert_awaited_once_with("⛔ Нет доступа", show_alert=True)

@pytest.mark.parametrize("ratio", ["16:9", "9:16", "1:1", "4:3", "3:4", "21:9", "adaptive"])
async def test_admin_ratio_buttons_round_trip_full_value(monkeypatch, ratio):
    cb = callback()
    cb.data = f"admin_wan3:set_ratio:{ratio}"
    state = DummyState()
    monkeypatch.setattr(lab.config, "is_admin", lambda _tid: True)
    await lab.set_option(cb, state)
    assert state.data["wan_lab_ratio"] == ratio
    cb.answer.assert_awaited_once_with()
