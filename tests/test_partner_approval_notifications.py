import pytest

from bot.services import partner_approval_service as approval


class FakeBot:
    def __init__(self):
        self.messages = []

    async def send_message(self, chat_id, text, **kwargs):
        self.messages.append((chat_id, text, kwargs))


@pytest.mark.asyncio
async def test_admin_application_alert_contains_account_link_and_review_actions(monkeypatch):
    application = {
        "id": 505,
        "user_id": 9001,
        "telegram_id": 710505,
        "username": "partner_candidate",
        "first_name": "Partner",
        "last_name": "Candidate",
        "referral_code": "TEST505",
        "status": approval.PARTNER_APPLICATION_PENDING,
        "source": "miniapp",
    }

    async def get_application(application_id):
        assert application_id == 505
        return application

    monkeypatch.setattr(approval, "get_partner_application", get_application)
    monkeypatch.setattr(approval.config, "ADMIN_IDS_STR", "990001,990002")

    bot = FakeBot()
    await approval.notify_admins_about_partner_application(bot, 505)

    assert [item[0] for item in bot.messages] == [990001, 990002]
    for _chat_id, text, kwargs in bot.messages:
        assert "Новая заявка" in text
        assert "710505" in text
        assert "@partner_candidate" in text
        assert "https://t.me/partner_candidate" in text
        assert "miniapp" in text

        markup = kwargs["reply_markup"]
        buttons = [button for row in markup.inline_keyboard for button in row]
        account_buttons = [button for button in buttons if button.url]
        callback_buttons = [button for button in buttons if button.callback_data]

        assert len(account_buttons) == 1
        assert account_buttons[0].url == "https://t.me/partner_candidate"
        assert {button.callback_data for button in callback_buttons} == {
            "partner_app_approve_505",
            "partner_app_reject_505",
        }
        assert kwargs["parse_mode"] == "HTML"
        assert kwargs["disable_web_page_preview"] is True


@pytest.mark.asyncio
async def test_admin_application_alert_falls_back_to_telegram_id_link_without_username(monkeypatch):
    application = {
        "id": 506,
        "user_id": 9002,
        "telegram_id": 710506,
        "username": "",
        "first_name": "No",
        "last_name": "Username",
        "referral_code": "TEST506",
        "status": approval.PARTNER_APPLICATION_PENDING,
        "source": "telegram_bot",
    }

    async def get_application(_application_id):
        return application

    monkeypatch.setattr(approval, "get_partner_application", get_application)
    monkeypatch.setattr(approval.config, "ADMIN_IDS_STR", "990001")

    bot = FakeBot()
    await approval.notify_admins_about_partner_application(bot, 506)

    assert len(bot.messages) == 1
    _chat_id, text, kwargs = bot.messages[0]
    assert "tg://user?id=710506" in text
    buttons = [button for row in kwargs["reply_markup"].inline_keyboard for button in row]
    assert any(button.url == "tg://user?id=710506" for button in buttons)
