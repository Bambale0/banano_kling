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


@pytest.mark.asyncio
@pytest.mark.parametrize('previous', [{}, {
    'video_model_family': 'all', 'video_model_page': 3, 'v_model': 'veo3',
}])
async def test_new_video_opens_seedance_family_even_after_browsing_another_tab(previous):
    event, state = callback('create_video_new'), State()
    state.data.update(previous)

    await video.show_complete_video_model_selection(event, state)

    markup = event.message.edit_text.call_args.kwargs['reply_markup']
    assert state.data['video_model_family'] == 'seedance'
    assert state.data['video_model_page'] == 0
    assert [button.callback_data for button in model_buttons(markup)] == [
        'v_model_seedance_2_5', 'advanced_v_model_seedance_2',
    ]
    assert any(button.text == '• Seedance'
               for row in markup.inline_keyboard for button in row)
    assert state.data['v_model'] == 'v3_pro'
    event.answer.assert_awaited_once()


@pytest.mark.asyncio
async def test_all_tab_still_paginates_every_public_model_after_seedance_entry():
    state = State()
    await video.show_complete_video_model_selection(callback('create_video_new'), state)
    next_page, seen = 'video_models:all:0', set()
    for page in range(4):
        event = callback(next_page)
        await video.show_video_models_page(event, state)
        markup = event.message.edit_text.call_args.kwargs['reply_markup']
        assert state.data['video_model_family'] == 'all'
        assert state.data['video_model_page'] == page
        assert any(button.text == '• Все'
                   for row in markup.inline_keyboard for button in row)
        seen.update(button.callback_data for button in model_buttons(markup))
        following = [button.callback_data for row in markup.inline_keyboard
                     for button in row if button.text == 'Далее ›']
        assert bool(following) == (page < 3)
        if following:
            next_page = following[0]

    assert seen == {
        'advanced_v_model_v3_std', 'advanced_v_model_v3_pro',
        'advanced_v_model_v3_4k', 'advanced_v_model_v26_pro',
        'advanced_v_model_motion_control_v26', 'advanced_v_model_motion_control_v30',
        'advanced_v_model_glow', 'advanced_v_model_avatar_std', 'advanced_v_model_avatar_pro',
        'v_model_seedance_2_5', 'advanced_v_model_seedance_2',
        'advanced_v_model_grok_imagine', 'advanced_v_model_grok_imagine_v15',
        'advanced_v_model_veo3', 'advanced_v_model_veo3_fast', 'advanced_v_model_veo3_lite',
        'advanced_v_model_gemini_omni_video', 'advanced_v_model_gemini_omni_audio',
        'advanced_v_model_gemini_omni_character', 'v_model_wan_3_prime',
    }
    back = callback('video_models:all:2')
    await video.show_video_models_page(back, state)
    assert state.data['video_model_page'] == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(('family', 'expected'), [
    ('wan', ['v_model_wan_3_prime']),
    ('kling', ['advanced_v_model_v3_std', 'advanced_v_model_v3_pro',
               'advanced_v_model_v3_4k', 'advanced_v_model_v26_pro']),
    ('motion', ['advanced_v_model_motion_control_v26', 'advanced_v_model_motion_control_v30',
                'advanced_v_model_glow', 'advanced_v_model_avatar_std', 'advanced_v_model_avatar_pro']),
    ('seedance', ['v_model_seedance_2_5', 'advanced_v_model_seedance_2']),
    ('grok', ['advanced_v_model_grok_imagine', 'advanced_v_model_grok_imagine_v15']),
    ('veo', ['advanced_v_model_veo3', 'advanced_v_model_veo3_fast', 'advanced_v_model_veo3_lite']),
    ('gemini', ['advanced_v_model_gemini_omni_video', 'advanced_v_model_gemini_omni_audio',
                'advanced_v_model_gemini_omni_character']),
])
async def test_family_tabs_remain_selectable_from_new_video_entry(family, expected):
    state = State()
    await video.show_complete_video_model_selection(callback('create_video_new'), state)
    event = callback(f'video_models:{family}:0')
    await video.show_video_models_page(event, state)
    markup = event.message.edit_text.call_args.kwargs['reply_markup']
    assert [button.callback_data for button in model_buttons(markup)] == expected
    assert state.data['video_model_family'] == family
    assert state.data['video_model_page'] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('model', ['veo3', 'wan_3_prime', 'grok_imagine', 'seedance_2_5'])
@pytest.mark.parametrize('navigation', [{}, {'video_model_family': 'all', 'video_model_page': 2}])
async def test_change_model_preserves_existing_generation_and_catalog_navigation(model, navigation):
    event, state = callback('video_change_model'), State()
    original = {
        'v_model': model, 'v_type': 'video', 'v_duration': 10,
        'user_prompt': 'Existing trend or repeat prompt',
        'reference_images': ['https://example.invalid/reference.png'],
        'repeat_source_task_id': 'source-task',
        **navigation,
    }
    state.data.update(original)

    await video.show_complete_video_model_selection(event, state)

    assert state.data.items() >= original.items()
    assert state.data['video_model_family'] == navigation.get('video_model_family', 'all')
    assert state.data['video_model_page'] == navigation.get('video_model_page', 0)
    assert state.data['video_flow_step'] == 'select_model'
