"""WAN publishers must prepare media after committing the public row and recipe."""

from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from bot import database
from bot.services import trend_catalog_live_video as live
from bot.services import trend_catalog_publish_thumbnail as posters
from bot.services import wan3_prime_trends as trends
from bot.services.wan3_prime_lifecycle import Wan3PrimeActor, Wan3PrimeLifecycle
from tests.test_wan3_manual_trends import setup_publication
from tests.test_wan3_prime_lifecycle import (
    Downloader,
    Prices,
    Probe,
    Provider,
    body,
    user_actor,
)


def media_spies(monkeypatch):
    async def committed_poster(prompt):
        # A separate connection must see BOTH records: no FFmpeg/S3 under the
        # storage transaction, and no orphan public row before recipe commit.
        stored = await database.get_prompt_by_id(prompt['id'])
        assert stored['preview_url'] == prompt['preview_url']
        async with database.db_backend.connect(database.DATABASE_PATH) as db:
            recipe = await (await db.execute(
                'SELECT trend_id FROM wan3_prime_trend_recipes WHERE trend_id = ?',
                (prompt['id'],),
            )).fetchone()
        assert recipe and prompt['status'] == 'approved' and prompt['is_public']
        assert 'trend' in prompt['tags']
        return True

    poster = AsyncMock(side_effect=committed_poster)
    schedule = Mock(return_value=True)
    monkeypatch.setattr(posters, 'ensure_published_trend_poster', poster)
    monkeypatch.setattr(live, 'schedule_published_live_preview', schedule)
    return poster, schedule


@pytest.mark.asyncio
@pytest.mark.parametrize('model', ['wan_3', 'wan_3_prime'])
async def test_manual_publish_prepares_media_after_commit(monkeypatch, tmp_path, model):
    actor, kwargs = await setup_publication(monkeypatch, tmp_path, model)
    poster, schedule = media_spies(monkeypatch)
    result = await trends.publish_manual_trend(actor, **kwargs)
    poster.assert_awaited_once()
    assert poster.call_args.args[0]['id'] == result['trend_id']
    schedule.assert_called_once_with(poster.call_args.args[0])
    assert (await trends.publish_manual_trend(actor, **kwargs))['replayed']
    # Replayed/hidden publications retain their existing idempotent semantics.
    await database.deactivate_prompt(result['trend_id'], author_id=actor.user_id)
    assert (await trends.publish_manual_trend(actor, **kwargs))['replayed']
    assert poster.await_count == schedule.call_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('poster_ready', [True, False])
async def test_generated_publish_prepares_media_without_undoing_publication(
    monkeypatch, tmp_path, poster_ready,
):
    monkeypatch.chdir(tmp_path)
    owner = await user_actor(100, telegram_id=7111)
    actor = Wan3PrimeActor(owner.user_id, owner.telegram_id, is_admin=True)
    lifecycle = Wan3PrimeLifecycle(
        probe=Probe(file_duration=5), preset_manager=Prices(), transport=Provider(),
        downloader=Downloader(Path('static/uploads/wan3_prime/results/trend.mp4')),
    )
    recipe = body(scenario='reference', reference_image_urls=['https://owned.test/author.png'])
    quote = await lifecycle.quote(actor, recipe)
    source = await lifecycle.launch(actor, recipe, quote, 'media-publication')
    await database.complete_video_task(source['task_id'], 'https://owned.test/preview.mp4')
    poster, schedule = media_spies(monkeypatch)
    if not poster_ready:
        poster.side_effect = None
        poster.return_value = False  # Existing bounded helper handles S3 outages.
    result = await trends.publish_trend(
        actor, task_id=source['task_id'], title='Public video', description='',
        replacement_keys=['image:0'],
    )
    poster.assert_awaited_once()
    schedule.assert_called_once_with(poster.call_args.args[0])
    prompt = await database.get_prompt_by_id(result['trend_id'], approved_public_only=True)
    assert prompt['preview_url'] == 'https://owned.test/preview.mp4'
    assert (await trends.get_trend_plan(actor, result['trend_id']))['recipe']['model'] == 'wan_3_prime'
