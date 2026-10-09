"""Creator editor FSM tests: Telegram and config-file writes stay local/faked."""
import copy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot import database
from bot import db as db_backend
from bot.creator_tariff_membership import (
    get_creator_tariff_membership,
    set_creator_tariff_membership,
)
from bot.handlers import creator_tariff_admin as admin

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


def callback(data="admin_creator_tariff", actor=ADMIN):
    message = SimpleNamespace(chat=SimpleNamespace(id=actor), message_id=100)
    message.edit_text = AsyncMock(return_value=message)
    message.answer = AsyncMock(return_value=message)
    return SimpleNamespace(data=data, from_user=SimpleNamespace(id=actor), message=message, answer=AsyncMock())


def message(text, actor=ADMIN, mid=101):
    return SimpleNamespace(text=text, from_user=SimpleNamespace(id=actor), message_id=mid, answer=AsyncMock(return_value=SimpleNamespace(message_id=mid)))


def action(state, name, *values):
    return admin._cb(name, state.data["creator_token"], *values)


@pytest.fixture
def editor(monkeypatch):
    prices = {
        "packages": [{"id": "untouched", "price_rub": 321}],
        "service_prices": {"video_prompt": 99},
        "costs_reference": {"video_models": {
            "seedance_2": {"quality_costs": {"720p": 21}},
            "seedance_2_5": {"quality_costs": {"480p": 22, "720p": 23, "1080p": 24}},
        }},
    }
    monkeypatch.setattr(admin.preset_manager, "_price_config", copy.deepcopy(prices))
    writes = []

    def update(value):
        writes.append(copy.deepcopy(value))
        admin.preset_manager._price_config = copy.deepcopy(value)
        return True

    monkeypatch.setattr(admin.preset_manager, "update_price_config", update)
    monkeypatch.setattr(admin.config, "is_admin", lambda uid: uid == ADMIN)
    return FakeState(), callback(), writes, prices


def complete_config(*, enabled=False):
    return {"enabled": enabled, "video_models": {
        model: {"quality_costs": {quality: 3 + index for index, quality in enumerate(qualities)}}
        for model, qualities in admin.creator_tariff_status()["required_qualities"].items()
    }}


async def click(state, cb, name, *values):
    cb.data = action(state, name, *values)
    await admin.creator_tariff_callback(cb, state)


async def lookup(state, cb):
    await database.get_or_create_user(TARGET)
    await admin.open_creator_tariff(cb, state)
    await click(state, cb, "lookup")
    await admin.creator_tariff_message(message(str(TARGET)), state)


@pytest.mark.asyncio
@pytest.mark.parametrize("entry", ["open", "callback", "message"])
async def test_all_entrypoints_reject_non_admin(editor, entry):
    state, cb, writes, _ = editor
    cb.from_user.id = TARGET
    if entry == "open":
        await admin.open_creator_tariff(cb, state)
    elif entry == "callback":
        cb.data = "admin_ct:lookup:fake"
        await admin.creator_tariff_callback(cb, state)
    else:
        cb = message("123", actor=TARGET)
        await admin.creator_tariff_message(cb, state)
    assert "Нет доступа" in cb.answer.await_args.args[0]
    assert state.data == {}
    assert writes == []


@pytest.mark.asyncio
async def test_grant_requires_confirmation_and_replay_does_not_reapply(editor):
    state, cb, *_ = editor
    await lookup(state, cb)
    await click(state, cb, "member", TARGET, 1)
    assert not await get_creator_tariff_membership(TARGET)
    confirmation = action(state, "confirm")
    cb.data = confirmation
    await admin.creator_tariff_callback(cb, state)
    assert await get_creator_tariff_membership(TARGET)
    await set_creator_tariff_membership(ADMIN, TARGET, False)
    cb.data = confirmation
    await admin.creator_tariff_callback(cb, state)
    assert not await get_creator_tariff_membership(TARGET)
    assert cb.answer.await_args.kwargs["show_alert"]


@pytest.mark.asyncio
async def test_cancelled_membership_confirmation_cannot_be_replayed(editor):
    state, cb, *_ = editor
    await lookup(state, cb)
    await click(state, cb, "member", TARGET, 1)
    old = action(state, "confirm")
    await click(state, cb, "home")
    cb.data = old
    await admin.creator_tariff_callback(cb, state)
    assert not await get_creator_tariff_membership(TARGET)


@pytest.mark.asyncio
async def test_admin_permission_rechecked_at_confirmation(editor, monkeypatch):
    state, cb, *_ = editor
    await lookup(state, cb)
    await click(state, cb, "member", TARGET, 1)
    monkeypatch.setattr(admin.config, "is_admin", lambda _uid: False)
    await click(state, cb, "confirm")
    assert not await get_creator_tariff_membership(TARGET)


@pytest.mark.asyncio
async def test_unknown_lookup_never_creates_a_user(editor):
    state, cb, *_ = editor
    await admin.open_creator_tariff(cb, state)
    await click(state, cb, "lookup")
    msg = message(str(TARGET))
    await admin.creator_tariff_message(msg, state)
    assert "не найден" in msg.answer.await_args.args[0]
    async with db_backend.connect() as db:
        assert await (await db.execute("SELECT id FROM users WHERE telegram_id = ?", (TARGET,))).fetchone() is None


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["0", "-1", "abc", "1.5", "9223372036854775808", "9" * 5000])
async def test_lookup_rejects_malformed_ids(editor, value):
    state, cb, *_ = editor
    await admin.open_creator_tariff(cb, state)
    await click(state, cb, "lookup")
    msg = message(value)
    await admin.creator_tariff_message(msg, state)
    assert "Telegram ID" in msg.answer.await_args.args[0]
    assert state.state == admin.CreatorTariffAdminStates.user_id.state


@pytest.mark.asyncio
async def test_menu_includes_runtime_1080p_and_ordinary_fallback(editor):
    state, cb, *_ = editor
    await admin.open_creator_tariff(cb, state)
    assert "обычная цена" in cb.message.edit_text.await_args.args[0]
    await click(state, cb, "prices")
    text = cb.message.edit_text.await_args.args[0]
    assert "Seedance 2.5 · 1080p" in text
    assert "×2" in text and "не задано" in text
    markup = cb.message.edit_text.await_args.kwargs["reply_markup"]
    assert all(len(button.callback_data.encode()) <= 64 for row in markup.inline_keyboard for button in row)


@pytest.mark.asyncio
async def test_edit_one_rate_keeps_other_prices_and_feature_disabled(editor):
    state, cb, writes, before = editor
    await admin.open_creator_tariff(cb, state)
    await click(state, cb, "prices")
    await click(state, cb, "rate", "seedance_2_5", "1080p")
    await admin.creator_tariff_message(message("2,75"), state)
    assert len(writes) == 1
    assert {key: value for key, value in writes[0].items() if key != "creator_tariff"} == before
    tariff = writes[0]["creator_tariff"]
    assert tariff == {"enabled": False, "video_models": {"seedance_2_5": {"quality_costs": {"1080p": 2.75}}}}
    async with db_backend.connect() as db:
        rows = await (await db.execute("SELECT event_type, before_state, after_state FROM creator_tariff_audit")).fetchall()
    assert {row[0] for row in rows} == {"config_change_requested", "config_updated"}
    assert all(json.loads(row[1]) == {} and json.loads(row[2]) == tariff for row in rows)


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf", "-inf", "not a price", "1e309"])
async def test_invalid_prices_never_write(editor, value):
    state, cb, writes, _ = editor
    await admin.open_creator_tariff(cb, state)
    await click(state, cb, "prices")
    await click(state, cb, "rate", "seedance_2", "720p")
    await admin.creator_tariff_message(message(value), state)
    assert not writes
    assert state.state == admin.CreatorTariffAdminStates.price.state


@pytest.mark.asyncio
async def test_stale_input_message_is_ignored(editor):
    state, cb, writes, _ = editor
    await admin.open_creator_tariff(cb, state)
    await click(state, cb, "prices")
    await click(state, cb, "rate", "seedance_2", "720p")
    await admin.creator_tariff_message(message("2", mid=99), state)
    assert not writes


@pytest.mark.asyncio
async def test_enable_requires_complete_quality_rates(editor):
    state, cb, writes, _ = editor
    await admin.open_creator_tariff(cb, state)
    await click(state, cb, "toggle", 1)
    assert not writes
    assert cb.answer.await_args.kwargs["show_alert"]
    assert state.state != admin.CreatorTariffAdminStates.confirmation.state


@pytest.mark.asyncio
async def test_enable_confirmation_and_disable_preserve_memberships(editor):
    state, cb, writes, _ = editor
    admin.preset_manager._price_config["creator_tariff"] = complete_config()
    await database.get_or_create_user(TARGET)
    await set_creator_tariff_membership(ADMIN, TARGET, True)
    await admin.open_creator_tariff(cb, state)
    await click(state, cb, "toggle", 1)
    assert not writes
    await click(state, cb, "confirm")
    assert admin.creator_tariff_status()["enabled"]
    await click(state, cb, "toggle", 0)
    assert admin.creator_tariff_status()["enabled"]
    await click(state, cb, "confirm")
    assert not admin.creator_tariff_status()["enabled"]
    assert await get_creator_tariff_membership(TARGET)


@pytest.mark.asyncio
async def test_changed_config_invalidates_confirmation(editor):
    state, cb, writes, _ = editor
    admin.preset_manager._price_config["creator_tariff"] = complete_config()
    await admin.open_creator_tariff(cb, state)
    await click(state, cb, "toggle", 1)
    admin.preset_manager._price_config["creator_tariff"]["video_models"]["seedance_2"]["quality_costs"]["720p"] = 8
    await click(state, cb, "confirm")
    assert not writes
    assert "уже изменились" in cb.answer.await_args.args[0]


@pytest.mark.asyncio
async def test_config_service_rejects_nonadmin(editor):
    with pytest.raises(PermissionError):
        await admin.save_creator_tariff_config(TARGET, complete_config(), expected_fingerprint="{}")
    assert not editor[2]


@pytest.mark.asyncio
async def test_audit_failure_prevents_config_write(editor, monkeypatch):
    monkeypatch.setattr(admin, "record_creator_tariff_config_audit", AsyncMock(side_effect=RuntimeError("audit unavailable")))
    with pytest.raises(RuntimeError, match="audit unavailable"):
        await admin.save_creator_tariff_config(ADMIN, complete_config(), expected_fingerprint="{}")
    assert not editor[2]


@pytest.mark.asyncio
async def test_intervening_ordinary_price_edit_is_preserved(editor, monkeypatch):
    async def audit(*args, **kwargs):
        admin.preset_manager._price_config["service_prices"]["video_prompt"] = 101

    monkeypatch.setattr(admin, "record_creator_tariff_config_audit", audit)
    await admin.save_creator_tariff_config(ADMIN, complete_config(), expected_fingerprint="{}")
    assert editor[2][-1]["service_prices"]["video_prompt"] == 101


@pytest.mark.asyncio
async def test_intervening_creator_price_edit_blocks_stale_write(editor, monkeypatch):
    async def audit(*args, **kwargs):
        admin.preset_manager._price_config["creator_tariff"] = complete_config()

    monkeypatch.setattr(admin, "record_creator_tariff_config_audit", audit)
    with pytest.raises(admin.CreatorTariffConfigConflict):
        await admin.save_creator_tariff_config(ADMIN, complete_config(), expected_fingerprint="{}")
    assert not editor[2]


@pytest.mark.asyncio
async def test_fresh_price_prompt_rejects_input_sent_before_it(editor):
    state, cb, writes, _ = editor
    await admin.open_creator_tariff(cb, state)
    await click(state, cb, "prices")
    cb.message.answer.return_value = SimpleNamespace(message_id=150)
    await click(state, cb, "rate", "seedance_2", "720p")
    assert state.data["creator_prompt_id"] == 150
    await admin.creator_tariff_message(message("2", mid=149), state)
    assert not writes
    await admin.creator_tariff_message(message("2", mid=151), state)
    assert len(writes) == 1
