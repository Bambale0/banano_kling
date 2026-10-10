import json
from unittest.mock import AsyncMock

import pytest

from bot import database
from bot.services.wan3_prime_lifecycle import Wan3PrimeLifecycle
from tests.test_wan3_prime_lifecycle import (
    Prices,
    Probe,
    Provider,
    balance,
    body,
    user_actor,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("model", ["wan_3_prime", "wan_3"])
async def test_internal_replay_uses_the_wan_lifecycle_without_debit_or_kling(monkeypatch, model):
    from bot import internal_admin_operation_replay as replay
    from bot.services import wan3_prime_lifecycle as module
    from bot.services.kling_service import kling_service

    owner = await user_actor(100)
    provider = Provider()
    prices = Prices()
    prices.get_video_quality_costs = lambda _model: dict(prices.rates)
    lifecycle = Wan3PrimeLifecycle(probe=Probe(), preset_manager=prices, transport=provider)
    await lifecycle.init_schema()
    # The HTTP control-plane middleware normally initializes this PostgreSQL
    # ledger. The routing regression uses its read projection on isolated SQLite.
    async with database.db_backend.connect(database.DATABASE_PATH) as db:
        await db.execute("CREATE TABLE internal_admin_operation_events (operation_id INTEGER, amount INTEGER, event_type TEXT, status TEXT)")
        await db.commit()
    source_body = body(model=model, scenario='edit', prompt='Change wardrobe, preserve Video1 motion.', seed=0, audio=False,
                       reference_video_urls=['https://owned.test/source.mp4'])
    quote = await lifecycle.quote(owner, source_body)
    original = await lifecycle.launch(owner, source_body, quote, 'original')
    source = await database.get_generation_task_payload(original['task_id'])
    before = await balance(owner.user_id)
    monkeypatch.setattr(module, 'wan3_prime_lifecycle', lifecycle)
    kling = AsyncMock(side_effect=AssertionError('Wan must never reach Kling'))
    monkeypatch.setattr(kling_service, 'generate_video', kling)
    provider.create_result = {'success': True, 'task_id': 'provider_replayed'}
    child = await replay._replay_video(source, admin_user_id='control-room-admin', request_id='test-request',
        idempotency_key='stable-admin-replay', reason='operator approved replay', comment=None)
    assert child['task_id'].startswith('wan3_')
    assert child['model'] == model
    assert child['action_type'] == 'admin_replay'
    assert int(child['parent_generation_id']) == source['id']
    assert await balance(owner.user_id) == before
    assert provider.recipe.seed == 0 and provider.recipe.audio is False
    assert provider.recipe.reference_video_urls == source_body['reference_video_urls']
    metadata = json.loads(child['request_data'])
    assert metadata['partner_invite_eligible'] is False
    assert metadata['admin_replay']['admin_user_id'] == 'control-room-admin'
    replayed = await replay._replay_video(source, admin_user_id='control-room-admin', request_id='retry-request',
        idempotency_key='stable-admin-replay', reason='operator approved replay', comment=None)
    assert replayed['task_id'] == child['task_id']
    assert provider.creates == 2  # original plus one explicitly authorized replay
    kling.assert_not_called()
