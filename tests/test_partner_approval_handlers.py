from types import SimpleNamespace

import pytest

from bot.handlers import partner_approval as handlers


class FakeMessage:
    def __init__(self):
        self.edits = []
        self.answers = []

    async def edit_text(self, text, **kwargs):
        self.edits.append((text, kwargs))

    async def answer(self, text, **kwargs):
        self.answers.append((text, kwargs))


class FakeCallback:
    def __init__(self, telegram_id=710100, data="", bot=None):
        self.from_user = SimpleNamespace(id=telegram_id)
        self.message = FakeMessage()
        self.data = data
        self.bot = bot or object()
        self.answers = []

    async def answer(self, text=None, **kwargs):
        self.answers.append((text, kwargs))


class FakeState:
    def __init__(self):
        self.clear_calls = 0

    async def clear(self):
        self.clear_calls += 1


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["menu_partner", "menu_referrals", "partner_accept"])
async def test_partner_buttons_open_cabinet_without_application(monkeypatch, route):
    from unittest.mock import AsyncMock

    from bot.handlers import common

    callback = FakeCallback(data=route)
    state = FakeState()
    render = AsyncMock()
    monkeypatch.setattr(common, "render_partner_program", render)
    handler = handlers.partner_application_submit if route == "partner_accept" else handlers.partner_menu
    await handler(callback, state)
    await handler(callback, state)
    assert state.clear_calls == 2
    assert render.await_count == 2
    render.assert_awaited_with(callback.message, user_id=callback.from_user.id)
    assert not callback.message.edits


@pytest.mark.asyncio
async def test_stale_stats_callback_delegates_without_gate(monkeypatch):
    from unittest.mock import AsyncMock

    from bot.handlers import common

    callback = FakeCallback(data="partner_stats")
    stats = AsyncMock()
    monkeypatch.setattr(common, "partner_stats", stats)
    await handlers.partner_stats_gate(callback)
    stats.assert_awaited_once_with(callback)


@pytest.mark.asyncio
@pytest.mark.parametrize("approve", [True, False])
async def test_non_admin_cannot_review_partner_application(monkeypatch, approve):
    from unittest.mock import AsyncMock

    callback = FakeCallback(data="partner_app_approve_303" if approve else "partner_app_reject_303")
    review = AsyncMock()
    monkeypatch.setattr(handlers, "review_partner_application", review)
    monkeypatch.setattr(handlers.config, "is_admin", lambda _telegram_id: False)
    handler = handlers.approve_partner_application_callback if approve else handlers.reject_partner_application_callback
    await handler(callback)
    review.assert_not_awaited()
    assert callback.answers[-1] == ("⛔ Нет доступа", {"show_alert": True})


@pytest.mark.asyncio
@pytest.mark.parametrize("approve", [True, False])
async def test_admin_stale_review_reports_retired_activation(monkeypatch, approve):
    from unittest.mock import AsyncMock

    callback = FakeCallback(telegram_id=999999999, data="partner_app_approve_404" if approve else "partner_app_reject_404")
    review = AsyncMock(return_value={"ok": False, "reason": "activation_not_required"})
    monkeypatch.setattr(handlers, "review_partner_application", review)
    monkeypatch.setattr(handlers.config, "is_admin", lambda _telegram_id: True)
    handler = handlers.approve_partner_application_callback if approve else handlers.reject_partner_application_callback
    await handler(callback)
    review.assert_awaited_once_with(404, approve=approve, admin_telegram_id=999999999)
    assert "Активация больше не требуется" in callback.answers[-1][0]
    assert not callback.message.edits


@pytest.mark.asyncio
async def test_command_opens_partner_cabinet(monkeypatch):
    from unittest.mock import AsyncMock

    from bot.handlers import common

    message = FakeMessage()
    message.from_user = SimpleNamespace(id=710105)
    state = FakeState()
    render = AsyncMock()
    monkeypatch.setattr(common, "render_partner_program", render)
    await handlers.partner_command(message, state)
    render.assert_awaited_once_with(message, user_id=710105)
    assert state.clear_calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("percent", [0, 30, 40])
async def test_partner_dashboard_uses_individual_rate_and_earned_bonus_wording(monkeypatch, percent):
    from unittest.mock import AsyncMock

    from bot.handlers import common

    target = FakeMessage()
    target.bot = SimpleNamespace(get_me=AsyncMock(return_value=SimpleNamespace(username="test_bot")))
    monkeypatch.setattr(common, "get_or_create_user", AsyncMock(return_value=SimpleNamespace(referral_code="OPENPARTNER")))
    monkeypatch.setattr(common, "get_partner_overview", AsyncMock(return_value={
        "is_partner": True, "percent": percent, "level2_percent": 7,
        "new_user_bonus": 5, "inviter_bonus": 3,
    }))
    await common.render_partner_program(target, user_id=710100)
    text, kwargs = target.edits[-1]
    assert f"<code>{percent}%</code>" in text
    assert "<code>5</code>" in text
    assert "после его первой генерации" in text
    assert "<code>15</code>" not in text
    buttons = [button for row in kwargs["reply_markup"].inline_keyboard for button in row]
    assert not any(button.callback_data == "partner_accept" for button in buttons)
    assert any(button.callback_data == "partner_withdraw" for button in buttons)


def test_partner_keyboards_do_not_offer_activation_or_synthetic_consent():
    from bot.keyboards import get_partner_consent_keyboard, get_partner_program_keyboard

    for markup in (get_partner_consent_keyboard(), get_partner_program_keyboard("", is_partner=False)):
        assert not any(button.callback_data == "partner_accept" for row in markup.inline_keyboard for button in row)


@pytest.mark.asyncio
async def test_direct_legacy_accept_opens_cabinet_without_writing_agreement(monkeypatch):
    from unittest.mock import AsyncMock

    from bot import database
    from bot.handlers import common

    callback = FakeCallback(data="partner_accept")
    agreement = AsyncMock()
    render = AsyncMock()
    monkeypatch.setattr(database, "accept_partner_agreement", agreement)
    monkeypatch.setattr(common, "render_partner_program", render)
    await common.accept_partner(callback)
    agreement.assert_not_awaited()
    render.assert_awaited_once_with(callback.message, user_id=callback.from_user.id)
