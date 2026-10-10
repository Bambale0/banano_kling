from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot.handlers import wan3_prime as tg
from tests.test_wan3_prime_telegram_fsm import FakeCallback, FakeMessage, FakeState


@pytest.mark.asyncio
async def test_user_upload_response_is_a_bot_message_not_an_edit_of_user_message():
    state = FakeState()
    message = FakeMessage(user_id=111)
    message.from_user.is_bot = False
    await tg._show_dashboard(message, state, tg.Wan3PrimeDraft())
    assert message.answers
    assert not message.edits


@pytest.mark.asyncio
async def test_shared_repeat_facade_preserves_slots_and_server_private_material(monkeypatch):
    plan = {"source_feed_gen_id": 42, "repeat_plan_hash": "hash-42",
            "recipe": {"model": "wan_3_prime", "scenario": "edit", "prompt": "", "duration": -1, "seed": 0},
            "slots": [
                {"key": "image:0", "kind": "image", "role": "reference", "index": 0, "binding": "upload"},
                {"key": "video:0", "kind": "video", "role": "source_video", "index": 0, "binding": "fixed"},
            ]}
    runtime = SimpleNamespace(repeat_plan_telegram_wan3_prime=AsyncMock(return_value=plan))
    monkeypatch.setattr(tg, "_runtime", AsyncMock(return_value=runtime))
    state = FakeState()
    await tg.open_wan3_shared_repeat(FakeCallback("wan3_repeat:42"), state)
    draft = tg.draft_from_state(await state.get_data())
    assert draft.source_feed_gen_id == 42
    assert draft.reference_video_urls == []
    draft.repeat_replacements = {"image:0": "https://owned.test/new.png"}
    tg.validate_wan3_draft(draft)
    sent = tg.build_wan3_payload(draft)
    assert sent["repeat_plan_hash"] == "hash-42"
    assert sent["repeat_replacements"] == draft.repeat_replacements
    assert sent["duration"] == -1 and sent["seed"] == 0
    assert not sent["reference_video_urls"]
    buttons = [button.callback_data for row in tg.dashboard_keyboard(draft).inline_keyboard for button in row]
    assert "wan3_repeat_slot:image:0" in buttons
    assert "wan3_media:source_video" not in buttons
    assert "wan3_modes" not in buttons
