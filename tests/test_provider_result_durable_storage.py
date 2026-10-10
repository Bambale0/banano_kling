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


def test_legacy_local_result_url_is_rebased_to_canonical_media_origin(monkeypatch):
    monkeypatch.setattr(
        main_module.config,
        "STATIC_BASE_URL",
        "https://tanyapp.xn--e1aikcel5c5a.online",
    )
    for host in ("tanyapi.chillcreative.ru", "media.chillcreative.ru"):
        legacy_url = f"https://{host}/uploads/feed/legacy.png"
        result = asyncio.run(
            main_module._persist_result_url_if_needed(legacy_url, task_type="image")
        )
        assert result == "https://tanyapp.xn--e1aikcel5c5a.online/uploads/feed/legacy.png"



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


def test_explicit_media_maintenance_runs_bounded_rendergrid_reconciliation():
    deploy_script = (
        Path(__file__).resolve().parents[1] / "scripts" / "deploy_backend_docker.sh"
    ).read_text(encoding="utf-8")
    deploy = deploy_script.split("\ndeploy() {", 1)[1].split("\nstatus() {", 1)[0]
    maintenance = deploy_script.split("\nmaintenance_media() {", 1)[1].split(
        "\nrollback_to_systemd() {", 1
    )[0]
    reconcile = deploy_script.split("\nreconcile_rendergrid_legacy_images() {", 1)[
        1
    ].split("\n# Historical media rewrites", 1)[0]
    backup = deploy_script.split("\nbackup_database() {", 1)[1].split(
        "\ncontainer_health() {", 1
    )[0]

    assert "reconcile_rendergrid_legacy_images" not in deploy
    assert '[ "${ALLOW_MEDIA_MAINTENANCE:-0}" = "1" ]' in maintenance
    assert '[ "$SKIP_BACKUP" != "1" ]' in maintenance
    assert maintenance.index("wait_for_health") < maintenance.index(
        "backup_database"
    ) < maintenance.index("reconcile_rendergrid_legacy_images")
    assert backup.index('require_disk_space "$backup_root"') < backup.index(
        'DB_BACKUP_DIR="$backup_dir" SEND_BACKUP_TO_ADMINS=0'
    )
    assert "${RENDERGRID_DEPLOY_BACKFILL_LIMIT:-50}" in reconcile
    assert "${RENDERGRID_DEPLOY_BACKFILL_CONCURRENCY:-4}" in reconcile
    assert "${RENDERGRID_DEPLOY_BACKFILL_MAX_BATCHES:-1}" in reconcile
    assert "RENDERGRID_IMAGE_BACKFILL_CHECKPOINT_PATH" in reconcile
    assert "/app/data/rendergrid-image-backfill-checkpoint.json" in reconcile
    assert "scripts.backfill_rendergrid_image_results" in reconcile
    assert "maintenance failed" in reconcile
    assert "return 1" in reconcile


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


def test_kie_ephemeral_video_result_is_durable_even_when_global_persist_is_off(monkeypatch):
    from bot import database

    external_url = "https://tempfile.aiquickdraw.com/video/result.mp4"
    durable_url = f"{config.static_base_url.rstrip('/')}/uploads/feed/result.mp4"
    persist_mock = AsyncMock(return_value=[durable_url])

    monkeypatch.setattr(main_module.config, "PERSIST_PROVIDER_RESULTS", False)
    monkeypatch.setattr(
        database,
        "FEED_EPHEMERAL_RESULT_HOSTS",
        {"tempfile.aiquickdraw.com"},
    )
    monkeypatch.setattr(feed_persist, "persist_feed_result_urls", persist_mock)

    result = asyncio.run(
        main_module._persist_result_url_if_needed(external_url, task_type="video")
    )

    assert result == durable_url
    persist_mock.assert_awaited_once_with([external_url], require_local=True)


def test_kie_ephemeral_result_retries_localization_before_using_provider_url(monkeypatch):
    from bot import database

    external_url = "https://tempfile.aiquickdraw.com/video/retry.mp4"
    durable_url = f"{config.static_base_url.rstrip('/')}/uploads/feed/retry.mp4"
    persist_mock = AsyncMock(side_effect=[[], [durable_url]])

    monkeypatch.setattr(main_module.config, "PERSIST_PROVIDER_RESULTS", False)
    monkeypatch.setattr(
        database,
        "FEED_EPHEMERAL_RESULT_HOSTS",
        {"tempfile.aiquickdraw.com"},
    )
    monkeypatch.setattr(main_module, "EPHEMERAL_RESULT_PERSIST_ATTEMPTS", 2)
    monkeypatch.setattr(
        main_module,
        "EPHEMERAL_RESULT_PERSIST_RETRY_DELAY_SECONDS",
        0,
    )
    monkeypatch.setattr(feed_persist, "persist_feed_result_urls", persist_mock)

    result = asyncio.run(
        main_module._persist_result_url_if_needed(external_url, task_type="video")
    )

    assert result == durable_url
    assert persist_mock.await_count == 2
