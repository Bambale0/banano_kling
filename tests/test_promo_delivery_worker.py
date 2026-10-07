"""Offline worker contract tests at the persisted queue / Telegram boundary."""

import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.exceptions import TelegramRetryAfter
from aiogram.methods import SendMessage

from bot import notification_service as worker
from bot.promo_message import build_message_snapshot


class Connection:
    def __init__(self, *, row=None, rowcount=1):
        self.cursor = SimpleNamespace(
            rowcount=rowcount,
            fetchone=AsyncMock(return_value=row),
            fetchall=AsyncMock(return_value=[]),
        )
        self.execute = AsyncMock(return_value=self.cursor)
        self.commit = AsyncMock()
        self.rollback = AsyncMock()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


def item(*, is_test=False):
    snapshot = build_message_snapshot(
        {
            "schema_version": 2,
            "text": "Promo",
            "media": [
                {"type": "video", "file_id": "first"},
                {"type": "video", "file_id": "second"},
            ],
            "buttons": [
                {"position": 1, "text": "Open trend", "action": "trend", "trend_id": 11}
            ],
        },
        "example_bot",
    )
    return {
        "id": 8,
        "campaign_id": 9,
        "telegram_id": 123,
        "attempts": 1,
        "attempt_token": "owned-token",
        "is_test": is_test,
        "delivery_parts": [],
        "message_snapshot": snapshot,
        "content_hash": snapshot["content_hash"],
        "message": snapshot["message"],
    }


@pytest.mark.asyncio
async def test_admin_test_claim_pauses_without_configured_administrators(monkeypatch):
    monkeypatch.setattr(worker, "config", SimpleNamespace(admin_ids=[]))
    connection = Connection()
    monkeypatch.setattr(worker.db_backend, "connect", lambda: connection)
    assert await worker._claim_test_delivery() is None
    connection.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_admin_test_claim_requires_current_run_current_hash_and_admin_target(
    monkeypatch,
):
    monkeypatch.setattr(worker, "config", SimpleNamespace(admin_ids=[123, 456]))
    connection = Connection(row=item(is_test=True))
    monkeypatch.setattr(worker.db_backend, "connect", lambda: connection)
    claimed = await worker._claim_test_delivery()
    sql, parameters = connection.execute.await_args_list[0].args
    assert "d.test_run_key = c.test_run_key" in sql
    assert "d.content_hash = c.content_hash" in sql
    assert "d.telegram_id IN (?,?)" in sql
    assert "c.status IN ('draft', 'running', 'completed')" in sql
    assert "FOR UPDATE OF d SKIP LOCKED" in sql
    assert parameters == (worker.MAX_ATTEMPTS, 123, 456)
    update_sql, update_params = connection.execute.await_args_list[1].args
    assert "attempt_token = ?" in update_sql
    assert "lease_until = CURRENT_TIMESTAMP + (? * INTERVAL '1 second')" in update_sql
    assert update_params[0] == worker.LEASE_SECONDS
    assert claimed["attempt_token"] == update_params[1]
    assert claimed["attempt_token"] != "owned-token"
    assert claimed["attempts"] == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("is_test", [False, True])
async def test_test_and_campaign_worker_send_identical_snapshot_parts(
    monkeypatch, is_test
):
    monkeypatch.setattr(worker, "config", SimpleNamespace(admin_ids=[123]))
    connection = Connection()
    monkeypatch.setattr(worker.db_backend, "connect", lambda: connection)
    bot = SimpleNamespace(
        send_media_group=AsyncMock(
            return_value=[SimpleNamespace(message_id=1), SimpleNamespace(message_id=2)]
        ),
        send_message=AsyncMock(return_value=SimpleNamespace(message_id=3)),
    )
    delivery = item(is_test=is_test)
    await worker.process_delivery(bot, delivery)
    bot.send_media_group.assert_awaited_once_with(
        chat_id=123,
        media=[
            {"type": "video", "media": "first", "parse_mode": None},
            {"type": "video", "media": "second", "parse_mode": None},
        ],
    )
    bot.send_message.assert_awaited_once_with(
        chat_id=123,
        text="Promo",
        parse_mode=None,
        disable_web_page_preview=True,
        reply_markup={
            "inline_keyboard": [
                [
                    {
                        "text": "Open trend",
                        "url": "https://t.me/example_bot?startapp=prompt_11",
                    }
                ]
            ]
        },
    )
    assert [part["message_ids"] for part in delivery["delivery_parts"]] == [[1, 2], [3]]
    queries = connection.execute.await_args_list
    assert len(queries) == 5  # Four committed part transitions, then final status.
    for call in queries:
        sql = call.args[0]
        assert "attempt_token = ?" in sql
        assert "lease_until > CURRENT_TIMESTAMP" in sql
    assert queries[-1].args[1][0] == "sent"
    assert queries[-1].args[1][1] == 3


@pytest.mark.asyncio
async def test_lost_database_fence_prevents_any_telegram_part(monkeypatch):
    connection = Connection(rowcount=0)
    monkeypatch.setattr(worker.db_backend, "connect", lambda: connection)
    bot = SimpleNamespace(send_media_group=AsyncMock(), send_message=AsyncMock())
    await worker.process_delivery(bot, item())
    bot.send_media_group.assert_not_awaited()
    bot.send_message.assert_not_awaited()
    connection.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_removed_admin_cannot_receive_a_claimed_test(monkeypatch):
    monkeypatch.setattr(worker, "config", SimpleNamespace(admin_ids=[456]))
    connection = Connection()
    monkeypatch.setattr(worker.db_backend, "connect", lambda: connection)
    bot = SimpleNamespace(send_media_group=AsyncMock(), send_message=AsyncMock())
    await worker.process_delivery(bot, item(is_test=True))
    bot.send_media_group.assert_not_awaited()
    bot.send_message.assert_not_awaited()
    connection.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_retry_after_persists_receipts_and_schedules_delay(monkeypatch):
    connection = Connection()
    monkeypatch.setattr(worker.db_backend, "connect", lambda: connection)
    error = TelegramRetryAfter(
        method=SendMessage(chat_id=123, text="x"),
        message="secret-token",
        retry_after=47,
    )
    bot = SimpleNamespace(
        send_media_group=AsyncMock(
            return_value=[SimpleNamespace(message_id=1), SimpleNamespace(message_id=2)]
        ),
        send_message=AsyncMock(side_effect=error),
    )
    delivery = item()
    await worker.process_delivery(bot, delivery)
    assert delivery["delivery_parts"][0]["status"] == "sent"
    assert delivery["delivery_parts"][1]["retry_after"] == 47
    parameters = connection.execute.await_args.args[1]
    assert parameters[0] == "failed"
    assert parameters[3] is False
    assert parameters[5] == 47
    assert (
        "next_attempt_at = CURRENT_TIMESTAMP + (? * INTERVAL '1 second')"
        in connection.execute.await_args.args[0]
    )
    assert "secret-token" not in repr(connection.execute.await_args_list)
    saved = copy.deepcopy(delivery["delivery_parts"])
    delivery.update(delivery_parts=saved, attempt_token="next-owner", attempts=2)
    bot.send_message.side_effect = None
    bot.send_message.return_value = SimpleNamespace(message_id=3)
    await worker.process_delivery(bot, delivery)
    bot.send_media_group.assert_awaited_once()
    assert bot.send_message.await_count == 2


@pytest.mark.asyncio
async def test_ambiguous_failure_becomes_terminal_uncertain_without_exposing_exception(
    monkeypatch,
):
    connection = Connection()
    monkeypatch.setattr(worker.db_backend, "connect", lambda: connection)
    bot = SimpleNamespace(
        send_media_group=AsyncMock(side_effect=TimeoutError("secret-token")),
        send_message=AsyncMock(),
    )
    delivery = item()
    await worker.process_delivery(bot, delivery)
    parameters = connection.execute.await_args.args[1]
    assert parameters[0] == "uncertain"
    assert parameters[6] == "TimeoutError [reconciliation-required]"
    assert delivery["delivery_parts"][0]["status"] == "uncertain"
    assert "secret-token" not in repr(connection.execute.await_args_list)
    bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_v2_snapshot_is_dead_lettered_without_fallback_send(monkeypatch):
    connection = Connection()
    monkeypatch.setattr(worker.db_backend, "connect", lambda: connection)
    legacy_sender = AsyncMock()
    monkeypatch.setattr(worker, "send_campaign_message", legacy_sender)
    delivery = item()
    delivery["message_snapshot"] = None
    await worker.process_delivery(SimpleNamespace(), delivery)
    legacy_sender.assert_not_awaited()
    parameters = connection.execute.await_args.args[1]
    assert parameters[0] == "failed"
    assert parameters[3] is True
    assert parameters[4] == worker.MAX_ATTEMPTS


@pytest.mark.asyncio
async def test_legacy_payload_keeps_old_sender_semantics_but_saves_receipt(monkeypatch):
    connection = Connection()
    monkeypatch.setattr(worker.db_backend, "connect", lambda: connection)
    legacy_sender = AsyncMock(return_value=SimpleNamespace(message_id=15))
    monkeypatch.setattr(worker, "send_campaign_message", legacy_sender)
    delivery = item()
    delivery.update(
        message_snapshot=None,
        content_hash=None,
        message={
            "text": "Old format",
            "media_type": "photo",
            "media_file_id": "photo_id",
            "button_label": "Legacy",
            "button_url": "https://example.org",
        },
    )
    bot = SimpleNamespace()
    await worker.process_delivery(bot, delivery)
    legacy_sender.assert_awaited_once_with(bot, 123, delivery["message"])
    assert delivery["delivery_parts"][0]["message_ids"] == [15]
    await worker.process_delivery(bot, delivery)
    legacy_sender.assert_awaited_once()


@pytest.mark.asyncio
async def test_recovery_separates_unconfirmed_parts_from_confirmed_receipts(
    monkeypatch,
):
    connection = Connection(rowcount=0)
    monkeypatch.setattr(worker.db_backend, "connect", lambda: connection)
    assert await worker._recover_expired_leases() == 0
    sql = connection.execute.await_args.args[0]
    assert "THEN 'uncertain' ELSE 'failed'" in sql
    assert "THEN 'sent'" in sql
    assert "NOT IN ('sent', 'pending', 'retryable')" in sql
    assert "attempt_token = NULL" in sql
    assert "d.attempt_token IS NOT NULL" in sql
    assert "d.attempt_token IS NULL" in sql
    assert "GREATEST(d.attempts - 1, 0)" in sql
    assert "delivery lease expired before API intent" in sql
    assert "MAX((p->>'retry_after')::integer)" in sql
    assert "lease_until < CURRENT_TIMESTAMP" in sql


@pytest.mark.asyncio
async def test_obsolete_test_runs_are_cancelled_without_touching_inflight_or_legacy(
    monkeypatch,
):
    connection = Connection()
    monkeypatch.setattr(worker.db_backend, "connect", lambda: connection)
    await worker._cancel_obsolete_tests()
    sql = connection.execute.await_args.args[0]
    assert "t.test_run_key IS NOT NULL" in sql
    assert "t.status IN ('queued', 'failed')" in sql
    assert "t.test_run_key IS DISTINCT FROM c.test_run_key" in sql
    assert "t.content_hash IS DISTINCT FROM c.content_hash" in sql


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "admins, expected",
    [
        ([123], "t.telegram_id NOT IN (?)"),
        ([], "THEN 'test_recipient_no_longer_admin'"),
    ],
)
async def test_revoked_admin_tests_cancel_and_refresh_summary(
    monkeypatch, admins, expected
):
    from bot import promo_campaigns

    monkeypatch.setattr(worker, "config", SimpleNamespace(admin_ids=admins))
    connection = Connection()
    connection.cursor.fetchall.return_value = [{"campaign_id": 9}, {"campaign_id": 9}]
    monkeypatch.setattr(worker.db_backend, "connect", lambda: connection)
    refresh = AsyncMock()
    monkeypatch.setattr(promo_campaigns, "refresh_test_state", refresh)
    await worker._cancel_obsolete_tests()
    sql, parameters = connection.execute.await_args.args
    assert expected in sql
    assert parameters == tuple(admins + admins)
    refresh.assert_awaited_once_with(9, None)


@pytest.mark.asyncio
async def test_success_logs_only_identifiers_and_delivery_metadata(monkeypatch, caplog):
    import logging

    connection = Connection()
    monkeypatch.setattr(worker.db_backend, "connect", lambda: connection)
    bot = SimpleNamespace(
        send_media_group=AsyncMock(
            return_value=[SimpleNamespace(message_id=1), SimpleNamespace(message_id=2)]
        ),
        send_message=AsyncMock(return_value=SimpleNamespace(message_id=3)),
    )
    delivery = item()
    with caplog.at_level(logging.INFO):
        await worker.process_delivery(bot, delivery)
    assert "campaign_id=9 delivery_id=8 telegram_id=123" in caplog.text
    assert "attempt=1" in caplog.text
    assert "trend_ids=[11]" in caplog.text
    assert "method=send_media_group" in caplog.text
    assert "duration_ms=" in caplog.text
    assert "Promo" not in caplog.text
    assert "https://" not in caplog.text
