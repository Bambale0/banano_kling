from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot.handlers import seedance_25_preview as preview
from bot.handlers import seedance_25_telegram_compat as compat


@pytest.mark.asyncio
async def test_admin_edit_control_preserves_reference_settings_and_locks_duration(monkeypatch):
    state = SimpleNamespace(
        get_data=AsyncMock(return_value={
            'v_model': 'seedance_2_5', 'seedance25_scenario': 'multimodal',
            'v_duration': 12, 'v_ratio': '9:16',
        }),
        update_data=AsyncMock(),
    )
    callback = SimpleNamespace(from_user=SimpleNamespace(id=123), answer=AsyncMock())
    monkeypatch.setattr(preview.config, 'is_admin', lambda _user_id: True)
    monkeypatch.setattr(preview, '_show_seedance_25_screen', AsyncMock())
    await preview.seedance25_toggle_editing(callback, state)
    state.update_data.assert_awaited_once_with(seedance25_video_editing=True)
    state.get_data.return_value['seedance25_video_editing'] = True
    state.update_data.reset_mock()
    callback.data = 's25_duration_plus'
    await preview.seedance25_duration(callback, state)
    state.update_data.assert_not_awaited()
    callback.data = 's25_ratio_16_9'
    await preview.seedance25_ratio(callback, state)
    state.update_data.assert_not_awaited()


@pytest.mark.asyncio
async def test_public_user_cannot_enable_editing_via_stale_callback(monkeypatch):
    state = SimpleNamespace(get_data=AsyncMock(return_value={
        'v_model': 'seedance_2_5', 'seedance25_scenario': 'multimodal',
    }), update_data=AsyncMock())
    callback = SimpleNamespace(from_user=SimpleNamespace(id=123), answer=AsyncMock())
    monkeypatch.setattr(preview.config, 'is_admin', lambda _user_id: False)
    await preview.seedance25_toggle_editing(callback, state)
    state.update_data.assert_not_awaited()
    assert callback.answer.await_args.kwargs['show_alert'] is True


def test_edit_keyboard_shows_source_duration_and_hides_fixed_controls():
    markup = compat._clear_seedance_keyboard({
        'seedance25_scenario': 'multimodal', 'seedance25_video_editing': True,
        'seedance25_editing_allowed': True, 'v_duration': 12, 'v_ratio': '9:16',
    })
    buttons = [button for row in markup.inline_keyboard for button in row]
    callbacks = {button.callback_data for button in buttons}
    assert 's25_toggle_editing' in callbacks
    assert 's25_duration_plus' not in callbacks
    assert 's25_ratio_9_16' not in callbacks
    assert any('исходного видео' in button.text for button in buttons)


def test_repeat_preserves_edit_intent_and_normalizes_legacy_fixed_settings():
    task = SimpleNamespace(duration=12, aspect_ratio='9:16')
    restored = compat._repeat_state_payload(task, {
        'seedance25_scenario': 'multimodal', 'seedance25_video_editing': True,
        'v_reference_videos': ['https://example.com/input.mp4'],
    }, 'replace the character')
    assert restored['seedance25_video_editing'] is True
    assert restored['v_duration'] == -1
    assert restored['v_ratio'] == 'adaptive'
