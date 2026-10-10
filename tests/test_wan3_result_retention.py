from pathlib import Path

import pytest

from bot import database
from bot.services.wan3_prime_lifecycle import Wan3PrimeLifecycle
from bot.services.wan3_prime_media import Wan3PrimeValidationError
from bot.services.wan3_prime_storage import wan3_prime_storage
from tests.test_wan3_prime_lifecycle import (
    Downloader,
    Prices,
    Probe,
    Provider,
    balance,
    body,
    user_actor,
)


@pytest.mark.asyncio
async def test_expired_private_delivered_result_is_removed_but_public_and_undelivered_stay(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('WAN3_RESULT_RETENTION_SECONDS', '3600')
    actor = await user_actor(100)
    task_ids = []
    paths = []
    for index in range(3):
        provider = Provider()
        provider.create_result = {'success': True, 'task_id': f'provider_{index}'}
        path = Path(f'static/uploads/wan3_prime/results/file-{index}.mp4')
        lifecycle = Wan3PrimeLifecycle(probe=Probe(file_duration=5), preset_manager=Prices(), transport=provider, downloader=Downloader(path))
        quote = await lifecycle.quote(actor, body())
        launched = await lifecycle.launch(actor, body(), quote, f'retention-{index}')
        provider.statuses[f'provider_{index}'] = {'taskId': f'provider_{index}', 'state': 'success', 'resultUrls': ['https://owned.test/out.mp4']}
        await lifecycle.reconcile_once(provider_task_id=f'provider_{index}')
        task_ids.append(launched['task_id'])
        paths.append(path)
    async with database.db_backend.connect(database.DATABASE_PATH) as db:
        await db.execute("UPDATE generation_tasks SET completed_at = '2000-01-01'")
        for task_id in task_ids[:2]:
            await db.execute("UPDATE wan3_prime_intents SET delivery_status = 'delivered' WHERE internal_task_id = ?", (task_id,))
        await db.execute('UPDATE generation_tasks SET is_public_feed = 1 WHERE task_id = ?', (task_ids[1],))
        await db.commit()
    for _ in range(4):
        await wan3_prime_storage.cleanup_expired(limit=1)
    assert not paths[0].exists()
    assert paths[1].exists() and paths[2].exists()
    original = await database.get_task_by_id(task_ids[0])
    assert original.status == 'completed' and original.cost == 10


@pytest.mark.asyncio
async def test_result_capacity_limit_precedes_debit_and_provider_call(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('WAN3_RESULT_GLOBAL_QUOTA_BYTES', '1')
    actor = await user_actor(100)
    provider = Provider()
    lifecycle = Wan3PrimeLifecycle(probe=Probe(), preset_manager=Prices(), transport=provider)
    quote = await lifecycle.quote(actor, body())
    with pytest.raises(Wan3PrimeValidationError) as error:
        await lifecycle.launch(actor, body(), quote, 'no-result-capacity')
    assert error.value.status == 503
    assert provider.creates == 0 and await balance(actor.user_id) == 100
