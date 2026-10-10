"""Telegram first-line commission editor: local FSM/service boundary tests."""
import asyncio
import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot.handlers import partner_rate_admin as admin

ADMIN = 999999999
TARGET = 12345678


class FakeState:
    def __init__(self):
        self.data = {}
        self.state = None

    async def get_data(self):
        return copy.deepcopy(self.data)

    async def update_data(self, **values):
        self.data.update(values)

    async def clear(self):
        self.data = {}
        self.state = None

    async def get_state(self):
        return self.state

    async def set_state(self, value):
        self.state = value.state if hasattr(value, "state") else value


def callback(data="admin_partner_rates", actor=ADMIN):
    msg = SimpleNamespace(chat=SimpleNamespace(id=actor), message_id=100)
    msg.edit_text = AsyncMock(return_value=msg)
    msg.answer = AsyncMock(return_value=msg)
    return SimpleNamespace(
        data=data, from_user=SimpleNamespace(id=actor), message=msg,
        answer=AsyncMock(), bot=SimpleNamespace(send_message=AsyncMock(return_value=msg)),
    )


def message(text, actor=ADMIN, mid=101, reply_to=None):
    return SimpleNamespace(
        text=text, from_user=SimpleNamespace(id=actor), message_id=mid,
        reply_to_message=reply_to,
        answer=AsyncMock(return_value=SimpleNamespace(message_id=mid)),
    )


def action(state, name, *args):
    return admin._cb(name, state.data["partner_rate_token"], *args)


async def click(state, cb, name, *args):
    cb.data = action(state, name, *args)
    await admin.partner_rate_callback(cb, state)


async def lookup(state, cb):
    await admin.open_partner_rates(cb, state)
    await click(state, cb, "lookup")
    await admin.partner_rate_message(message(str(TARGET)), state)


@pytest.fixture
def editor(monkeypatch):
    setting = {
        "telegram_id": TARGET, "effective_percent": 30.0, "override_percent": None,
        "revision": 0, "source": "default", "username": "a<partner>",
    }
    writes = []

    async def get(target):
        return copy.deepcopy(setting) if target == TARGET else None

    async def save(actor, target, percent, *, expected_revision):
        assert actor == ADMIN and target == TARGET
        if expected_revision != setting["revision"]:
            raise admin.PartnerCommissionConflict("stale")
        changed = percent != setting["override_percent"]
        if changed:
            writes.append((actor, target, percent, expected_revision))
            setting.update(effective_percent=percent, override_percent=percent,
                           revision=expected_revision + 1, source="admin")
        return {**setting, "changed": changed}

    getter, setter = AsyncMock(side_effect=get), AsyncMock(side_effect=save)
    monkeypatch.setattr(admin, "get_partner_commission_setting", getter)
    monkeypatch.setattr(admin, "set_partner_commission_percent", setter)
    monkeypatch.setattr(admin.config, "is_admin", lambda uid: uid == ADMIN)
    return FakeState(), callback(), setting, writes, getter, setter


@pytest.mark.asyncio
async def test_lookup_and_refresh_are_read_only_and_escape_profile(editor):
    state, cb, _, writes, _, setter = editor
    await lookup(state, cb)
    await click(state, cb, "view")
    text = cb.message.edit_text.await_args.args[0]
    assert "30%" in text and "a&lt;partner&gt;" in text
    assert "первая линия" in text.lower()
    assert not writes and not setter.await_count
    markup = cb.message.edit_text.await_args.kwargs["reply_markup"]
    buttons = [button for row in markup.inline_keyboard for button in row]
    assert {"0%", "30%", "40%"} <= {button.text for button in buttons}
    assert all(len(button.callback_data.encode()) <= 64 for button in buttons)


@pytest.mark.asyncio
@pytest.mark.parametrize("percent", [0, 30, 40])
async def test_quick_rate_requires_confirmation_and_preserves_zero(editor, percent):
    state, cb, setting, writes, _, setter = editor
    await lookup(state, cb)
    await click(state, cb, "quick", percent)
    assert not setter.await_count and not writes
    text = cb.message.edit_text.await_args.args[0]
    assert "30%" in text and f"{percent}%" in text and str(TARGET) in text
    assert "вторая линия" in text.lower() and "повторы" in text.lower()
    await click(state, cb, "confirm")
    setter.assert_awaited_once_with(ADMIN, TARGET, float(percent), expected_revision=0)
    assert setting["effective_percent"] == percent
    assert len(writes) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("raw,expected", [("0", 0), ("2,75", 2.75), ("33.3", 33.3), ("100", 100), (" 45.5 ", 45.5)])
async def test_custom_rate_is_validated_and_confirmed(editor, raw, expected):
    state, cb, setting, _, _, setter = editor
    await lookup(state, cb)
    await click(state, cb, "custom")
    await admin.partner_rate_message(message(raw), state)
    assert state.state == admin.PartnerRateAdminStates.confirmation.state
    assert not setter.await_count
    await click(state, cb, "confirm")
    assert setting["effective_percent"] == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", ["-1", "100.01", "33.333", "33.3000000000000000000000000000000001", "0.001", "1e-999999999", "nan", "inf", "-inf", "1e309", "true", "", "9" * 5000])
async def test_invalid_custom_rate_never_mutates(editor, raw):
    state, cb, _, _, _, setter = editor
    await lookup(state, cb)
    await click(state, cb, "custom")
    await admin.partner_rate_message(message(raw), state)
    assert state.state == admin.PartnerRateAdminStates.percent.state
    assert not setter.await_count


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", ["0", "-1", "abc", "1.5", "9223372036854775808", "9" * 5000, "١٢٣"])
async def test_invalid_id_never_queries_or_mutates(editor, raw):
    state, cb, _, _, getter, setter = editor
    await admin.open_partner_rates(cb, state)
    await click(state, cb, "lookup")
    msg = message(raw)
    await admin.partner_rate_message(msg, state)
    assert "Telegram ID" in msg.answer.await_args.args[0]
    assert state.state == admin.PartnerRateAdminStates.user_id.state
    assert not getter.await_count and not setter.await_count


@pytest.mark.asyncio
async def test_unknown_user_is_not_created(editor):
    state, cb, _, _, getter, setter = editor
    await admin.open_partner_rates(cb, state)
    await click(state, cb, "lookup")
    msg = message("987654321")
    await admin.partner_rate_message(msg, state)
    assert "не найден" in msg.answer.await_args.args[0]
    getter.assert_awaited_once_with(987654321)
    assert not setter.await_count


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ["open", "callback", "message"])
async def test_non_admin_is_denied_at_each_entry(editor, entry):
    state, cb, _, _, getter, setter = editor
    if entry == "open":
        await admin.open_partner_rates(callback(actor=42), state)
    else:
        await lookup(state, cb)
        getter.reset_mock()
        if entry == "callback":
            await admin.partner_rate_callback(callback(action(state, "quick", 40), actor=42), state)
        else:
            await admin.partner_rate_message(message("40", actor=42), state)
    assert not getter.await_count and not setter.await_count


@pytest.mark.asyncio
async def test_permission_is_rechecked_at_confirmation(editor, monkeypatch):
    state, cb, _, _, _, setter = editor
    await lookup(state, cb)
    await click(state, cb, "quick", 40)
    monkeypatch.setattr(admin.config, "is_admin", lambda _: False)
    await click(state, cb, "confirm")
    assert not setter.await_count
    assert cb.answer.await_args.kwargs["show_alert"]


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", ["cancel", "home"])
async def test_cancel_invalidates_old_confirmation(editor, cancel):
    state, cb, _, _, _, setter = editor
    await lookup(state, cb)
    await click(state, cb, "quick", 40)
    previous = action(state, "confirm")
    await click(state, cb, cancel)
    cb.data = previous
    await admin.partner_rate_callback(cb, state)
    assert not setter.await_count
    assert cb.answer.await_args.kwargs["show_alert"]


@pytest.mark.asyncio
async def test_duplicate_confirmation_runs_only_once(editor):
    state, cb, _, _, _, setter = editor
    await lookup(state, cb)
    await click(state, cb, "quick", 40)
    previous = action(state, "confirm")
    await asyncio.gather(
        admin.partner_rate_callback(callback(previous), state),
        admin.partner_rate_callback(callback(previous), state),
    )
    assert setter.await_count == 1


@pytest.mark.asyncio
async def test_expired_confirmation_never_mutates(editor, monkeypatch):
    state, cb, _, _, _, setter = editor
    await lookup(state, cb)
    await click(state, cb, "quick", 40)
    monkeypatch.setattr(admin.time, "time", lambda: state.data["partner_rate_expires_at"] + 1)
    await click(state, cb, "confirm")
    assert not setter.await_count
    assert not state.data
    assert cb.answer.await_args.kwargs["show_alert"]


@pytest.mark.asyncio
async def test_expired_message_never_mutates(editor):
    state, cb, _, _, _, setter = editor
    await lookup(state, cb)
    await click(state, cb, "custom")
    state.data["partner_rate_expires_at"] = 0
    await admin.partner_rate_message(message("40"), state)
    assert not setter.await_count and not state.data


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["selection", "confirmation", "custom"])
async def test_changed_setting_requires_fresh_review(editor, stage):
    state, cb, setting, _, _, setter = editor
    await lookup(state, cb)
    if stage == "confirmation":
        await click(state, cb, "quick", 40)
    elif stage == "custom":
        await click(state, cb, "custom")
    setting.update(effective_percent=50.0, revision=1)
    if stage == "custom":
        await admin.partner_rate_message(message("40"), state)
    else:
        await click(state, cb, "confirm" if stage == "confirmation" else "quick", *([] if stage == "confirmation" else [40]))
    assert not setter.await_count
    assert state.data["partner_rate_snapshot"]["effective_percent"] == 50.0


@pytest.mark.asyncio
async def test_concurrent_service_revision_conflict_does_not_retry(editor):
    state, cb, _, _, _, setter = editor
    await lookup(state, cb)
    await click(state, cb, "quick", 40)
    setter.side_effect = admin.PartnerCommissionConflict("concurrent edit")
    await click(state, cb, "confirm")
    assert setter.await_count == 1
    assert "изменилась" in cb.message.edit_text.await_args.args[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", ["{prefix}:confirm:bad", "{prefix}:quick:40:ю", "{prefix}:quick:99:{token}"])
async def test_forged_callbacks_do_not_mutate(editor, raw):
    state, cb, _, _, _, setter = editor
    await lookup(state, cb)
    cb.data = raw.format(prefix=admin.PREFIX, token=state.data["partner_rate_token"])
    await admin.partner_rate_callback(cb, state)
    assert not setter.await_count
    assert cb.answer.await_args.kwargs["show_alert"]


@pytest.mark.asyncio
async def test_old_input_and_reply_to_previous_prompt_are_ignored(editor):
    state, cb, _, _, _, setter = editor
    await lookup(state, cb)
    await click(state, cb, "custom")
    await admin.partner_rate_message(message("40", mid=99), state)
    await admin.partner_rate_message(message("40", reply_to=SimpleNamespace(message_id=99)), state)
    assert state.state == admin.PartnerRateAdminStates.percent.state
    assert not setter.await_count


@pytest.mark.asyncio
async def test_service_failure_consumes_confirmation_without_claiming_success(editor):
    state, cb, _, _, _, setter = editor
    await lookup(state, cb)
    await click(state, cb, "quick", 40)
    previous = action(state, "confirm")
    setter.side_effect = RuntimeError("database unavailable")
    await click(state, cb, "confirm")
    assert "Проверьте" in cb.message.edit_text.await_args.args[0]
    cb.data = previous
    await admin.partner_rate_callback(cb, state)
    assert setter.await_count == 1


def test_admin_menu_exposes_percentage_editor():
    from bot.handlers.admin import _admin_partners_keyboard

    assert "admin_partner_rates" in {
        button.callback_data
        for row in _admin_partners_keyboard([]).inline_keyboard for button in row
    }


@pytest.mark.asyncio
async def test_handler_confirmation_uses_real_sqlite_service_and_single_audit(monkeypatch):
    from bot import database
    from bot import db as db_backend
    from bot.partner_commission_settings import get_partner_commission_setting

    monkeypatch.setattr(admin.config, "is_admin", lambda uid: uid == ADMIN)
    await database.get_or_create_user(TARGET)
    state, cb = FakeState(), callback()
    async with db_backend.connect() as db:
        before = await (await db.execute("SELECT * FROM users WHERE telegram_id = ?", (TARGET,))).fetchone()
    await lookup(state, cb)
    await click(state, cb, "quick", 0)
    async with db_backend.connect() as db:
        assert (await (await db.execute("SELECT COUNT(*) FROM partner_commission_audit")).fetchone())[0] == 0
    confirmation = action(state, "confirm")
    await click(state, cb, "confirm")
    assert (await get_partner_commission_setting(TARGET))["effective_percent"] == 0
    cb.data = confirmation
    await admin.partner_rate_callback(cb, state)
    await click(state, cb, "quick", 0)
    await click(state, cb, "confirm")
    async with db_backend.connect() as db:
        assert (await (await db.execute("SELECT COUNT(*) FROM partner_commission_audit")).fetchone())[0] == 1
        after = await (await db.execute("SELECT * FROM users WHERE telegram_id = ?", (TARGET,))).fetchone()
        assert after == before


@pytest.mark.asyncio
async def test_registered_dispatcher_journey_bypasses_subscription_only_for_admin(editor, monkeypatch):
    from datetime import datetime, timezone

    from aiogram import Bot, types
    from aiogram.fsm.storage.memory import MemoryStorage

    from bot import main

    _, _, setting, _, _, setter = editor
    monkeypatch.setattr(main, "_build_dispatcher_storage", MemoryStorage)
    subscription_check = AsyncMock(return_value=True)
    monkeypatch.setattr(main, "is_channel_subscription_required", subscription_check)
    dp = main.setup_dispatcher()
    bot = Bot("123456:TEST_TOKEN_FOR_CI_ONLY")
    actor = types.User(id=ADMIN, is_bot=False, first_name="Admin")
    chat = types.Chat(id=ADMIN, type="private")
    date = datetime.now(timezone.utc)
    menu = types.Message(message_id=100, date=date, chat=chat,
                         from_user=types.User(id=123456, is_bot=True, first_name="Bot"), text="Menu")
    transport = AsyncMock(return_value=menu)
    monkeypatch.setattr(bot.session, "make_request", transport)
    state = dp.fsm.get_context(bot=bot, chat_id=ADMIN, user_id=ADMIN)
    sequence = 0

    async def click_update(data):
        nonlocal sequence
        sequence += 1
        await dp.feed_update(bot, types.Update(
            update_id=sequence, callback_query=types.CallbackQuery(
                id=str(sequence), from_user=actor, chat_instance="test", message=menu, data=data,
            ),
        ))

    async def click_action(name, *args):
        data = await state.get_data()
        await click_update(admin._cb(name, data["partner_rate_token"], *args))

    async def send_text(text):
        nonlocal sequence
        sequence += 1
        await dp.feed_update(bot, types.Update(
            update_id=sequence, message=types.Message(
                message_id=100 + sequence, date=date, chat=chat, from_user=actor, text=text,
            ),
        ))

    try:
        names = [router.name for router in dp.sub_routers]
        assert names.index("partner_rate_admin") < dp.sub_routers.index(main.admin_router)
        await click_update("admin_partner_rates")
        await click_action("lookup")
        await send_text(str(TARGET))
        assert (await state.get_data())["partner_rate_snapshot"]["telegram_id"] == TARGET
        await click_action("custom")
        await send_text("0")
        assert await state.get_state() == admin.PartnerRateAdminStates.confirmation.state
        assert not setter.await_count
        previous = admin._cb("confirm", (await state.get_data())["partner_rate_token"])
        await click_action("confirm")
        assert setting["effective_percent"] == 0 and setter.await_count == 1
        await click_update(previous)
        assert setter.await_count == 1
        subscription_check.assert_not_awaited()
        await click_action("custom")
        await send_text("/admin")
        assert await state.get_state() is None
        subscription_check.return_value = False
        actor = types.User(id=42, is_bot=False, first_name="Regular user")
        await click_update("admin_partner_rates")
        subscription_check.assert_awaited_once()
        assert setter.await_count == 1
        assert "Нет доступа" in str(transport.call_args_list)
    finally:
        await bot.session.close()
        await dp.storage.close()
        for child_router in dp.sub_routers:
            child_router._parent_router = None
        dp.sub_routers.clear()


@pytest.mark.asyncio
async def test_configuration_change_without_db_revision_requires_new_review(editor):
    state, cb, setting, _, _, setter = editor
    await lookup(state, cb)
    await click(state, cb, "quick", 40)
    setting.update(effective_percent=25.0, source="configuration")
    await click(state, cb, "confirm")
    assert not setter.await_count
    assert state.data["partner_rate_snapshot"]["effective_percent"] == 25.0


@pytest.mark.asyncio
async def test_confirmation_that_expires_during_read_never_mutates(editor):
    state, cb, _, _, getter, setter = editor
    await lookup(state, cb)
    await click(state, cb, "quick", 40)
    read = getter.side_effect
    expired = False
    original_expired = admin._expired

    async def slow_read(target):
        nonlocal expired
        result = await read(target)
        expired = True
        return result

    from unittest.mock import patch

    getter.side_effect = slow_read
    with patch.object(admin, "_expired", side_effect=lambda data: expired or original_expired(data)):
        await click(state, cb, "confirm")
    assert not setter.await_count and not state.data


@pytest.mark.asyncio
async def test_callback_without_message_has_safe_private_fallback(editor):
    state, cb, _, _, _, setter = editor
    cb.message = None
    await admin.open_partner_rates(cb, state)
    cb.bot.send_message.assert_awaited_once()
    assert cb.bot.send_message.await_args.args[0] == ADMIN
    assert not setter.await_count


@pytest.mark.asyncio
async def test_reopening_editor_invalidates_existing_confirmation(editor):
    state, cb, _, _, _, setter = editor
    await lookup(state, cb)
    await click(state, cb, "quick", 40)
    previous = action(state, "confirm")
    await admin.open_partner_rates(cb, state)
    cb.data = previous
    await admin.partner_rate_callback(cb, state)
    assert not setter.await_count
