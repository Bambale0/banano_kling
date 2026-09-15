import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import bot.main as main_module
from bot.config import config
from bot.services import feed_persist
from scripts import backfill_rendergrid_image_results as backfill


def test_rendergrid_image_result_is_durable_even_when_global_persist_is_off(monkeypatch):
    external_url = "https://cdn.rendergrid.io/images/2026/09/15/result.png"
    durable_url = f"{config.static_base_url.rstrip('/')}/uploads/feed/result.png"
    persist_mock = AsyncMock(return_value=[durable_url])

    monkeypatch.setattr(main_module.config, "PERSIST_PROVIDER_RESULTS", False)
    monkeypatch.setattr(feed_persist, "persist_feed_result_urls", persist_mock)

    result = asyncio.run(
        main_module._persist_result_url_if_needed(external_url, task_type="image")
    )

    assert result == durable_url
    persist_mock.assert_awaited_once_with([external_url], require_local=True)


def test_non_durable_image_host_respects_global_persist_flag(monkeypatch):
    external_url = "https://example.com/result.png"
    persist_mock = AsyncMock(return_value=[])

    monkeypatch.setattr(main_module.config, "PERSIST_PROVIDER_RESULTS", False)
    monkeypatch.setattr(feed_persist, "persist_feed_result_urls", persist_mock)

    result = asyncio.run(
        main_module._persist_result_url_if_needed(external_url, task_type="image")
    )

    assert result == external_url
    persist_mock.assert_not_awaited()



def test_rendergrid_backfill_detects_only_provider_result_host():
    assert backfill._is_rendergrid_result_url(
        "https://cdn.rendergrid.io/images/2026/09/15/result.png"
    )
    assert not backfill._is_rendergrid_result_url(
        "https://example.com/images/result.png"
    )


def test_rendergrid_backfill_rewrites_result_urls_without_losing_extras():
    old_url = "https://cdn.rendergrid.io/images/old.png"
    extra_url = "https://example.com/extra.png"
    durable_url = "https://tanyapi.chillcreative.ru/uploads/feed/durable.png"

    result = backfill._replace_result_url_list(
        f'["{old_url}", "{extra_url}", "{old_url}"]',
        old_url=old_url,
        new_url=durable_url,
    )

    assert result == f'["{durable_url}", "{extra_url}"]'


def test_rendergrid_backfill_cursor_progresses_past_failed_rows(monkeypatch, tmp_path):
    from bot import database

    monkeypatch.setattr(backfill, "DATABASE_PATH", database.DATABASE_PATH)

    async def run():
        user = await database.get_or_create_user(880004)
        ids = []
        for idx in range(3):
            task_id = f"cursor-rg-{idx}"
            await database.add_generation_task(
                user.id,
                user.telegram_id,
                task_id,
                "image",
                "banana_pro",
                model="banana_pro",
                aspect_ratio="1:1",
                prompt="cursor",
                cost=2,
            )
            await database.complete_video_task(
                task_id,
                f"https://cdn.rendergrid.io/images/{task_id}.png",
            )
            task = await database.get_task_by_id(task_id)
            ids.append(task.id)

        newest_id = max(ids)

        async def fake_localize(row):
            row_id = int(row["id"])
            old_url = str(row["result_url"])
            if row_id == newest_id:
                return row_id, old_url, None
            return row_id, old_url, f"https://tanyapi.chillcreative.ru/uploads/feed/{row_id}.png"

        monkeypatch.setattr(backfill, "_localize_row", fake_localize)

        first = await backfill.backfill_rendergrid_image_results(
            limit=2,
            concurrency=1,
        )
        assert first["scanned"] == 2
        assert first["failed"] == 1
        assert first["updated"] == 1
        assert first["next_before_id"] == sorted(ids, reverse=True)[1]

        second = await backfill.backfill_rendergrid_image_results(
            limit=2,
            concurrency=1,
            before_id=first["next_before_id"],
        )
        assert second["scanned"] == 1
        assert second["updated"] == 1
        assert second["failed"] == 0
        assert second["exhausted"] is True

    asyncio.run(run())


def test_rendergrid_completed_localized_result_is_canonical_in_database(monkeypatch):
    from bot import database

    external_url = "https://cdn.rendergrid.io/images/completed-db.png"
    durable_url = "https://tanyapi.chillcreative.ru/uploads/feed/completed-db.png"
    persist_mock = AsyncMock(return_value=[durable_url])

    monkeypatch.setattr(main_module.config, "PERSIST_PROVIDER_RESULTS", False)
    monkeypatch.setattr(feed_persist, "persist_feed_result_urls", persist_mock)

    async def run():
        user = await database.get_or_create_user(880007)
        await database.add_generation_task(
            user.id,
            user.telegram_id,
            "rendergrid-completed-db",
            "image",
            "banana_pro",
            model="banana_pro",
            aspect_ratio="1:1",
            prompt="persist me",
            cost=2,
        )
        persisted = await main_module._persist_result_url_if_needed(
            external_url,
            task_type="image",
        )
        assert persisted == durable_url
        assert await database.complete_video_task(
            "rendergrid-completed-db",
            persisted,
        )
        task = await database.get_task_by_id("rendergrid-completed-db")
        assert task.status == "completed"
        assert task.result_url == durable_url
        assert "cdn.rendergrid.io" not in task.result_url

    asyncio.run(run())


def test_production_deploy_runs_bounded_rendergrid_reconciliation():
    deploy_script = (
        Path(__file__).resolve().parents[1] / "scripts" / "deploy_backend_docker.sh"
    ).read_text(encoding="utf-8")

    assert "reconcile_rendergrid_legacy_images" in deploy_script
    assert "RENDERGRID_DEPLOY_BACKFILL_LIMIT" in deploy_script
    assert "RENDERGRID_DEPLOY_BACKFILL_CONCURRENCY" in deploy_script
    assert "RENDERGRID_DEPLOY_BACKFILL_MAX_BATCHES" in deploy_script
    assert "RENDERGRID_IMAGE_BACKFILL_CHECKPOINT_PATH" in deploy_script
    assert "/app/data/rendergrid-image-backfill-checkpoint.json" in deploy_script
    assert "scripts.backfill_rendergrid_image_results" in deploy_script
    assert "deployment continues with TTL/media_unavailable safeguards" in deploy_script


def test_rendergrid_backfill_checkpoint_persists_cursor_and_resets_after_full_pass(tmp_path):
    checkpoint = tmp_path / "rendergrid-checkpoint.json"

    backfill._save_checkpoint(str(checkpoint), 4321, exhausted=False)
    assert backfill._load_checkpoint(str(checkpoint)) == 4321

    payload = checkpoint.read_text(encoding="utf-8")
    assert '"next_before_id": 4321' in payload
    assert '"last_pass_exhausted": false' in payload

    backfill._save_checkpoint(str(checkpoint), 1234, exhausted=True)
    assert backfill._load_checkpoint(str(checkpoint)) is None

    payload = checkpoint.read_text(encoding="utf-8")
    assert '"next_before_id": null' in payload
    assert '"last_pass_exhausted": true' in payload
