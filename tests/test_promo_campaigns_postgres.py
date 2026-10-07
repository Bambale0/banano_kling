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
        await conn.execute("DROP TABLE IF EXISTS notification_promo_revisions, notification_test_sends, notification_deliveries, notification_campaigns, user_prompts, users CASCADE")
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


@pytest.fixture(params=["UTC", "Europe/London", "Asia/Kolkata"])
async def worker_clock(monkeypatch, request):
    """Exercise the actual pooled adapter, including a year-round UTC offset."""
    timezone = request.param
    monkeypatch.setenv("PGOPTIONS", f"-c timezone={timezone}")
    await close_postgres_pool()
    async with db_backend.connect() as conn:
        conn.row_factory = db_backend.Row
        cur = await conn.execute("SELECT current_setting('TimeZone') AS timezone")
        assert (await cur.fetchone())["timezone"] == timezone
    yield
    await close_postgres_pool()


async def _deadline_remaining(table, column, row_id):
    assert table in {"notification_test_sends", "notification_deliveries"}
    assert column in {"lease_until", "next_attempt_at"}
    async with db_backend.connect() as conn:
        conn.row_factory = db_backend.Row
        cur = await conn.execute(
            f"SELECT EXTRACT(EPOCH FROM ({column} - CURRENT_TIMESTAMP::timestamp)) AS remaining "
            f"FROM {table} WHERE id = ?", (row_id,),
        )
        return float((await cur.fetchone())["remaining"])


@pytest.mark.asyncio
async def test_admin_and_mass_delivery_leases_use_database_clock(worker_clock):
    bot = fake_bot()
    item = await draft()
    await promos.test_promo(item["id"], ADMIN, bot, item["revision"], "non-utc-clock")
    test_delivery = await worker._claim_test_delivery()
    assert test_delivery is not None
    assert 80 < await _deadline_remaining(
        "notification_test_sends", "lease_until", test_delivery["id"]
    ) <= worker.LEASE_SECONDS
    await worker.process_delivery(bot, test_delivery)
    await promos.refresh_test_state(item["id"], test_delivery["content_hash"])
    tested = await promos.get_promo(item["id"], ADMIN)
    assert tested["ready"], tested["test_summary"]
    assert bot.send_media_group.await_count == 1
    assert bot.send_message.await_count == 1

    await promos.start_promo(
        item["id"], ADMIN, bot, item["revision"], tested["content_hash"], 3
    )
    mass_delivery = await worker._claim_delivery()
    assert mass_delivery is not None
    assert 80 < await _deadline_remaining(
        "notification_deliveries", "lease_until", mass_delivery["id"]
    ) <= worker.LEASE_SECONDS
    await worker.process_delivery(bot, mass_delivery)
    await worker._refresh_campaign(item["id"])
    assert (await promos.get_promo(item["id"], ADMIN))["sent_count"] == 1
    assert bot.send_media_group.await_count == 2
    assert bot.send_message.await_count == 2


@pytest.mark.asyncio
async def test_retry_and_legacy_deadlines_use_database_clock(worker_clock):
    from aiogram.exceptions import TelegramRetryAfter
    from aiogram.methods import SendMessage

    bot = fake_bot()
    item = await draft()
    await promos.test_promo(item["id"], ADMIN, bot, item["revision"], "non-utc-retry")
    delivery = await worker._claim_test_delivery()
    bot.send_message.side_effect = TelegramRetryAfter(
        method=SendMessage(chat_id=ADMIN, text="test"), message="retry", retry_after=47,
    )
    await worker.process_delivery(bot, delivery)
    assert 45 < await _deadline_remaining(
        "notification_test_sends", "next_attempt_at", delivery["id"]
    ) <= 47
    async with db_backend.connect() as conn:
        conn.row_factory = db_backend.Row
        cur = await conn.execute(
            "SELECT status, delivery_parts FROM notification_test_sends WHERE id = ?",
            (delivery["id"],),
        )
        row = await cur.fetchone()
        assert row["status"] == "failed"
        assert promos._decode(row["delivery_parts"], [])[0]["status"] == "sent"
        cur = await conn.execute(
            "INSERT INTO notification_deliveries (campaign_id, telegram_id, status) "
            "VALUES (?, 1001, 'queued') RETURNING id", (item["id"],),
        )
        legacy_id = (await cur.fetchone())["id"]
        await conn.commit()
    await worker._mark_failed(legacy_id, 1, RuntimeError("definite rejection"))
    assert 3 < await _deadline_remaining(
        "notification_deliveries", "next_attempt_at", legacy_id
    ) <= 5


@pytest.mark.asyncio
async def test_fifth_inflight_admin_attempt_cannot_be_replaced():
    bot = fake_bot()
    item = await draft()
    queued = await promos.test_promo(item["id"], ADMIN, bot, item["revision"], "fifth-first")
    async with db_backend.connect() as conn:
        # The other admin already completed; the fifth attempt is still in flight.
        await conn.execute(
            "UPDATE notification_test_sends SET status = 'cancelled' WHERE campaign_id = ?",
            (item["id"],),
        )
        await conn.execute(
            """UPDATE notification_test_sends SET status = 'sending', attempts = 5,
               attempt_token = 'fifth-attempt', lease_until = CURRENT_TIMESTAMP + INTERVAL '60 seconds'
               WHERE campaign_id = ? AND telegram_id = ?""",
            (item["id"], ADMIN),
        )
        await conn.commit()
    repeated = await promos.test_promo(item["id"], ADMIN, bot, item["revision"], "fifth-second")
    assert repeated["test_run_key"] == queued["test_run_key"]
    async with db_backend.connect() as conn:
        conn.row_factory = db_backend.Row
        cur = await conn.execute("SELECT COUNT(*) AS n FROM notification_test_sends WHERE campaign_id = ?", (item["id"],))
        assert (await cur.fetchone())["n"] == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("is_test", [True, False])
async def test_fenced_unstarted_fifth_claim_recovers_without_spending_attempt(is_test):
    bot = fake_bot()
    item = await draft()
    if is_test:
        await promos.test_promo(item["id"], ADMIN, bot, item["revision"], "unstarted")
    else:
        tested = await _test_and_deliver(item, bot)
        await promos.start_promo(
            item["id"], ADMIN, bot, item["revision"], tested["content_hash"], 3
        )
    bot.send_media_group.reset_mock()
    bot.send_message.reset_mock()
    table = "notification_test_sends" if is_test else "notification_deliveries"
    claim = worker._claim_test_delivery if is_test else worker._claim_delivery
    async with db_backend.connect() as conn:
        await conn.execute(
            f"UPDATE {table} SET attempts = ? WHERE campaign_id = ?",
            (worker.MAX_ATTEMPTS - 1, item["id"]),
        )
        await conn.commit()
    claimed = await claim()
    assert claimed["attempts"] == worker.MAX_ATTEMPTS
    assert claimed["attempt_token"]
    assert promos._decode(claimed["delivery_parts"], []) == []
    async with db_backend.connect() as conn:
        await conn.execute(
            f"UPDATE {table} SET lease_until = CURRENT_TIMESTAMP - INTERVAL '1 second' "
            "WHERE id = ?", (claimed["id"],),
        )
        await conn.commit()
    assert await worker._recover_table(is_test=is_test) == 1
    async with db_backend.connect() as conn:
        conn.row_factory = db_backend.Row
        cur = await conn.execute(f"SELECT * FROM {table} WHERE id = ?", (claimed["id"],))
        row = await cur.fetchone()
        assert row["status"] == "failed"
        assert row["attempts"] == worker.MAX_ATTEMPTS - 1
        assert row["attempt_token"] is None
        assert promos._decode(row["delivery_parts"], []) == []
    bot.send_media_group.assert_not_awaited()
    bot.send_message.assert_not_awaited()
    resumed = await claim()
    assert resumed["id"] == claimed["id"]
    assert resumed["attempt_token"] != claimed["attempt_token"]
    await worker.process_delivery(bot, resumed)
    bot.send_media_group.assert_awaited_once()
    bot.send_message.assert_awaited_once()
    async with db_backend.connect() as conn:
        conn.row_factory = db_backend.Row
        cur = await conn.execute(f"SELECT status FROM {table} WHERE id = ?", (claimed["id"],))
        assert (await cur.fetchone())["status"] == "sent"


@pytest.mark.asyncio
@pytest.mark.parametrize("status, token", [("sending", None), ("uncertain", "old-owner")])
async def test_legacy_unfenced_or_already_uncertain_empty_attempt_is_not_retried(status, token):
    item = await draft()
    async with db_backend.connect() as conn:
        await conn.execute(
            "UPDATE notification_campaigns SET status = 'running' WHERE id = ?", (item["id"],)
        )
        cur = await conn.execute(
            """INSERT INTO notification_deliveries
               (campaign_id, telegram_id, status, attempts, attempt_token, lease_until)
               VALUES (?, 1001, ?, ?, ?, CURRENT_TIMESTAMP - INTERVAL '1 second') RETURNING id""",
            (item["id"], status, worker.MAX_ATTEMPTS, token),
        )
        delivery_id = (await cur.fetchone())[0]
        await conn.commit()
    recovered = await worker._recover_expired_leases()
    assert recovered == (1 if status == "sending" else 0)
    async with db_backend.connect() as conn:
        conn.row_factory = db_backend.Row
        cur = await conn.execute(
            "SELECT status, attempts FROM notification_deliveries WHERE id = ?", (delivery_id,)
        )
        row = await cur.fetchone()
        assert row["status"] == "uncertain"
        assert row["attempts"] == worker.MAX_ATTEMPTS
    assert await worker._claim_delivery() is None


@pytest.mark.asyncio
@pytest.mark.parametrize("is_test", [True, False])
async def test_partial_inflight_progress_is_never_retried_by_unstarted_claim_recovery(is_test):
    bot = fake_bot()
    item = await draft()
    if is_test:
        await promos.test_promo(item["id"], ADMIN, bot, item["revision"], "partial-intent")
    else:
        tested = await _test_and_deliver(item, bot)
        await promos.start_promo(
            item["id"], ADMIN, bot, item["revision"], tested["content_hash"], 3
        )
    table = "notification_test_sends" if is_test else "notification_deliveries"
    claim = worker._claim_test_delivery if is_test else worker._claim_delivery
    claimed = await claim()
    bot.send_media_group.reset_mock()
    bot.send_message.reset_mock()
    bot.send_message.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await worker.process_delivery(bot, claimed)
    async with db_backend.connect() as conn:
        conn.row_factory = db_backend.Row
        cur = await conn.execute(f"SELECT delivery_parts FROM {table} WHERE id = ?", (claimed["id"],))
        parts = promos._decode((await cur.fetchone())["delivery_parts"], [])
        assert parts[0]["status"] == "sent"
        assert parts[1]["status"] == "sending"
        await conn.execute(
            f"UPDATE {table} SET lease_until = CURRENT_TIMESTAMP - INTERVAL '1 second' WHERE id = ?",
            (claimed["id"],),
        )
        await conn.commit()
    assert await worker._recover_table(is_test=is_test) == 1
    async with db_backend.connect() as conn:
        conn.row_factory = db_backend.Row
        cur = await conn.execute(f"SELECT status, attempts FROM {table} WHERE id = ?", (claimed["id"],))
        row = await cur.fetchone()
        assert row["status"] == "uncertain"
        assert row["attempts"] == claimed["attempts"]
    next_claim = await claim()
    assert next_claim is None or next_claim["id"] != claimed["id"]
    bot.send_media_group.assert_awaited_once()
    bot.send_message.assert_awaited_once()


async def _promo_revision_audit(campaign_id):
    async with db_backend.connect() as conn:
        conn.row_factory = db_backend.Row
        cursor = await conn.execute(
            "SELECT campaign_id, revision, admin_telegram_id, payload_hash, created_at "
            "FROM notification_promo_revisions WHERE campaign_id = ? ORDER BY revision",
            (campaign_id,),
        )
        return [dict(row) for row in await cursor.fetchall()]


@pytest.mark.asyncio
async def test_promo_revision_audit_records_creation_and_actual_edit_actor():
    from datetime import datetime

    created = await promos.create_promo(ADMIN, "audited-create")
    replay = await promos.create_promo(ADMIN, "audited-create")
    assert replay["id"] == created["id"]
    assert replay["revision"] == 1
    initial = await _promo_revision_audit(created["id"])
    assert len(initial) == 1
    assert initial[0]["admin_telegram_id"] == ADMIN
    assert initial[0]["revision"] == 1
    assert initial[0]["payload_hash"] == created["content_hash"]
    assert datetime.fromisoformat(str(initial[0]["created_at"])).tzinfo is not None

    edited = await promos.save_promo(created["id"], OTHER_ADMIN, payload(), 1)
    rows = await _promo_revision_audit(created["id"])
    assert [(row["revision"], row["admin_telegram_id"]) for row in rows] == [(1, ADMIN), (2, OTHER_ADMIN)]
    assert rows[0] == initial[0]
    assert rows[1]["payload_hash"] == edited["content_hash"]
    assert rows[1]["created_at"] >= rows[0]["created_at"]
    assert set(rows[1]) == {"campaign_id", "revision", "admin_telegram_id", "payload_hash", "created_at"}


@pytest.mark.asyncio
async def test_unchanged_invalid_and_stale_saves_add_no_revision_audit():
    item = await draft()
    before = await _promo_revision_audit(item["id"])
    identical = await promos.save_promo(item["id"], OTHER_ADMIN, item["message"], item["revision"])
    assert identical["revision"] == item["revision"]
    with pytest.raises(promos.PromoError, match="актуальную версию"):
        await promos.save_promo(item["id"], OTHER_ADMIN, payload(buttons=0), item["revision"] - 1)
    invalid = payload()
    invalid["media"] = [{"type": "document", "file_id": "unsupported"}]
    with pytest.raises(promos.PromoError):
        await promos.save_promo(item["id"], OTHER_ADMIN, invalid, item["revision"])
    assert await _promo_revision_audit(item["id"]) == before
    current = await promos.get_promo(item["id"], ADMIN)
    assert current["revision"] == item["revision"]
    assert current["message"] == item["message"]


@pytest.mark.asyncio
async def test_duplicate_audits_new_creation_and_copy_actor_without_changing_source():
    original = await draft()
    original_audit = await _promo_revision_audit(original["id"])
    duplicate = await promos.duplicate_promo(original["id"], OTHER_ADMIN)
    assert duplicate["id"] != original["id"]
    assert duplicate["message"] == original["message"]
    rows = await _promo_revision_audit(duplicate["id"])
    assert [(row["revision"], row["admin_telegram_id"]) for row in rows] == [(1, OTHER_ADMIN), (2, OTHER_ADMIN)]
    assert rows[-1]["payload_hash"] == duplicate["content_hash"]
    assert await _promo_revision_audit(original["id"]) == original_audit


@pytest.mark.asyncio
async def test_failed_revision_audit_insert_rolls_back_campaign_edit_and_create():
    item = await draft()
    before = await _promo_revision_audit(item["id"])
    # The compatibility adapter deliberately skips generic DDL; use psycopg,
    # as schema creation does, only against the fixture's guarded test database.
    async with await psycopg.AsyncConnection.connect(os.environ["DATABASE_URL"]) as conn:
        await conn.execute(
            "ALTER TABLE notification_promo_revisions ADD CONSTRAINT test_reject_actor "
            "CHECK (admin_telegram_id <> 999999998)"
        )
        await conn.commit()
    with pytest.raises(Exception, match="test_reject_actor"):
        await promos.save_promo(item["id"], OTHER_ADMIN, payload(buttons=0), item["revision"])
    with pytest.raises(Exception, match="test_reject_actor"):
        await promos.create_promo(OTHER_ADMIN, "audit-must-commit")
    current = await promos.get_promo(item["id"], ADMIN)
    assert current["message"] == item["message"]
    assert current["revision"] == item["revision"]
    assert await _promo_revision_audit(item["id"]) == before
    assert [entry["id"] for entry in await promos.list_promos(ADMIN)] == [item["id"]]


@pytest.mark.asyncio
async def test_promo_test_timestamp_is_timezone_aware_in_detail_and_list(worker_clock):
    from datetime import datetime

    tested = await _test_and_deliver(await draft(), fake_bot())
    listed = next(entry for entry in await promos.list_promos(ADMIN) if entry["id"] == tested["id"])
    async with db_backend.connect() as conn:
        conn.row_factory = db_backend.Row
        cursor = await conn.execute("SELECT EXTRACT(EPOCH FROM CURRENT_TIMESTAMP) AS now_epoch")
        now_epoch = float((await cursor.fetchone())["now_epoch"])
    for item in (tested, listed):
        timestamp = datetime.fromisoformat(item["tested_at"])
        assert timestamp.tzinfo is not None
        assert 0 <= now_epoch - timestamp.timestamp() < 10
