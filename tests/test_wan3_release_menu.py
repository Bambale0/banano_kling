"""Public Telegram model-picker regression: test the actual screenshot entry point."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot.handlers import video_generation_compat as video


class State:
    def __init__(self):
        self.data = {}

    async def get_data(self):
        return dict(self.data)

    async def clear(self):
        self.data.clear()

    async def update_data(self, **kwargs):
        self.data.update(kwargs)


def callback(data):
    return SimpleNamespace(
        data=data, from_user=SimpleNamespace(id=111),
        message=SimpleNamespace(edit_text=AsyncMock(), answer=AsyncMock()),
        answer=AsyncMock(),
    )


def model_buttons(markup):
    return [button for row in markup.inline_keyboard for button in row
            if (button.callback_data or '').startswith(('advanced_v_model_', 'v_model_'))]


@pytest.mark.asyncio
async def test_create_video_menu_is_compact_and_exposes_wan_family():
    event, state = callback('create_video_new'), State()
    await video.show_complete_video_model_selection(event, state)
    markup = event.message.edit_text.call_args.kwargs['reply_markup']
    assert 1 <= len(model_buttons(markup)) <= 6
    assert any('Wan' in button.text for row in markup.inline_keyboard for button in row)
    assert any((button.callback_data or '').startswith('video_models:')
               for row in markup.inline_keyboard for button in row)
    assert state.data['video_flow_step'] == 'select_model'
