"""Promo acceptance tests against an explicitly isolated PostgreSQL database."""
import asyncio
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict

from bot import db as db_backend
from bot import internal_admin_notification_schema as schema
from bot import notification_service as worker
from bot import promo_campaigns as promos
from bot.config import config
from bot.postgres_pool import close_postgres_pool
from tests.test_partner_approval_postgres import (
    _bootstrap_production_like_partner_schema,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("PROMO_POSTGRES_TEST") != "1",
    reason="requires dedicated ephemeral promo PostgreSQL database",
)
ADMIN = 999999999
OTHER_ADMIN = 999999998


@pytest.fixture(autouse=True)
async def promo_database(isolated_database, monkeypatch):
    if os.environ.get("PROMO_POSTGRES_TEST") != "1":
        yield
        return
    dsn = os.environ["DATABASE_URL"]
    params = conninfo_to_dict(dsn)
    assert params["dbname"] in {"promo_test", "banano_promo_test"}
    assert params.get("host") in {"127.0.0.1", "localhost"}
    assert db_backend.is_postgres()
    await close_postgres_pool()
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        await conn.execute("DROP TABLE IF EXISTS notification_test_sends, notification_deliveries, notification_campaigns, user_prompts, users CASCADE")
        await conn.commit()
    await _bootstrap_production_like_partner_schema()
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        await conn.execute('ALTER TABLE generation_tasks ADD COLUMN IF NOT EXISTS user_id BIGINT')
        for column in ('title TEXT', 'tags TEXT', 'is_public BOOLEAN'):
            await conn.execute(f'ALTER TABLE user_prompts ADD COLUMN IF NOT EXISTS {column}')
        await conn.execute(
            "INSERT INTO users(telegram_id) VALUES(%s),(%s),(%s)", (ADMIN, OTHER_ADMIN, 1001)
        )
        await conn.execute("""
            INSERT INTO user_prompts (id,title,preview_url,tags,status,is_public) VALUES
            (184,'Танец на парковке','preview-a','["trend"]','approved',TRUE),
            (196,'Осенний образ','preview-b','["trend","trend-video"]','approved',TRUE),
            (197,'Черновик','preview-c','["trend"]','pending',TRUE),
            (198,'Скрыт','preview-d','["trend"]','approved',FALSE),
            (199,'Обычный промпт','preview-e','[]','approved',TRUE)
        """)
        await conn.commit()
    schema._SCHEMA_READY = False
    schema._SCHEMA_LOCK = None
    monkeypatch.setattr(config, "ADMIN_IDS_STR", f"{ADMIN},{OTHER_ADMIN}")
    monkeypatch.setattr(worker, "ensure_notification_campaign_worker", lambda bot: None)
    await schema.ensure_internal_admin_notification_schema()
    yield
    await close_postgres_pool()


def payload(buttons=2, album=True):
    return {
        "schema_version": 2, "text": "<b>Новый тренд</b>", "parse_mode": "HTML",
        "media": ([{"type": "video", "file_id": "video_A"},
                   {"type": "video", "file_id": "video_B"}] if album else []),
        "buttons": [
            {"position": i+1, "text": f"Повторить {i+1}", "action": "trend", "trend_id": trend}
            for i, trend in enumerate([184, 196][:buttons])
        ],
    }


def fake_bot():
    count = 100
    async def send(**kwargs):
        nonlocal count
        count += 1
        return SimpleNamespace(message_id=count)
    return SimpleNamespace(
        get_me=AsyncMock(return_value=SimpleNamespace(username="TestPromoBot")),
        send_media_group=AsyncMock(return_value=[SimpleNamespace(message_id=91), SimpleNamespace(message_id=92)]),
        send_message=AsyncMock(side_effect=send),
        send_photo=AsyncMock(side_effect=send),
        send_video=AsyncMock(side_effect=send),
    )


async def draft(message=None):
    item = await promos.create_promo(ADMIN)
    return await promos.save_promo(item["id"], ADMIN, message or payload(), item["revision"])


async def _test_and_deliver(item, bot):
    await promos.test_promo(item["id"], ADMIN, bot, item["revision"], "test-run-1")
    claimed = await worker._claim_test_delivery()
    assert claimed is not None
    await worker.process_delivery(bot, claimed)
    await promos.refresh_test_state(item["id"], claimed["content_hash"])
    return await promos.get_promo(item["id"], ADMIN)


@pytest.mark.asyncio
async def test_migration_repeated_and_server_paginated_search():
    schema._SCHEMA_READY = False
    await schema.ensure_internal_admin_notification_schema()
    page = await promos.search_trends("", size=1)
    assert [item["id"] for item in page["items"]] == [196]
    assert page["has_more"]
    assert [item["id"] for item in (await promos.search_trends("", page=1, size=1))["items"]] == [184]
    assert [item["id"] for item in (await promos.search_trends("184"))["items"]] == [184]
    assert [item["id"] for item in (await promos.search_trends("осен"))["items"]] == [196]
    assert (await promos.search_trends("%"))["items"] == []


@pytest.mark.asyncio
async def test_draft_requires_test_and_test_delivery_uses_same_snapshot_as_mass_send():
    bot = fake_bot()
    item = await draft()
    with pytest.raises(promos.PromoError, match="после теста"):
        await promos.start_promo(item["id"], ADMIN, bot, item["revision"], item["content_hash"], 3)
    tested = await _test_and_deliver(item, bot)
    assert tested["ready"], tested["test_summary"]
    assert tested["test_summary"]["sent"] == 1
    assert len(bot.send_media_group.await_args.kwargs["media"]) == 2
    test_keyboard = bot.send_message.await_args.kwargs["reply_markup"]
    launched = await promos.start_promo(
        item["id"], ADMIN, bot, item["revision"], tested["content_hash"], 3
    )
    assert launched["status"] == "running"
    delivery = await worker._claim_delivery()
    await worker.process_delivery(bot, delivery)
    await worker._refresh_campaign(item["id"])
    assert bot.send_message.await_args.kwargs["reply_markup"] == test_keyboard
    actual = await promos.get_promo(item["id"], ADMIN)
    assert actual["sent_count"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["text", "parse_mode", "media", "button_text", "trend_id", "buttons"])
async def test_edit_invalidates_admin_test(field):
    bot = fake_bot()
    item = await draft()
    tested = await _test_and_deliver(item, bot)
    message = tested["message"]
    if field == "text":
        message["text"] = "Изменено"
    elif field == "parse_mode":
        message["parse_mode"] = None
    elif field == "media":
        message["media"].reverse()
    elif field == "button_text":
        message["buttons"][0]["text"] = "Новая кнопка"
    elif field == "trend_id":
        message["buttons"][0]["trend_id"] = 196
    else:
        message["buttons"] = []
    edited = await promos.save_promo(item["id"], ADMIN, message, tested["revision"])
    assert not edited["ready"]
    with pytest.raises(promos.PromoError):
        await promos.start_promo(item["id"], ADMIN, bot, edited["revision"], tested["content_hash"], 3)


@pytest.mark.asyncio
async def test_double_launch_and_concurrent_edit_are_atomic():
    bot = fake_bot()
    item = await draft()
    tested = await _test_and_deliver(item, bot)
    left, right = await asyncio.gather(*[
        promos.start_promo(item["id"], ADMIN, bot, item["revision"], tested["content_hash"], 3)
        for _ in range(2)
    ])
    assert left["id"] == right["id"] == item["id"]
    async with db_backend.connect() as conn:
        conn.row_factory = db_backend.Row
        cur = await conn.execute("SELECT COUNT(*) AS n FROM notification_deliveries WHERE campaign_id = ?", (item["id"],))
        assert (await cur.fetchone())["n"] == 3
    with pytest.raises(promos.PromoError, match="уже запущена"):
        await promos.save_promo(item["id"], ADMIN, payload(), item["revision"])


@pytest.mark.asyncio
async def test_unavailable_trend_blocks_test_and_launch():
    bot = fake_bot()
    item = await draft()
    tested = await _test_and_deliver(item, bot)
    async with db_backend.connect() as conn:
        await conn.execute("UPDATE user_prompts SET status = 'deactivated' WHERE id = 184")
        await conn.commit()
    with pytest.raises(promos.PromoError, match="недоступен"):
        await promos.start_promo(item["id"], ADMIN, bot, item["revision"], tested["content_hash"], 3)
    with pytest.raises(promos.PromoError, match="недоступен"):
        await promos.test_promo(item["id"], ADMIN, bot, item["revision"], "again")


@pytest.mark.asyncio
async def test_bot_username_change_invalidates_test():
    bot = fake_bot()
    item = await draft()
    tested = await _test_and_deliver(item, bot)
    bot.get_me.return_value.username = "ChangedBot"
    with pytest.raises(promos.PromoError, match="после теста"):
        await promos.start_promo(item["id"], ADMIN, bot, item["revision"], tested["content_hash"], 3)


@pytest.mark.asyncio
async def test_audience_change_rolls_back_materialization():
    bot = fake_bot()
    item = await draft()
    tested = await _test_and_deliver(item, bot)
    with pytest.raises(promos.PromoError, match="Число получателей"):
        await promos.start_promo(item["id"], ADMIN, bot, item["revision"], tested["content_hash"], 2)
    async with db_backend.connect() as conn:
        conn.row_factory = db_backend.Row
        cur = await conn.execute("SELECT COUNT(*) AS n FROM notification_deliveries")
        assert (await cur.fetchone())["n"] == 0


@pytest.mark.asyncio
async def test_stale_success_cannot_unlock_edited_content():
    bot = fake_bot()
    item = await draft()
    test = await promos.test_promo(item["id"], ADMIN, bot, item["revision"], "once")
    new = payload()
    new["text"] = "Новый текст"
    edited = await promos.save_promo(item["id"], ADMIN, new, item["revision"])
    async with db_backend.connect() as conn:
        await conn.execute(
            "UPDATE notification_test_sends SET status = 'sent' WHERE campaign_id = ?", (item["id"],)
        )
        await conn.commit()
    await promos.refresh_test_state(item["id"], test["content_hash"])
    assert not (await promos.get_promo(item["id"], ADMIN))["ready"]
    assert edited["revision"] == item["revision"] + 1


@pytest.mark.asyncio
async def test_duplicate_keeps_content_but_not_send_authority():
    bot = fake_bot()
    item = await draft()
    tested = await _test_and_deliver(item, bot)
    copied = await promos.duplicate_promo(item["id"], ADMIN)
    assert copied["id"] != item["id"]
    assert copied["message"] == tested["message"]
    assert not copied["ready"]


@pytest.mark.asyncio
async def test_no_admin_delivery_keeps_mass_send_locked():
    bot = fake_bot()
    item = await draft(payload(buttons=0, album=False))
    bot.send_message.side_effect = TimeoutError()
    await promos.test_promo(item["id"], ADMIN, bot, item["revision"], "failed")
    for _ in range(2):
        task = await worker._claim_test_delivery()
        await worker.process_delivery(bot, task)
        await promos.refresh_test_state(item["id"], task["content_hash"])
    result = await promos.get_promo(item["id"], ADMIN)
    assert not result["ready"]
    assert result["test_summary"]["uncertain"] == 2


@pytest.mark.asyncio
async def test_authorization_and_stale_revision():
    with pytest.raises(promos.PromoError, match="Нет доступа"):
        await promos.create_promo(1001)
    item = await draft()
    with pytest.raises(promos.PromoError, match="актуальную"):
        await promos.save_promo(item["id"], ADMIN, payload(), item["revision"] - 1)


@pytest.mark.asyncio
async def test_test_double_click_creates_one_recipient_set():
    bot = fake_bot()
    item = await draft()
    await asyncio.gather(*[
        promos.test_promo(item["id"], ADMIN, bot, item["revision"], "same-click")
        for _ in range(2)
    ])
    async with db_backend.connect() as conn:
        conn.row_factory = db_backend.Row
        cur = await conn.execute("SELECT COUNT(*) AS n FROM notification_test_sends")
        assert (await cur.fetchone())["n"] == 2


@pytest.mark.asyncio
async def test_album_receipt_survives_worker_restart_before_text_retry():
    from aiogram.exceptions import TelegramRetryAfter
    from aiogram.methods import SendMessage

    bot = fake_bot()
    item = await draft()
    await promos.test_promo(item["id"], ADMIN, bot, item["revision"], "retry")
    task = await worker._claim_test_delivery()
    bot.send_message.side_effect = TelegramRetryAfter(
        method=SendMessage(chat_id=ADMIN, text="x"), message="retry", retry_after=1,
    )
    await worker.process_delivery(bot, task)
    async with db_backend.connect() as conn:
        conn.row_factory = db_backend.Row
        cur = await conn.execute(
            "SELECT status, delivery_parts FROM notification_test_sends WHERE id = ?", (task["id"],)
        )
        row = await cur.fetchone()
        assert row["status"] == "failed"
        parts = promos._decode(row["delivery_parts"], [])
        assert parts[0]["status"] == "sent"
        await conn.execute(
            "UPDATE notification_test_sends SET next_attempt_at = CURRENT_TIMESTAMP WHERE id = ?",
            (task["id"],),
        )
        await conn.commit()
    bot.send_message.side_effect = None
    bot.send_message.return_value = SimpleNamespace(message_id=200)
    resumed = await worker._claim_test_delivery()
    assert resumed["id"] == task["id"]
    await worker.process_delivery(bot, resumed)
    await promos.refresh_test_state(item["id"], resumed["content_hash"])
    assert bot.send_media_group.await_count == 1
    assert bot.send_message.await_count == 2
    assert (await promos.get_promo(item["id"], ADMIN))["ready"]


@pytest.mark.asyncio
async def test_lost_lease_fences_old_worker_before_network():
    bot = fake_bot()
    item = await draft()
    await promos.test_promo(item["id"], ADMIN, bot, item["revision"], "fence")
    task = await worker._claim_test_delivery()
    async with db_backend.connect() as conn:
        await conn.execute(
            "UPDATE notification_test_sends SET attempt_token = 'new-owner' WHERE id = ?", (task["id"],)
        )
        await conn.commit()
    await worker.process_delivery(bot, task)
    bot.send_media_group.assert_not_awaited()
    bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_crash_with_inflight_album_is_uncertain_not_resent():
    bot = fake_bot()
    item = await draft()
    await promos.test_promo(item["id"], ADMIN, bot, item["revision"], "crash")
    task = await worker._claim_test_delivery()
    async with db_backend.connect() as conn:
        await conn.execute(
            """UPDATE notification_test_sends SET
               delivery_parts = '[{"status":"sending","message_ids":[]}]'::jsonb,
               lease_until = CURRENT_TIMESTAMP - INTERVAL '1 second' WHERE id = ?""",
            (task["id"],),
        )
        await conn.commit()
    assert await worker._recover_expired_test_leases() == 1
    async with db_backend.connect() as conn:
        conn.row_factory = db_backend.Row
        cur = await conn.execute("SELECT status FROM notification_test_sends WHERE id = ?", (task["id"],))
        assert (await cur.fetchone())["status"] == "uncertain"
    next_task = await worker._claim_test_delivery()
    assert next_task is None or next_task["id"] != task["id"]
    bot.send_media_group.assert_not_awaited()


@pytest.mark.asyncio
async def test_concurrent_save_and_launch_never_send_untested_payload():
    bot = fake_bot()
    item = await draft()
    tested = await _test_and_deliver(item, bot)
    changed = payload()
    changed["text"] = "New version"
    results = await asyncio.gather(
        promos.save_promo(item["id"], ADMIN, changed, item["revision"]),
        promos.start_promo(item["id"], ADMIN, bot, item["revision"], tested["content_hash"], 3),
        return_exceptions=True,
    )
    assert sum(isinstance(result, promos.PromoError) for result in results) == 1
    final = await promos.get_promo(item["id"], ADMIN)
    if final["status"] == "running":
        assert final["message"]["text"] == "<b>Новый тренд</b>"
        assert final["message_snapshot"]["message"]["text"] == "<b>Новый тренд</b>"
    else:
        assert final["status"] == "draft" and not final["ready"]


@pytest.mark.asyncio
async def test_real_persistent_service_matches_editor_contract_without_live_sends(monkeypatch):
    from unittest.mock import Mock

    from bot import notification_service, promo_campaigns
    from bot.handlers import promo_admin
    from tests.test_promo_admin import (
        FakeState,
        action,
        callback,
        displayed_callbacks,
        incoming,
    )

    monkeypatch.setattr(promo_admin, "_service", lambda: promo_campaigns)
    worker = Mock()
    monkeypatch.setattr(notification_service, "ensure_notification_campaign_worker", worker)

    state, cb = FakeState(), callback()
    cb.bot = SimpleNamespace(get_me=AsyncMock(return_value=SimpleNamespace(username="promo_test_bot")))
    await promo_admin.open_promos(cb, state)
    cb.data = f"admin_pr:new:{state.data['promo_token']}"
    await promo_admin.promo_callback(cb, state)
    promo_id = state.data["promo_id"]
    cb.data = action(state, "text")
    await promo_admin.promo_callback(cb, state)
    await promo_admin.promo_message(incoming(text="<b>Промо</b>"), state)
    cb.data = action(state, "buttons")
    await promo_admin.promo_callback(cb, state)
    cb.data = action(state, "label", 0)
    await promo_admin.promo_callback(cb, state)
    await promo_admin.promo_message(incoming(1002, text="Попробовать"), state)
    await promo_admin.promo_message(incoming(1003, text="184"), state)
    cb.data = action(state, "pick", 0)
    await promo_admin.promo_callback(cb, state)
    saved = await promo_campaigns.get_promo(promo_id, 999999999)
    assert saved["message"]["buttons"] == [{"position": 1, "text": "Попробовать", "action": "trend", "trend_id": 184}]
    assert saved["message"]["text"] == "<b>Промо</b>"
    assert not saved["ready"]
    worker.assert_not_called()
    cb.data = action(state, "cancel")
    await promo_admin.promo_callback(cb, state)
    cb.data = action(state, "test")
    await promo_admin.promo_callback(cb, state)
    saved = await promo_campaigns.get_promo(promo_id, 999999999)
    assert saved["test_summary"]["status"] == "queued"
    assert saved["test_summary"]["pending"] == 2
    assert saved["status"] == "draft"
    worker.assert_called_once_with(cb.bot)
    assert not any(":confirm:" in item for item in displayed_callbacks(cb))


@pytest.mark.asyncio
async def test_edit_while_album_inflight_never_unlocks_new_version():
    bot = fake_bot()
    item = await draft()
    await promos.test_promo(item["id"], ADMIN, bot, item["revision"], "inflight-edit")
    claimed = await worker._claim_test_delivery()

    async def edit_during_send(**kwargs):
        changed = payload()
        changed["text"] = "Новое содержимое"
        await promos.save_promo(item["id"], ADMIN, changed, item["revision"])
        return [SimpleNamespace(message_id=1), SimpleNamespace(message_id=2)]

    bot.send_media_group.side_effect = edit_during_send
    await worker.process_delivery(bot, claimed)
    await promos.refresh_test_state(item["id"], claimed["content_hash"])
    updated = await promos.get_promo(item["id"], ADMIN)
    assert updated["message"]["text"] == "Новое содержимое"
    assert not updated["ready"]
    bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_removed_admin_does_not_strand_test_run(monkeypatch):
    bot = fake_bot()
    item = await draft()
    await promos.test_promo(item["id"], ADMIN, bot, item["revision"], "revoked")
    monkeypatch.setattr(config, "ADMIN_IDS_STR", str(ADMIN))
    await worker._cancel_obsolete_tests()
    claimed = await worker._claim_test_delivery()
    assert claimed["telegram_id"] == ADMIN
    await worker.process_delivery(bot, claimed)
    await promos.refresh_test_state(item["id"], claimed["content_hash"])
    result = await promos.get_promo(item["id"], ADMIN)
    assert result["ready"] and result["test_summary"]["pending"] == 0
    assert result["test_summary"]["status"] == "completed"


@pytest.mark.asyncio
async def test_all_admins_removed_prevents_any_queued_test_send(monkeypatch):
    bot = fake_bot()
    item = await draft()
    await promos.test_promo(item["id"], ADMIN, bot, item["revision"], "none")
    monkeypatch.setattr(config, "ADMIN_IDS_STR", "")
    await worker._cancel_obsolete_tests()
    assert await worker._claim_test_delivery() is None
    bot.send_media_group.assert_not_awaited()
    async with db_backend.connect() as conn:
        conn.row_factory = db_backend.Row
        cur = await conn.execute("SELECT tested_content_hash FROM notification_campaigns WHERE id = ?", (item["id"],))
        assert (await cur.fetchone())["tested_content_hash"] is None


@pytest.mark.asyncio
async def test_remaining_admin_test_finishes_after_mass_launch():
    bot = fake_bot()
    item = await draft()
    tested = await _test_and_deliver(item, bot)
    await promos.start_promo(item["id"], ADMIN, bot, item["revision"], tested["content_hash"], 3)
    await worker._cancel_obsolete_tests()
    remaining = await worker._claim_test_delivery()
    assert remaining is not None
    await worker.process_delivery(bot, remaining)
    await promos.refresh_test_state(item["id"], remaining["content_hash"])
    current = await promos.get_promo(item["id"], ADMIN)
    assert current["test_summary"]["sent"] == 2
    assert current["tested_content_hash"] == tested["tested_content_hash"]
    assert current["status"] == "running"


@pytest.mark.asyncio
async def test_trend_unpublication_waits_for_launch_commit(monkeypatch):
    bot = fake_bot()
    item = await draft()
    tested = await _test_and_deliver(item, bot)
    checked, release = asyncio.Event(), asyncio.Event()
    original = promos._check_trends

    async def pause_after_check(conn, message):
        result = await original(conn, message)
        checked.set()
        await release.wait()
        return result

    monkeypatch.setattr(promos, "_check_trends", pause_after_check)
    launch = asyncio.create_task(promos.start_promo(
        item["id"], ADMIN, bot, item["revision"], tested["content_hash"], 3
    ))
    await checked.wait()

    async def hide():
        async with db_backend.connect() as conn:
            await conn.execute("UPDATE user_prompts SET status = 'deactivated' WHERE id = 184")
            await conn.commit()

    hiding = asyncio.create_task(hide())
    try:
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(asyncio.shield(hiding), timeout=0.05)
    finally:
        release.set()
        result = await launch
        await hiding
    assert result["status"] == "running"
