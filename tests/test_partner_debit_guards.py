"""Accepted-generation bonuses must never mask a lost balance/debit race."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
@pytest.mark.parametrize('route', ['image', 'remix', 'motion'])
async def test_miniapp_lost_debit_race_never_submits_or_refunds(monkeypatch, route):
    from bot import miniapp
    from bot.services.kling_service import kling_service

    user = SimpleNamespace(id=810, telegram_id=81001, credits=1000)
    payload = {'init_data': 'signed', 'prompt': 'A sunset over a forest', 'img_service': 'banana_pro',
               'img_quality': '2K', 'gen_id': 42, 'motion_image_url': 'https://example.test/i.jpg',
               'motion_video_url': 'https://example.test/v.mp4'}
    request = SimpleNamespace(app={}, json=AsyncMock(return_value=payload))
    monkeypatch.setattr(miniapp, '_miniapp_payload', AsyncMock(return_value=payload))
    monkeypatch.setattr(miniapp, '_get_user_context', AsyncMock(return_value=(user.telegram_id, {'user': user})))
    monkeypatch.setattr(miniapp.config, 'is_admin', lambda _: False)
    monkeypatch.setattr(miniapp, 'check_can_afford', AsyncMock(return_value=True))
    debit, refund = AsyncMock(return_value=False), AsyncMock()
    monkeypatch.setattr(miniapp, 'deduct_credits', debit)
    monkeypatch.setattr(miniapp, 'add_credits', refund)
    monkeypatch.setattr(miniapp, 'touch_saved_references', AsyncMock())
    monkeypatch.setattr(miniapp, 'missing_local_upload_sources', lambda _: [])
    image_launch, motion_launch = AsyncMock(), AsyncMock()
    monkeypatch.setattr(miniapp, '_start_image_generation_task_lazy', image_launch)
    monkeypatch.setattr(kling_service, 'generate_motion_control', motion_launch)
    if route == 'remix':
        source = {'id': 42, 'gen_type': 'image', 'is_mine': True, 'model': 'banana_pro', 'prompt': payload['prompt'],
                  'aspect_ratio': '1:1', 'result_url': 'https://example.test/source.png', 'reference_images': []}
        monkeypatch.setattr(miniapp, '_get_feed_remix_source_card', AsyncMock(return_value=source))
        monkeypatch.setattr(miniapp, 'get_generation_task_payload', AsyncMock(return_value={'prompt': payload['prompt'], 'request_data': '{}'}))
        response = await miniapp.miniapp_feed_remix(request)
    elif route == 'motion':
        response = await miniapp.miniapp_generate_motion(request)
    else:
        response = await miniapp.miniapp_generate_image(request)
    assert response.status == 400
    debit.assert_awaited_once()
    image_launch.assert_not_awaited()
    motion_launch.assert_not_awaited()
    refund.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('route', ['image', 'video', 'veo_extend'])
async def test_telegram_lost_debit_race_never_submits_or_refunds(monkeypatch, route):
    from bot.handlers import generation
    from bot.services.kling_service import kling_service
    from bot.services.veo_service import veo_service

    data = {'generation_type': 'image', 'img_service': 'banana_pro', 'v_type': 'text',
            'v_model': 'v3_std', 'veo_extend_task_id': 'existing-veo'}
    state = SimpleNamespace(get_data=AsyncMock(return_value=data), update_data=AsyncMock(), clear=AsyncMock())
    message = SimpleNamespace(from_user=SimpleNamespace(id=82001), text='A sunset over a forest', answer=AsyncMock())
    monkeypatch.setattr(generation, '_normalize_grok_video_state', AsyncMock(return_value=data))
    monkeypatch.setattr(generation.config, 'is_admin', lambda _: False)
    monkeypatch.setattr(generation, 'get_or_create_user', AsyncMock(return_value=SimpleNamespace(id=820, credits=1000)))
    monkeypatch.setattr(generation, 'check_can_afford', AsyncMock(return_value=True))
    debit, refund, image_launch, video_launch, extend = (AsyncMock(return_value=False), AsyncMock(), AsyncMock(), AsyncMock(), AsyncMock())
    monkeypatch.setattr(generation, 'deduct_credits', debit)
    monkeypatch.setattr(generation, 'add_credits', refund)
    monkeypatch.setattr(generation, '_start_image_generation_task', image_launch)
    monkeypatch.setattr(kling_service, 'generate_video', video_launch)
    monkeypatch.setattr(veo_service, 'extend_video', extend)
    if route == 'image':
        await generation.handle_image_prompt_text(message, state)
    elif route == 'video':
        await generation.run_no_preset_video_from_message(message, state, message.text)
    else:
        await generation.handle_veo_extend_prompt(message, state)
    debit.assert_awaited_once()
    refund.assert_not_awaited()
    image_launch.assert_not_awaited()
    video_launch.assert_not_awaited()
    extend.assert_not_awaited()


@pytest.mark.asyncio
async def test_telegram_seedance_lost_debit_never_submits_or_refunds(monkeypatch):
    from bot.handlers import seedance_25_public_release as public

    monkeypatch.setattr(public.config, 'is_admin', lambda _: False)
    monkeypatch.setattr(public, '_scenario_payload', lambda *_: {'duration': 5, 'ratio': '16:9', 'resolution': '720p', 'video_urls': []})
    monkeypatch.setattr(public, '_validate_public_payload', AsyncMock())
    monkeypatch.setattr(public.generation_module, 'check_can_afford', AsyncMock(return_value=True))
    debit, refund, provider = AsyncMock(return_value=False), AsyncMock(), AsyncMock()
    monkeypatch.setattr(public.generation_module, 'deduct_credits', debit)
    monkeypatch.setattr(public.generation_module, 'add_credits', refund)
    monkeypatch.setattr(public, '_launch_provider', provider)
    message = SimpleNamespace(from_user=SimpleNamespace(id=83001), answer=AsyncMock(return_value=SimpleNamespace(delete=AsyncMock())))
    state = SimpleNamespace(get_data=AsyncMock(return_value={}), clear=AsyncMock())
    await public._public_message_launch(message, state, 'A sunset')
    debit.assert_awaited_once()
    provider.assert_not_awaited()
    refund.assert_not_awaited()
