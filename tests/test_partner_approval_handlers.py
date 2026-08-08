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
async def test_telegram_partner_apply_notifies_admin_only_for_new_pending_request(monkeypatch):
    callback = FakeCallback()
    state = FakeState()
    notifications = []

    results = iter(
        [
            {
                "ok": True,
                "created": True,
                "status": handlers.PARTNER_APPLICATION_PENDING,
                "application_id": 101,
            },
            {
                "ok": True,
                "created": False,
                "status": handlers.PARTNER_APPLICATION_PENDING,
                "application_id": 101,
            },
        ]
    )

    async def submit(_telegram_id, *, source):
        assert source == "telegram_bot"
        return next(results)

    async def notify(_bot, application_id):
        notifications.append(application_id)

    monkeypatch.setattr(handlers, "submit_partner_application", submit)
    monkeypatch.setattr(handlers, "notify_admins_about_partner_application", notify)

    await handlers.partner_application_submit(callback, state)
    await handlers.partner_application_submit(callback, state)

    assert state.clear_calls == 2
    assert notifications == [101]
    assert len(callback.message.edits) == 2
    assert "рассматривается" in callback.message.edits[-1][0]
    assert callback.answers[0][0] == "Заявка отправлена администратору"
    assert callback.answers[1][0] == "Заявка уже рассматривается"


@pytest.mark.asyncio
async def test_stale_partner_stats_callback_is_gated_before_approval(monkeypatch):
    callback = FakeCallback(data="partner_stats")

    async def pending(_telegram_id):
        return {
            "status": handlers.PARTNER_APPLICATION_PENDING,
            "is_partner": False,
            "can_apply": False,
            "application_id": 202,
        }

    monkeypatch.setattr(handlers, "get_partner_application_state", pending)

    await handlers.partner_stats_gate(callback)

    assert len(callback.message.edits) == 1
    text, _kwargs = callback.message.edits[0]
    assert "рассматривается" in text
    assert "реферальная ссылка" not in text.lower() or "не привязывает" in text.lower()
    assert callback.answers[-1][0] == "Партнёрский кабинет ещё не активирован"


@pytest.mark.asyncio
async def test_non_admin_cannot_review_partner_application(monkeypatch):
    callback = FakeCallback(telegram_id=710102, data="partner_app_approve_303")
    review_calls = 0

    async def review(*_args, **_kwargs):
        nonlocal review_calls
        review_calls += 1
        return {"ok": True}

    monkeypatch.setattr(handlers, "review_partner_application", review)
    monkeypatch.setattr(handlers.config, "is_admin", lambda _telegram_id: False)

    await handlers.approve_partner_application_callback(callback)

    assert review_calls == 0
    assert callback.answers[-1][0] == "⛔ Нет доступа"
    assert callback.answers[-1][1].get("show_alert") is True


@pytest.mark.asyncio
async def test_admin_approve_updates_review_card_and_notifies_user(monkeypatch):
    admin_id = 999999999
    callback = FakeCallback(telegram_id=admin_id, data="partner_app_approve_404")
    notified = []

    async def review(application_id, *, approve, admin_telegram_id):
        assert application_id == 404
        assert approve is True
        assert admin_telegram_id == admin_id
        return {
            "ok": True,
            "status": handlers.PARTNER_APPLICATION_APPROVED,
            "application": {
                "telegram_id": 710104,
                "username": "approved_user",
            },
        }

    async def notify(_bot, application, *, approved):
        notified.append((application, approved))

    monkeypatch.setattr(handlers, "review_partner_application", review)
    monkeypatch.setattr(handlers, "notify_user_about_partner_review", notify)
    monkeypatch.setattr(handlers.config, "is_admin", lambda telegram_id: telegram_id == admin_id)

    await handlers.approve_partner_application_callback(callback)

    assert len(callback.message.edits) == 1
    assert "Одобрено" in callback.message.edits[0][0]
    assert notified == [({"telegram_id": 710104, "username": "approved_user"}, True)]
    assert callback.answers[-1][0] == "Кабинет активирован"
