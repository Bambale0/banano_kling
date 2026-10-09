"""Referral events commit atomically; mocked Telegram delivery is receipt-safe.

All users, generation IDs and message receipts are synthetic. Each test uses a
temporary SQLite database and the real shared sender with a fake Bot API boundary.
"""

import asyncio
import hashlib
import hmac
import json
import socket
import time
from dataclasses import asdict
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import urlencode

import pytest
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramRetryAfter,
    TelegramServerError,
)
from aiogram.methods import SendMessage


@pytest.fixture
async def app(isolated_database, monkeypatch):
    """Use the shared isolated database and forbid real network calls."""
    def reject_network(*_args, **_kwargs):
        raise AssertionError("Referral notification tests must never use the network")

    monkeypatch.setattr(socket.socket, "connect", reject_network)
    monkeypatch.setattr(socket.socket, "connect_ex", reject_network)

    from bot import database, partner_policy, referral_notifications
    from bot import db as db_backend
    from bot.config import config
    from bot.services import referral_service

    monkeypatch.setattr(referral_service, "DATABASE_PATH", database.DATABASE_PATH)
    monkeypatch.setattr(database, "_BOT_SETTING_CACHE", {})
    monkeypatch.setattr(config, "is_admin", lambda _telegram_id: False)
    return SimpleNamespace(
        db=database,
        backend=db_backend,
        policy=partner_policy,
        outbox=referral_notifications,
        referrals=referral_service,
        bot=SimpleNamespace(send_message=AsyncMock(return_value=SimpleNamespace(message_id=73001))),
    )


async def rows(app, sql="SELECT * FROM referral_notification_outbox ORDER BY event_key", values=()):
    async with app.backend.connect() as db:
        db.row_factory = app.backend.Row
        return [dict(row) for row in await (await db.execute(sql, values)).fetchall()]


async def execute(app, sql, values=()):
    async with app.backend.connect() as db:
        await db.execute(sql, values)
        await db.commit()


async def users(app):
    inviter = await app.db.get_or_create_user(886101)
    invited = await app.db.get_or_create_user(886102)
    return inviter, invited


async def attach(app, *, surface="service"):
    inviter, invited = await users(app)
    if surface == "database":
        assert await app.db.process_referral(invited.telegram_id, inviter.referral_code)
    elif surface == "transaction":
        async with app.backend.connect() as db:
            db.row_factory = app.backend.Row
            result = await app.referrals.attach_referral_in_transaction(
                db, invited.telegram_id, invited.id, inviter.referral_code,
                source="notification-test-transaction",
            )
            assert result.attached, result.reason
            assert result.notify_partner is False
            await db.commit()
    else:
        result = await app.referrals.process_referral_click(
            invited.telegram_id, inviter.referral_code, source="notification-test"
        )
        assert result.attached, result.reason
    return inviter, invited


async def accepted_task(app, monkeypatch, invited, task_id="accepted-notification-test"):
    # Persist genuine provider-accepted proof, then exercise racing callbacks below.
    with monkeypatch.context() as patch:
        patch.setattr(app.db, "mark_generation_accepted", AsyncMock(return_value=False))
        assert await app.db.add_generation_task(
            invited.id, invited.telegram_id, task_id, "image", "test",
            cost=2, provider_accepted=True,
        )
    return task_id


def progress(snapshot, status, *, message_ids=None):
    """Construct persisted sender state using its public snapshot contract."""
    return [
        {
            "index": index,
            "part_hash": hashlib.sha256(
                json.dumps(part, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
            "status": status,
            "message_ids": list(message_ids or []),
            "attempts": 1,
        }
        for index, part in enumerate(snapshot["parts"])
    ]


async def expire_claim(app, event, parts):
    await execute(
        app,
        """UPDATE referral_notification_outbox
           SET status = 'sending', attempts = 1, lease_until = ?,
               attempt_token = 'expired-synthetic-attempt', delivery_parts = ?
           WHERE event_key = ?""",
        (time.time() - 10, json.dumps(parts), event["event_key"]),
    )


@pytest.mark.parametrize("surface", ["database", "service", "transaction"])
async def test_attachment_queues_one_event_without_crediting_inviter(app, surface):
    inviter, invited = await attach(app, surface=surface)
    events = await rows(app)
    assert len(events) == 1
    event = events[0]
    assert event["event_key"] == f"attached:{invited.id}"
    assert event["kind"] == "attached"
    assert event["referrer_id"] == inviter.id
    assert event["telegram_id"] == inviter.telegram_id
    assert event["status"] == "queued"
    assert event["attempts"] == 0
    assert json.loads(event["delivery_parts"]) == []
    assert json.loads(event["snapshot"])["message"]["schema_version"] == 2
    updated = await app.db.get_or_create_user(inviter.telegram_id)
    assert updated.credits == inviter.credits
    assert updated.referral_earned == inviter.referral_earned
    assert (await app.db.get_or_create_user(invited.telegram_id)).credits == invited.credits
    app.bot.send_message.assert_not_awaited()


async def test_duplicate_and_parallel_attachments_enqueue_once(app):
    inviter, invited = await users(app)
    outcomes = await asyncio.gather(*(
        app.referrals.process_referral_click(
            invited.telegram_id, inviter.referral_code, source="parallel-notification-test"
        )
        for _ in range(8)
    ))
    assert sum(result.attached for result in outcomes) == 1
    assert not await app.db.process_referral(invited.telegram_id, inviter.referral_code)
    assert len(await rows(app)) == 1
    assert len(await rows(app, "SELECT * FROM referral_activation_bonuses")) == 1
    assert (await app.db.get_or_create_user(inviter.telegram_id)).credits == inviter.credits


async def test_parallel_qualification_credits_and_queues_distinct_bonus_once(app, monkeypatch):
    inviter, invited = await attach(app)
    task_id = await accepted_task(app, monkeypatch, invited)
    outcomes = await asyncio.gather(*(
        app.policy.mark_generation_accepted(task_id) for _ in range(8)
    ))
    assert outcomes.count(True) == 1
    events = await rows(app)
    assert [event["event_key"] for event in events] == [
        f"attached:{invited.id}", f"bonus:{invited.id}"
    ]
    assert all(event["status"] == "queued" for event in events)
    bonus = (await rows(app, "SELECT * FROM referral_activation_bonuses"))[0]
    assert bonus["granted_at"] is not None
    updated = await app.db.get_or_create_user(inviter.telegram_id)
    assert updated.credits == inviter.credits + bonus["bonus_credits"]
    assert updated.referral_earned == inviter.referral_earned + bonus["bonus_credits"]
    assert not await app.policy.mark_generation_accepted(task_id)
    assert len(await rows(app)) == 2
    app.bot.send_message.assert_not_awaited()


async def test_attachment_transaction_rollback_also_removes_event(app, monkeypatch):
    inviter, invited = await users(app)
    original = app.db.record_pending_invite_bonus

    async def fail_after_enqueue(db, *args):
        await original(db, *args)
        assert (await (await db.execute("SELECT COUNT(*) FROM referral_notification_outbox")).fetchone())[0] == 1
        raise RuntimeError("synthetic attachment transaction failure")

    monkeypatch.setattr(app.db, "record_pending_invite_bonus", fail_after_enqueue)
    with pytest.raises(RuntimeError, match="synthetic attachment"):
        await app.db.process_referral(invited.telegram_id, inviter.referral_code)
    assert await rows(app) == []
    assert await rows(app, "SELECT * FROM referral_activation_bonuses") == []
    assert await rows(app, "SELECT * FROM referrals") == []
    assert (await app.db.get_or_create_user(invited.telegram_id)).referred_by is None


async def test_bonus_enqueue_failure_rolls_back_new_grant_and_can_reconcile(app, monkeypatch):
    inviter, invited = await attach(app)
    task_id = await accepted_task(app, monkeypatch, invited)
    enqueue = app.outbox.enqueue_referral_notification

    async def fail_after_enqueue(db, *args):
        await enqueue(db, *args)
        raise RuntimeError("synthetic bonus enqueue failure")

    with monkeypatch.context() as patch:
        patch.setattr(app.outbox, "enqueue_referral_notification", fail_after_enqueue)
        assert not await app.policy.mark_generation_accepted(task_id)
    assert [event["kind"] for event in await rows(app)] == ["attached"]
    assert (await app.db.get_or_create_user(inviter.telegram_id)).credits == inviter.credits
    assert (await rows(app, "SELECT * FROM referral_activation_bonuses"))[0]["granted_at"] is None
    assert await app.policy.reconcile_pending_invite_bonuses() == 1
    assert [event["kind"] for event in await rows(app)] == ["attached", "bonus"]


async def test_schema_initialization_never_backfills_historical_referrals(app):
    inviter, invited = await users(app)
    async with app.backend.connect() as db:
        await db.execute("UPDATE users SET referred_by = ? WHERE id = ?", (inviter.id, invited.id))
        await db.execute(
            "INSERT INTO referrals (referrer_id, referred_id, bonus_credits) VALUES (?, ?, 3)",
            (inviter.id, invited.id),
        )
        await db.execute(
            """INSERT INTO referral_activation_bonuses
               (referred_id, referrer_id, bonus_credits, granted_at)
               VALUES (?, ?, 3, CURRENT_TIMESTAMP)""",
            (invited.id, inviter.id),
        )
        await app.outbox.init_referral_notification_schema(db)
        await app.outbox.init_referral_notification_schema(db)
        await db.commit()
    assert await app.outbox.recover_expired_referral_notifications() == 0
    assert not await app.outbox.deliver_pending_referral_notification(app.bot)
    assert await rows(app) == []
    app.bot.send_message.assert_not_awaited()


async def test_enqueued_identity_is_escaped_and_snapshot_is_immutable(app):
    inviter, invited = await users(app)
    await execute(
        app, "UPDATE users SET first_name = ?, last_name = ?, username = ? WHERE id = ?",
        ("<Synthetic>", "A & B", "synthetic_user", invited.id),
    )
    assert await app.db.process_referral(invited.telegram_id, inviter.referral_code)
    before = (await rows(app))[0]["snapshot"]
    text = json.loads(before)["message"]["text"]
    assert "&lt;Synthetic&gt;" in text
    assert "A &amp; B" in text
    assert "@synthetic_user" in text
    await execute(app, "UPDATE users SET first_name = 'Changed' WHERE id = ?", (invited.id,))
    async with app.backend.connect() as db:
        db.row_factory = app.backend.Row
        await app.outbox.enqueue_referral_notification(db, "attached", inviter.id, invited.id, 999)
        await db.commit()
    assert len(await rows(app)) == 1
    assert (await rows(app))[0]["snapshot"] == before


async def test_delivery_persists_intent_before_api_and_receipt_after_api(app):
    inviter, _ = await attach(app)
    event = (await rows(app))[0]
    snapshot = json.loads(event["snapshot"])

    async def send_message(**kwargs):
        # A separate reader sees committed intent before the network boundary.
        during = (await rows(app))[0]
        assert during["status"] == "sending"
        assert during["attempt_token"]
        assert json.loads(during["delivery_parts"])[0]["status"] == "sending"
        assert kwargs == {"chat_id": inviter.telegram_id, **snapshot["parts"][0]["kwargs"]}
        # A write must complete while the API is in flight: no billing transaction
        # may be held open across Telegram I/O.
        await asyncio.wait_for(
            execute(app, "UPDATE users SET first_name = 'Network boundary' WHERE id = ?", (inviter.id,)),
            timeout=2,
        )
        return SimpleNamespace(message_id=73002)

    app.bot.send_message.side_effect = send_message
    assert await app.outbox.deliver_pending_referral_notification(app.bot)
    after = (await rows(app))[0]
    assert after["status"] == "sent"
    assert after["telegram_message_id"] == 73002
    assert json.loads(after["delivery_parts"])[0]["message_ids"] == [73002]
    assert after["attempt_token"] is None
    assert after["lease_until"] is None
    assert not await app.outbox.deliver_pending_referral_notification(app.bot)
    app.bot.send_message.assert_awaited_once()


async def test_retry_after_is_delayed_then_delivered_once(app):
    await attach(app)
    app.bot.send_message.side_effect = TelegramRetryAfter(
        method=SendMessage(chat_id=886101, text="synthetic"), message="rate limited", retry_after=30,
    )
    before = time.time()
    assert await app.outbox.deliver_pending_referral_notification(app.bot)
    failed = (await rows(app))[0]
    assert failed["status"] == "failed"
    assert failed["next_attempt_at"] >= before + 30
    assert failed["telegram_message_id"] is None
    assert json.loads(failed["delivery_parts"])[0]["status"] == "retryable"
    assert not await app.outbox.deliver_pending_referral_notification(app.bot)
    app.bot.send_message.assert_awaited_once()
    await execute(app, "UPDATE referral_notification_outbox SET next_attempt_at = 0")
    app.bot.send_message.side_effect = None
    assert await app.outbox.deliver_pending_referral_notification(app.bot)
    delivered = (await rows(app))[0]
    assert delivered["status"] == "sent"
    assert delivered["attempts"] == 2
    assert delivered["telegram_message_id"] == 73001
    assert not await app.outbox.deliver_pending_referral_notification(app.bot)
    assert app.bot.send_message.await_count == 2


@pytest.mark.parametrize("failure", ["timeout", "server", "connection", "invalid_receipt"])
async def test_ambiguous_delivery_is_uncertain_and_never_replayed(app, failure):
    await attach(app)
    if failure == "invalid_receipt":
        app.bot.send_message.return_value = SimpleNamespace(message_id=0)
    else:
        errors = {
            "timeout": TimeoutError("synthetic timeout"),
            "connection": ConnectionError("synthetic dropped response"),
            "server": TelegramServerError(
                method=SendMessage(chat_id=886101, text="synthetic"), message="server error",
            ),
        }
        app.bot.send_message.side_effect = errors[failure]
    assert await app.outbox.deliver_pending_referral_notification(app.bot)
    event = (await rows(app))[0]
    assert event["status"] == "uncertain"
    assert event["telegram_message_id"] is None
    assert await app.outbox.recover_expired_referral_notifications() == 0
    assert not await app.outbox.deliver_pending_referral_notification(app.bot)
    app.bot.send_message.assert_awaited_once()


@pytest.mark.parametrize("failure,status", [("forbidden", "blocked"), ("bad_request", "terminal")])
async def test_definitive_failures_are_not_retried(app, failure, status):
    await attach(app)
    error = TelegramForbiddenError if failure == "forbidden" else TelegramBadRequest
    app.bot.send_message.side_effect = error(
        method=SendMessage(chat_id=886101, text="synthetic"), message="synthetic rejected request",
    )
    assert await app.outbox.deliver_pending_referral_notification(app.bot)
    assert (await rows(app))[0]["status"] == status
    assert not await app.outbox.deliver_pending_referral_notification(app.bot)
    app.bot.send_message.assert_awaited_once()


@pytest.mark.parametrize("part_state", ["empty", "pending"])
async def test_expired_lease_before_api_is_safely_recoverable(app, part_state):
    await attach(app)
    event = (await rows(app))[0]
    parts = [] if part_state == "empty" else progress(json.loads(event["snapshot"]), "pending")
    await expire_claim(app, event, parts)
    assert await app.outbox.recover_expired_referral_notifications() == 1
    assert (await rows(app))[0]["status"] in {"queued", "failed"}
    assert await app.outbox.deliver_pending_referral_notification(app.bot)
    assert (await rows(app))[0]["status"] == "sent"
    app.bot.send_message.assert_awaited_once()


async def test_expired_lease_with_saved_api_intent_is_uncertain(app):
    await attach(app)
    event = (await rows(app))[0]
    await expire_claim(app, event, progress(json.loads(event["snapshot"]), "sending"))
    assert await app.outbox.recover_expired_referral_notifications() == 1
    assert (await rows(app))[0]["status"] == "uncertain"
    assert not await app.outbox.deliver_pending_referral_notification(app.bot)
    app.bot.send_message.assert_not_awaited()


async def test_expired_lease_with_saved_receipt_finishes_without_replay(app):
    await attach(app)
    event = (await rows(app))[0]
    await expire_claim(app, event, progress(json.loads(event["snapshot"]), "sent", message_ids=[73003]))
    assert await app.outbox.recover_expired_referral_notifications() == 1
    await app.outbox.deliver_pending_referral_notification(app.bot)
    after = (await rows(app))[0]
    assert after["status"] == "sent"
    assert after["telegram_message_id"] == 73003
    app.bot.send_message.assert_not_awaited()


async def test_unexpired_lease_is_not_recovered_or_reclaimed(app):
    await attach(app)
    event = (await rows(app))[0]
    await expire_claim(app, event, [])
    await execute(app, "UPDATE referral_notification_outbox SET lease_until = ?", (time.time() + 300,))
    assert await app.outbox.recover_expired_referral_notifications() == 0
    assert not await app.outbox.deliver_pending_referral_notification(app.bot)
    assert (await rows(app))[0]["status"] == "sending"
    app.bot.send_message.assert_not_awaited()


async def test_concurrent_delivery_claims_send_event_once(app):
    await attach(app)

    async def delayed_send(**_kwargs):
        await asyncio.sleep(0.02)
        return SimpleNamespace(message_id=73004)

    app.bot.send_message.side_effect = delayed_send
    outcomes = await asyncio.gather(*(
        app.outbox.deliver_pending_referral_notification(app.bot) for _ in range(8)
    ))
    assert outcomes.count(True) == 1
    assert outcomes.count(False) == 7
    assert (await rows(app))[0]["status"] == "sent"
    assert (await rows(app))[0]["attempts"] == 1
    app.bot.send_message.assert_awaited_once()


async def test_delivery_failure_does_not_reverse_previously_committed_credit(app, monkeypatch):
    inviter, invited = await attach(app)
    task_id = await accepted_task(app, monkeypatch, invited)
    assert await app.policy.mark_generation_accepted(task_id)
    credited = await app.db.get_or_create_user(inviter.telegram_id)
    assert credited.credits > inviter.credits
    app.bot.send_message.side_effect = TimeoutError("synthetic ambiguous response")
    assert await app.outbox.deliver_pending_referral_notification(app.bot)
    assert await app.outbox.deliver_pending_referral_notification(app.bot)
    assert all(event["status"] == "uncertain" for event in await rows(app))
    assert not await app.policy.mark_generation_accepted(task_id)
    assert await app.policy.reconcile_pending_invite_bonuses() == 0
    unchanged = await app.db.get_or_create_user(inviter.telegram_id)
    assert unchanged.credits == credited.credits
    assert unchanged.referral_earned == credited.referral_earned
    assert app.bot.send_message.await_count == 2


async def test_cancelled_inflight_api_never_replays_after_lease_expiry(app):
    await attach(app)
    app.bot.send_message.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await app.outbox.deliver_pending_referral_notification(app.bot)
    event = (await rows(app))[0]
    assert event["status"] == "sending"
    assert json.loads(event["delivery_parts"])[0]["status"] == "sending"
    await execute(app, "UPDATE referral_notification_outbox SET lease_until = ?", (time.time() - 1,))
    assert await app.outbox.recover_expired_referral_notifications() == 1
    assert (await rows(app))[0]["status"] == "uncertain"
    assert not await app.outbox.deliver_pending_referral_notification(app.bot)
    app.bot.send_message.assert_awaited_once()


async def test_bonus_waits_for_pending_attachment_delivery(app, monkeypatch):
    _, invited = await attach(app)
    task_id = await accepted_task(app, monkeypatch, invited)
    assert await app.policy.mark_generation_accepted(task_id)
    await execute(
        app,
        "UPDATE referral_notification_outbox SET status = 'failed', next_attempt_at = ? WHERE kind = 'attached'",
        (time.time() + 300,),
    )
    assert not await app.outbox.deliver_pending_referral_notification(app.bot)
    app.bot.send_message.assert_not_awaited()
    await execute(app, "UPDATE referral_notification_outbox SET next_attempt_at = 0 WHERE kind = 'attached'")
    assert await app.outbox.deliver_pending_referral_notification(app.bot)
    events = await rows(app)
    assert [(event["kind"], event["status"]) for event in events] == [
        ("attached", "sent"), ("bonus", "queued")
    ]
    assert await app.outbox.deliver_pending_referral_notification(app.bot)
    assert all(event["status"] == "sent" for event in await rows(app))
    assert app.bot.send_message.await_count == 2


async def test_preexisting_pending_claim_gets_only_new_bonus_notification(app, monkeypatch):
    _, invited = await attach(app)
    # Simulate an attachment committed before outbox rollout, still unqualified.
    await execute(app, "DELETE FROM referral_notification_outbox")
    task_id = await accepted_task(app, monkeypatch, invited)
    assert await app.policy.mark_generation_accepted(task_id)
    events = await rows(app)
    assert len(events) == 1
    assert events[0]["event_key"] == f"bonus:{invited.id}"
    assert await app.outbox.deliver_pending_referral_notification(app.bot)
    assert (await rows(app))[0]["status"] == "sent"
    app.bot.send_message.assert_awaited_once()


async def test_saved_receipt_survives_transient_final_status_write_failure(app, monkeypatch):
    await attach(app)
    finish = app.outbox._finish
    failed_once = False

    async def fail_final_write_once(item, status, **kwargs):
        nonlocal failed_once
        if status == "sent" and not failed_once:
            failed_once = True
            raise RuntimeError("synthetic transient final status write failure")
        await finish(item, status, **kwargs)

    monkeypatch.setattr(app.outbox, "_finish", fail_final_write_once)
    with pytest.raises(RuntimeError, match="synthetic transient final status"):
        await app.outbox.deliver_pending_referral_notification(app.bot)
    event = (await rows(app))[0]
    assert json.loads(event["delivery_parts"])[0]["message_ids"] == [73001]
    await execute(
        app, "UPDATE referral_notification_outbox SET lease_until = ? WHERE status = 'sending'",
        (time.time() - 1,),
    )
    await app.outbox.recover_expired_referral_notifications()
    await app.outbox.deliver_pending_referral_notification(app.bot)
    recovered = (await rows(app))[0]
    assert recovered["status"] == "sent"
    assert recovered["telegram_message_id"] == 73001
    app.bot.send_message.assert_awaited_once()


@pytest.mark.parametrize("message_ids", [["not-an-id"], [-1], [True], [73001, 73002]])
async def test_malformed_saved_receipt_is_uncertain_not_successful(app, message_ids):
    await attach(app)
    event = (await rows(app))[0]
    await expire_claim(app, event, progress(json.loads(event["snapshot"]), "sent", message_ids=message_ids))
    assert await app.outbox.recover_expired_referral_notifications() == 1
    assert (await rows(app))[0]["status"] == "uncertain"
    assert not await app.outbox.deliver_pending_referral_notification(app.bot)
    app.bot.send_message.assert_not_awaited()


@pytest.mark.parametrize("existing_user", [False, True])
async def test_signed_miniapp_referral_queues_without_inline_telegram(app, monkeypatch, existing_user):
    from bot import miniapp
    from bot.config import config
    from bot.handlers import common

    inviter = await app.db.get_or_create_user(886101)
    if existing_user:
        await app.db.get_or_create_user(886102)
    monkeypatch.setattr(miniapp, "DATABASE_PATH", app.db.DATABASE_PATH)
    monkeypatch.setattr(miniapp, "_mini_app_referral_last_attempt", {})
    monkeypatch.setattr(miniapp, "process_referral_click", app.referrals.process_referral_click)
    inline_send = AsyncMock(side_effect=AssertionError("Mini App must not await partner notification"))
    monkeypatch.setattr(common, "_notify_partner_about_new_referral", inline_send)
    await app.db.set_channel_subscription_required(False)
    fields = {
        "auth_date": str(int(time.time())),
        "user": json.dumps({"id": 886102, "first_name": "Synthetic Mini App User"}),
        "start_param": f"prompt_42_ref_{inviter.referral_code}",
    }
    secret = hmac.new(b"WebAppData", config.BOT_TOKEN.encode(), hashlib.sha256).digest()
    check = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
    fields["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    for _ in range(2):
        telegram_id, _context = await asyncio.wait_for(
            miniapp._get_user_context({"bot": app.bot}, urlencode(fields)), timeout=2,
        )
        assert telegram_id == 886102
    invited = await app.db.get_or_create_user(886102)
    assert invited.referred_by == inviter.id
    events = await rows(app)
    assert len(events) == 1
    assert events[0]["event_key"] == f"attached:{invited.id}"
    assert events[0]["status"] == "queued"
    assert (await app.db.get_or_create_user(inviter.telegram_id)).credits == inviter.credits
    inline_send.assert_not_awaited()
    app.bot.send_message.assert_not_awaited()


async def test_start_referral_queues_without_inline_partner_notification(app, monkeypatch):
    from aiogram.types import User

    from bot.handlers import common

    inviter = await app.db.get_or_create_user(886101)
    inline_send = AsyncMock(side_effect=AssertionError("Start must not await partner notification"))
    monkeypatch.setattr(common, "_notify_partner_about_new_referral", inline_send)
    message = SimpleNamespace(
        text=f"/start ref_{inviter.referral_code}",
        from_user=User(id=886102, is_bot=False, first_name="Synthetic Start User"),
        bot=app.bot,
        answer=AsyncMock(),
    )
    state = SimpleNamespace(clear=AsyncMock())
    for _ in range(2):
        await common.cmd_start(message, state)
    invited = await app.db.get_or_create_user(886102)
    assert invited.referred_by == inviter.id
    events = await rows(app)
    assert len(events) == 1
    assert events[0]["event_key"] == f"attached:{invited.id}"
    assert events[0]["status"] == "queued"
    assert (await app.db.get_or_create_user(inviter.telegram_id)).credits == inviter.credits
    inline_send.assert_not_awaited()
    app.bot.send_message.assert_not_awaited()
    assert message.answer.await_count == 2


@pytest.mark.parametrize("fail_when", ["sending", "sent"])
async def test_progress_write_failure_recovers_only_confirmed_safe_state(app, monkeypatch, fail_when):
    await attach(app)
    save = app.outbox._save_progress

    async def fail_selected_progress(item, parts):
        if parts[0]["status"] == fail_when:
            raise RuntimeError("synthetic progress write failure")
        await save(item, parts)

    with monkeypatch.context() as patch:
        patch.setattr(app.outbox, "_save_progress", fail_selected_progress)
        with pytest.raises(app.outbox.ReferralProgressStorageError):
            await app.outbox.deliver_pending_referral_notification(app.bot)
    event = (await rows(app))[0]
    assert event["status"] == "sending"
    await execute(app, "UPDATE referral_notification_outbox SET lease_until = ?", (time.time() - 1,))
    assert await app.outbox.recover_expired_referral_notifications() == 1
    if fail_when == "sending":
        app.bot.send_message.assert_not_awaited()
        assert await app.outbox.deliver_pending_referral_notification(app.bot)
        assert (await rows(app))[0]["status"] == "sent"
    else:
        assert (await rows(app))[0]["status"] == "uncertain"
        assert not await app.outbox.deliver_pending_referral_notification(app.bot)
    app.bot.send_message.assert_awaited_once()


async def test_worker_does_not_log_raw_telegram_error_when_error_write_fails(app, monkeypatch, caplog):
    await attach(app)
    marker = "SYNTHETIC_DO_NOT_LOG_TOKEN"
    app.bot.send_message.side_effect = TelegramBadRequest(
        method=SendMessage(chat_id=886101, text="synthetic"), message=marker,
    )
    monkeypatch.setattr(
        app.outbox, "_finish", AsyncMock(side_effect=RuntimeError("synthetic finish write error"))
    )
    monkeypatch.setattr(app.outbox.asyncio, "sleep", AsyncMock(side_effect=asyncio.CancelledError()))
    with pytest.raises(asyncio.CancelledError):
        await app.outbox.referral_notification_worker(app.bot)
    assert marker not in caplog.text
    app.bot.send_message.assert_awaited_once()


async def test_worker_start_is_guarded_and_shutdown_allows_clean_restart(app, monkeypatch):
    started = asyncio.Event()

    async def fake_worker(bot):
        assert bot is app.bot
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(app.outbox, "referral_notification_worker", fake_worker)
    try:
        first = app.outbox.ensure_referral_notification_worker(app.bot)
        assert app.outbox.ensure_referral_notification_worker(app.bot) is first
        await asyncio.wait_for(started.wait(), timeout=2)
        await app.outbox.stop_referral_notification_worker()
        assert first.cancelled()
        started.clear()
        restarted = app.outbox.ensure_referral_notification_worker(app.bot)
        assert restarted is not first
        assert app.outbox.ensure_referral_notification_worker(app.bot) is restarted
        await asyncio.wait_for(started.wait(), timeout=2)
        await app.outbox.stop_referral_notification_worker()
        assert restarted.cancelled()
        await app.outbox.stop_referral_notification_worker()
    finally:
        await app.outbox.stop_referral_notification_worker()
    app.bot.send_message.assert_not_awaited()


@pytest.mark.parametrize("activation", ["available_marker", "start_command"])
async def test_miniapp_only_inviter_waits_for_bot_start_then_delivers_in_order(app, monkeypatch, activation):
    inviter = await app.db.get_or_create_user(886101, initial_telegram_chat_state="never_started")
    _, invited = await attach(app)
    task_id = await accepted_task(app, monkeypatch, invited)
    assert await app.policy.mark_generation_accepted(task_id)
    credited = await app.db.get_or_create_user(inviter.telegram_id)

    for _ in range(2):
        assert not await app.outbox.deliver_pending_referral_notification(app.bot)
        assert await app.outbox.recover_expired_referral_notifications() == 0
    events = await rows(app)
    assert [(event["kind"], event["status"], event["attempts"]) for event in events] == [
        ("attached", "queued", 0), ("bonus", "queued", 0),
    ]
    assert all(json.loads(event["delivery_parts"]) == [] for event in events)
    app.bot.send_message.assert_not_awaited()

    if activation == "available_marker":
        await app.db.mark_telegram_chat_available(inviter.telegram_id)
    else:
        from aiogram.types import User

        from bot.handlers import common

        message = SimpleNamespace(
            text="/start",
            from_user=User(id=inviter.telegram_id, is_bot=False, first_name="Synthetic Inviter"),
            bot=app.bot,
            answer=AsyncMock(),
        )
        await common.cmd_start(message, SimpleNamespace(clear=AsyncMock()))
        message.answer.assert_awaited_once()
    app.bot.send_message.assert_not_awaited()

    assert await app.outbox.deliver_pending_referral_notification(app.bot)
    events = await rows(app)
    assert [(event["kind"], event["status"]) for event in events] == [
        ("attached", "sent"), ("bonus", "queued"),
    ]
    assert await app.outbox.deliver_pending_referral_notification(app.bot)
    assert all(event["status"] == "sent" for event in await rows(app))
    assert not await app.outbox.deliver_pending_referral_notification(app.bot)
    assert app.bot.send_message.await_count == 2
    assert (await app.db.get_or_create_user(inviter.telegram_id)).credits == credited.credits


async def test_miniapp_only_inviter_does_not_starve_available_recipient(app, monkeypatch):
    waiting = await app.db.get_or_create_user(886101, initial_telegram_chat_state="never_started")
    _, invited = await attach(app)
    task_id = await accepted_task(app, monkeypatch, invited)
    assert await app.policy.mark_generation_accepted(task_id)
    available = await app.db.get_or_create_user(886201, initial_telegram_chat_state="available")
    other_invited = await app.db.get_or_create_user(886202)
    assert await app.db.process_referral(other_invited.telegram_id, available.referral_code)

    assert await app.outbox.deliver_pending_referral_notification(app.bot)
    app.bot.send_message.assert_awaited_once()
    assert app.bot.send_message.await_args.kwargs["chat_id"] == available.telegram_id
    assert not await app.outbox.deliver_pending_referral_notification(app.bot)
    waiting_events = [event for event in await rows(app) if event["referrer_id"] == waiting.id]
    assert len(waiting_events) == 2
    assert all(event["status"] == "queued" and event["attempts"] == 0 for event in waiting_events)


async def test_bot_start_does_not_requeue_real_telegram_blocked_result(app):
    inviter, _ = await attach(app)
    app.bot.send_message.side_effect = TelegramForbiddenError(
        method=SendMessage(chat_id=inviter.telegram_id, text="synthetic"), message="bot was blocked",
    )
    assert await app.outbox.deliver_pending_referral_notification(app.bot)
    assert (await rows(app))[0]["status"] == "blocked"
    await app.db.mark_telegram_chat_available(inviter.telegram_id)
    assert await app.outbox.recover_expired_referral_notifications() == 0
    assert not await app.outbox.deliver_pending_referral_notification(app.bot)
    assert (await rows(app))[0]["status"] == "blocked"
    app.bot.send_message.assert_awaited_once()


@pytest.mark.parametrize("actual_attempts", [1, 4])
async def test_unstarted_retry_claim_crashes_preserve_actual_api_attempt_budget(app, actual_attempts):
    await attach(app)
    app.bot.send_message.side_effect = TelegramRetryAfter(
        method=SendMessage(chat_id=886101, text="synthetic"), message="rate limited", retry_after=1,
    )
    for _ in range(actual_attempts):
        assert await app.outbox.deliver_pending_referral_notification(app.bot)
        await execute(app, "UPDATE referral_notification_outbox SET next_attempt_at = 0")
    event = (await rows(app))[0]
    saved_parts = json.loads(event["delivery_parts"])
    assert saved_parts[0]["status"] == "retryable"
    assert saved_parts[0]["attempts"] == actual_attempts
    assert event["attempts"] == actual_attempts

    for _ in range(3):
        # Crash after acquiring ownership, before persisting a new send intent.
        claim = await app.outbox._claim()
        assert claim is not None
        during = (await rows(app))[0]
        assert during["status"] == "sending"
        assert json.loads(during["delivery_parts"]) == saved_parts
        await execute(app, "UPDATE referral_notification_outbox SET lease_until = ?", (time.time() - 1,))
        assert await app.outbox.recover_expired_referral_notifications() == 1
        recovered = (await rows(app))[0]
        assert recovered["status"] in {"queued", "failed"}
        assert recovered["attempts"] == actual_attempts
        assert app.bot.send_message.await_count == actual_attempts
        await execute(app, "UPDATE referral_notification_outbox SET next_attempt_at = 0")

    app.bot.send_message.side_effect = None
    assert await app.outbox.deliver_pending_referral_notification(app.bot)
    sent = (await rows(app))[0]
    assert sent["status"] == "sent"
    assert sent["attempts"] == actual_attempts + 1
    assert json.loads(sent["delivery_parts"])[0]["attempts"] == actual_attempts + 1
    assert app.bot.send_message.await_count == actual_attempts + 1
    assert not await app.outbox.deliver_pending_referral_notification(app.bot)


async def managed_settings(app, monkeypatch, **overrides):
    from bot.config import config

    monkeypatch.setattr(config, "is_admin", lambda actor: actor == 999999999)
    values = asdict(await app.outbox.get_referral_notification_settings())
    values.update(overrides)
    await app.outbox.save_referral_notification_settings(json.dumps(values), admin_id=999999999)
    return values


async def test_managed_notification_settings_default_save_and_reset(app, monkeypatch):
    defaults = asdict(await app.outbox.get_referral_notification_settings())
    assert defaults["poll_seconds"] == 1.0
    assert defaults["batch_delay_seconds"] == 0.05
    assert defaults["lease_seconds"] == 90
    assert defaults["max_attempts"] == 5
    for field in ("attached_template", "bonus_template"):
        assert "{identity}" in defaults[field]
        assert "{bonus}" in defaults[field]
    updated = await managed_settings(
        app, monkeypatch, poll_seconds=2.5, batch_delay_seconds=0.2,
        lease_seconds=120, max_attempts=7,
        attached_template="<b>Attached</b> {identity}: {bonus}",
        bonus_template="<b>Bonus</b> {identity}: {bonus}",
    )
    assert asdict(await app.outbox.get_referral_notification_settings()) == updated
    async with app.backend.connect() as db:
        db.row_factory = app.backend.Row
        assert asdict(await app.outbox.get_referral_notification_settings(db)) == updated
    stored = await rows(
        app, "SELECT * FROM bot_settings WHERE key = ?",
        (app.outbox.REFERRAL_NOTIFICATION_SETTINGS_KEY,),
    )
    assert stored[0]["updated_by_telegram_id"] == 999999999
    await app.outbox.reset_referral_notification_settings(admin_id=999999999)
    assert asdict(await app.outbox.get_referral_notification_settings()) == defaults


@pytest.mark.parametrize("field,value", [
    ("poll_seconds", 0.09), ("poll_seconds", 61), ("poll_seconds", True),
    ("poll_seconds", float("nan")), ("poll_seconds", float("inf")),
    ("batch_delay_seconds", 0), ("batch_delay_seconds", 5.1), ("batch_delay_seconds", False),
    ("lease_seconds", 60), ("lease_seconds", 901), ("lease_seconds", 61.5),
    ("lease_seconds", True), ("max_attempts", 0), ("max_attempts", 21),
    ("max_attempts", 1.5), ("max_attempts", False), ("unknown_field", 1),
    ("attached_template", "Missing bonus {identity}"),
    ("bonus_template", "Missing identity {bonus}"),
    ("attached_template", "{identity.__class__} {bonus}"),
    ("attached_template", "{identity[0]} {bonus}"),
    ("attached_template", "{identity!r} {bonus}"),
    ("attached_template", "{identity:>20} {bonus}"),
    ("attached_template", "{identity} {bonus} {unexpected}"),
    ("attached_template", "<script>{identity}</script> {bonus}"),
    ("attached_template", "<b>{identity} {bonus}"),
    ("attached_template", "X" * 2001 + " {identity} {bonus}"),
])
async def test_managed_notification_settings_reject_unsafe_or_invalid_values(app, field, value):
    settings = asdict(await app.outbox.get_referral_notification_settings())
    settings[field] = value
    with pytest.raises(ValueError):
        app.outbox.validate_referral_notification_settings(settings)


@pytest.mark.parametrize("edge", ["minimum", "maximum"])
async def test_managed_notification_settings_accept_documented_boundaries(app, edge):
    settings = asdict(await app.outbox.get_referral_notification_settings())
    if edge == "minimum":
        settings.update(poll_seconds=0.1, batch_delay_seconds=0.01, lease_seconds=61, max_attempts=1)
    else:
        settings.update(poll_seconds=60, batch_delay_seconds=5, lease_seconds=900, max_attempts=20)
    assert asdict(app.outbox.validate_referral_notification_settings(settings)) == settings


async def test_managed_settings_unauthorized_save_and_reset_cannot_mutate_state(app):
    defaults = asdict(await app.outbox.get_referral_notification_settings())
    changed = {**defaults, "max_attempts": 7}
    with pytest.raises(PermissionError):
        await app.outbox.save_referral_notification_settings(json.dumps(changed), admin_id=886101)
    with pytest.raises(PermissionError):
        await app.outbox.reset_referral_notification_settings(admin_id=886101)
    assert asdict(await app.outbox.get_referral_notification_settings()) == defaults


@pytest.mark.parametrize("invalid", ["not-json", "unsafe-settings"])
async def test_invalid_stored_notification_settings_fall_back_without_logging_payload(app, caplog, invalid):
    defaults = asdict(await app.outbox.get_referral_notification_settings())
    marker = "SYNTHETIC_PRIVATE_SETTINGS_MARKER"
    payload = marker if invalid == "not-json" else json.dumps({**defaults, "attached_template": marker})
    assert await app.db.set_bot_setting(app.outbox.REFERRAL_NOTIFICATION_SETTINGS_KEY, payload)
    assert asdict(await app.outbox.get_referral_notification_settings()) == defaults
    assert caplog.records
    assert marker not in caplog.text


async def test_managed_notification_copy_is_frozen_for_existing_events(app, monkeypatch):
    await managed_settings(
        app, monkeypatch,
        attached_template="OLD {identity}; pending {bonus}",
        bonus_template="OLD BONUS {identity}; credited {bonus}",
    )
    inviter, invited = await attach(app)
    old_snapshot = (await rows(app))[0]["snapshot"]
    assert json.loads(old_snapshot)["message"]["text"].startswith("OLD ")
    await managed_settings(
        app, monkeypatch,
        attached_template="NEW {identity}; pending {bonus}",
        bonus_template="NEW BONUS {identity}; credited {bonus}",
    )
    task_id = await accepted_task(app, monkeypatch, invited)
    assert await app.policy.mark_generation_accepted(task_id)
    newcomer = await app.db.get_or_create_user(886103)
    assert await app.db.process_referral(newcomer.telegram_id, inviter.referral_code)
    events = {event["event_key"]: event for event in await rows(app)}
    assert events[f"attached:{invited.id}"]["snapshot"] == old_snapshot
    assert json.loads(events[f"attached:{newcomer.id}"]["snapshot"])["message"]["text"].startswith("NEW ")
    assert json.loads(events[f"bonus:{invited.id}"]["snapshot"])["message"]["text"].startswith("NEW BONUS ")


async def test_managed_max_attempts_applies_to_future_claims(app, monkeypatch):
    await attach(app)
    app.bot.send_message.side_effect = TelegramRetryAfter(
        method=SendMessage(chat_id=886101, text="synthetic"), message="rate limited", retry_after=1,
    )
    assert await app.outbox.deliver_pending_referral_notification(app.bot)
    await execute(app, "UPDATE referral_notification_outbox SET next_attempt_at = 0")
    await managed_settings(app, monkeypatch, max_attempts=1)
    assert not await app.outbox.deliver_pending_referral_notification(app.bot)
    app.bot.send_message.assert_awaited_once()
    assert (await rows(app))[0]["status"] == "terminal"
    await managed_settings(app, monkeypatch, max_attempts=2)
    app.bot.send_message.side_effect = None
    assert not await app.outbox.deliver_pending_referral_notification(app.bot)
    # Higher limits apply to new eligible work, never revive terminal receipts.
    inviter = await app.db.get_or_create_user(886101)
    newcomer = await app.db.get_or_create_user(886199)
    assert await app.db.process_referral(newcomer.telegram_id, inviter.referral_code)
    assert await app.outbox.deliver_pending_referral_notification(app.bot)
    assert next(row for row in await rows(app) if row['referred_id'] == newcomer.id)['status'] == 'sent'
    assert app.bot.send_message.await_count == 2


async def test_managed_lease_and_attempt_policy_are_captured_for_inflight_claim(app, monkeypatch):
    await managed_settings(app, monkeypatch, lease_seconds=120, max_attempts=1)
    await attach(app)
    finish = app.outbox._finish
    observed_remaining_lease = []

    async def change_policy_during_send(**_kwargs):
        await managed_settings(app, monkeypatch, lease_seconds=300, max_attempts=7)
        raise TelegramRetryAfter(
            method=SendMessage(chat_id=886101, text="synthetic"), message="rate limited", retry_after=1,
        )

    async def observe_finish(item, status, **kwargs):
        current = (await rows(app))[0]
        observed_remaining_lease.append(current["lease_until"] - time.time())
        await finish(item, status, **kwargs)

    app.bot.send_message.side_effect = change_policy_during_send
    monkeypatch.setattr(app.outbox, "_finish", observe_finish)
    assert await app.outbox.deliver_pending_referral_notification(app.bot)
    assert (await rows(app))[0]["status"] == "terminal"
    assert len(observed_remaining_lease) == 1
    assert 115 <= observed_remaining_lease[0] <= 121
    assert not await app.outbox.deliver_pending_referral_notification(app.bot)
    app.bot.send_message.assert_awaited_once()


async def test_managed_worker_poll_and_batch_delay_are_used(app, monkeypatch):
    await managed_settings(app, monkeypatch, poll_seconds=2.5, batch_delay_seconds=0.2)
    monkeypatch.setattr(app.outbox, "recover_expired_referral_notifications", AsyncMock(return_value=0))
    monkeypatch.setattr(app.outbox, "deliver_pending_referral_notification", AsyncMock(side_effect=[False, True]))
    delays = []

    async def observed_sleep(delay):
        delays.append(delay)
        if len(delays) == 2:
            raise asyncio.CancelledError

    monkeypatch.setattr(app.outbox.asyncio, "sleep", observed_sleep)
    with pytest.raises(asyncio.CancelledError):
        await app.outbox.referral_notification_worker(app.bot)
    assert delays == [2.5, 0.2]


def settings_admin_message(text="/referral_notifications_config", *, actor=999999999, reply=None):
    return SimpleNamespace(
        text=text,
        from_user=SimpleNamespace(id=actor) if actor is not None else None,
        reply_to_message=reply,
        answer=AsyncMock(),
        answer_document=AsyncMock(),
    )


@pytest.mark.parametrize("actor", [None, 886101])
@pytest.mark.parametrize("action", ["", " set {}", " reset"])
async def test_notification_admin_command_rejects_unauthorized_before_settings_access(app, monkeypatch, actor, action):
    from bot.handlers import admin

    monkeypatch.setattr(admin, "is_admin", lambda _actor: False)
    spies = []
    for name in (
        "get_referral_notification_settings", "save_referral_notification_settings",
        "reset_referral_notification_settings",
    ):
        spy = AsyncMock(side_effect=AssertionError("Unauthorized settings access"))
        monkeypatch.setattr(app.outbox, name, spy)
        spies.append(spy)
    message = settings_admin_message("/referral_notifications_config" + action, actor=actor)
    await admin.cmd_referral_notifications_config(message)
    message.answer.assert_awaited_once()
    message.answer_document.assert_not_awaited()
    for spy in spies:
        spy.assert_not_awaited()


async def test_notification_admin_read_returns_downloadable_current_json(app, monkeypatch):
    from bot.handlers import admin

    expected = await managed_settings(app, monkeypatch, poll_seconds=2.5, max_attempts=7)
    monkeypatch.setattr(admin, "is_admin", lambda actor: actor == 999999999)
    message = settings_admin_message()
    await admin.cmd_referral_notifications_config(message)
    message.answer_document.assert_awaited_once()
    document = message.answer_document.await_args.kwargs["document"]
    assert document.filename == "referral-notifications-config.json"
    assert json.loads(document.data.decode("utf-8")) == expected
    message.answer.assert_awaited_once()
    assert asdict(await app.outbox.get_referral_notification_settings()) == expected


@pytest.mark.parametrize("source", ["inline", "reply_text", "reply_caption"])
async def test_notification_admin_set_and_reset_use_authorized_persisted_settings(app, monkeypatch, source):
    from bot.config import config
    from bot.handlers import admin

    monkeypatch.setattr(config, "is_admin", lambda actor: actor == 999999999)
    monkeypatch.setattr(admin, "is_admin", lambda actor: actor == 999999999)
    defaults = asdict(await app.outbox.get_referral_notification_settings())
    expected = {**defaults, "max_attempts": 8}
    payload = json.dumps(expected)
    command = "/referral_notifications_config set"
    reply = None
    if source == "inline":
        command += " " + payload
    else:
        reply = SimpleNamespace(
            text=payload if source == "reply_text" else None,
            caption=payload if source == "reply_caption" else None,
        )
    message = settings_admin_message(command, reply=reply)
    await admin.cmd_referral_notifications_config(message)
    message.answer.assert_awaited_once()
    assert asdict(await app.outbox.get_referral_notification_settings()) == expected
    reset = settings_admin_message("/referral_notifications_config reset")
    await admin.cmd_referral_notifications_config(reset)
    reset.answer.assert_awaited_once()
    assert asdict(await app.outbox.get_referral_notification_settings()) == defaults


@pytest.mark.parametrize("suffix", [" set", " set " + "X" * 12001, " reset unexpected", " unknown"])
async def test_notification_admin_invalid_command_never_mutates_settings(app, monkeypatch, suffix):
    from bot.handlers import admin

    monkeypatch.setattr(admin, "is_admin", lambda actor: actor == 999999999)
    save = AsyncMock(side_effect=AssertionError("Invalid command cannot save settings"))
    reset = AsyncMock(side_effect=AssertionError("Invalid command cannot reset settings"))
    monkeypatch.setattr(app.outbox, "save_referral_notification_settings", save)
    monkeypatch.setattr(app.outbox, "reset_referral_notification_settings", reset)
    message = settings_admin_message("/referral_notifications_config" + suffix)
    await admin.cmd_referral_notifications_config(message)
    message.answer.assert_awaited_once()
    save.assert_not_awaited()
    reset.assert_not_awaited()


@pytest.mark.parametrize("exception_type", [ValueError, RuntimeError])
async def test_notification_admin_error_response_and_logs_do_not_echo_private_input(app, monkeypatch, caplog, exception_type):
    from bot.handlers import admin

    monkeypatch.setattr(admin, "is_admin", lambda actor: actor == 999999999)
    marker = "SYNTHETIC_PRIVATE_ADMIN_INPUT"
    save = AsyncMock(side_effect=exception_type(marker))
    monkeypatch.setattr(app.outbox, "save_referral_notification_settings", save)
    message = settings_admin_message('/referral_notifications_config set {"private":"' + marker + '"}')
    await admin.cmd_referral_notifications_config(message)
    save.assert_awaited_once()
    message.answer.assert_awaited_once()
    assert marker not in str(message.answer.await_args)
    assert marker not in caplog.text


async def test_huge_integer_managed_setting_is_rejected_and_stored_fallback_is_safe(app, caplog):
    value = {"poll_seconds": 10 ** 400}
    with pytest.raises(ValueError):
        app.outbox.validate_referral_notification_settings(value)
    await app.db.set_bot_setting(app.outbox.REFERRAL_NOTIFICATION_SETTINGS_KEY, json.dumps(value))
    settings = await app.outbox.get_referral_notification_settings()
    assert settings.poll_seconds == 1.0
    await attach(app)
    assert len(await rows(app)) == 1
    assert str(10 ** 400) not in caplog.text


@pytest.mark.parametrize("template", [
    '<a href="{identity}">{bonus}</a>',
    '<a href="javascript:alert(1)">{identity}</a> {bonus}',
    '<a href="https://example.com">{identity}</a> {bonus}',
    '<b title="{identity}">Name</b> {bonus}',
])
async def test_receipt_templates_reject_attributes_and_links(app, template):
    with pytest.raises(ValueError):
        app.outbox.validate_referral_notification_settings({"attached_template": template})


async def test_lower_then_higher_retry_limit_cannot_reverse_receipt_order(app, monkeypatch):
    inviter, invited = await attach(app)
    task_id = await accepted_task(app, monkeypatch, invited)
    assert await app.policy.mark_generation_accepted(task_id)
    app.bot.send_message.side_effect = TelegramRetryAfter(
        method=SendMessage(chat_id=inviter.telegram_id, text="synthetic"),
        message="synthetic rate limit", retry_after=1,
    )
    assert await app.outbox.deliver_pending_referral_notification(app.bot)
    monkeypatch.setattr(app.outbox, 'get_referral_notification_settings', AsyncMock(
        return_value=app.outbox.ReferralNotificationSettings(max_attempts=1),
    ))
    app.bot.send_message.side_effect = None
    assert await app.outbox.deliver_pending_referral_notification(app.bot)
    current = await rows(app)
    assert next(r for r in current if r['kind'] == 'attached')['status'] == 'terminal'
    assert next(r for r in current if r['kind'] == 'bonus')['status'] == 'sent'
    monkeypatch.setattr(app.outbox, 'get_referral_notification_settings', AsyncMock(
        return_value=app.outbox.ReferralNotificationSettings(max_attempts=2),
    ))
    await execute(app, 'UPDATE referral_notification_outbox SET next_attempt_at = 0')
    assert not await app.outbox.deliver_pending_referral_notification(app.bot)
    assert app.bot.send_message.await_count == 2


async def test_admin_can_reapply_maximum_templates_from_bounded_json_document(app, monkeypatch):
    from bot.config import config
    from bot.handlers import admin

    monkeypatch.setattr(config, 'is_admin', lambda actor: actor == 999999999)
    monkeypatch.setattr(admin, 'is_admin', lambda actor: actor == 999999999)
    template = '{identity} {bonus}' + 'x' * 1982
    assert len(template) == 2000
    payload = json.dumps({**asdict(app.outbox.ReferralNotificationSettings()),
                          'attached_template': template, 'bonus_template': template}).encode()
    assert len(payload) > 4096
    document = SimpleNamespace(file_size=len(payload), file_id='synthetic-json')
    reply = SimpleNamespace(document=document, text=None, caption='Edited settings file')
    message = settings_admin_message('/referral_notifications_config set', reply=reply)
    async def download(file, *, destination, timeout):
        assert file is document and timeout == 10
        destination.write(payload)
    message.bot = SimpleNamespace(download=AsyncMock(side_effect=download))
    await admin.cmd_referral_notifications_config(message)
    message.bot.download.assert_awaited_once()
    saved = await app.outbox.get_referral_notification_settings()
    assert saved.attached_template == template and saved.bonus_template == template


@pytest.mark.parametrize('size,content,downloaded', [
    (None, b'{}', False), (48001, b'{}', False),
    (1, b'x' * 48001, True), (1, b'\xff', True),
])
async def test_admin_document_bounds_and_encoding_fail_before_setting_mutation(app, monkeypatch, size, content, downloaded):
    from bot.handlers import admin

    monkeypatch.setattr(admin, 'is_admin', lambda actor: actor == 999999999)
    save = AsyncMock(side_effect=AssertionError('Invalid document cannot mutate settings'))
    monkeypatch.setattr(app.outbox, 'save_referral_notification_settings', save)
    reply = SimpleNamespace(document=SimpleNamespace(file_size=size), text=None, caption=None)
    message = settings_admin_message('/referral_notifications_config set', reply=reply)
    async def download(_file, *, destination, timeout):
        destination.write(content)
    message.bot = SimpleNamespace(download=AsyncMock(side_effect=download))
    await admin.cmd_referral_notifications_config(message)
    assert message.bot.download.await_count == int(downloaded)
    save.assert_not_awaited()
    message.answer.assert_awaited_once()


async def test_notification_admin_large_settings_roundtrip_via_bounded_json_document(app, monkeypatch):
    from bot.config import config
    from bot.handlers import admin

    monkeypatch.setattr(config, 'is_admin', lambda actor: actor == 999999999)
    monkeypatch.setattr(admin, 'is_admin', lambda actor: actor == 999999999)
    template = '"' * 1978 + '{identity} {bonus}'
    assert len(template) < 2000
    value = {'attached_template': template, 'bonus_template': template, 'max_attempts': 6}
    raw = json.dumps(value).encode('utf-8')
    assert len(raw) > 4096
    reply = SimpleNamespace(text=None, caption=None, document=SimpleNamespace(file_size=len(raw)))
    message = settings_admin_message('/referral_notifications_config set', reply=reply)

    async def download(document, *, destination, timeout):
        assert document is reply.document and timeout == 10
        destination.write(raw)

    message.bot = SimpleNamespace(download=AsyncMock(side_effect=download))
    await admin.cmd_referral_notifications_config(message)
    message.bot.download.assert_awaited_once()
    assert (await app.outbox.get_referral_notification_settings()).attached_template == template
    assert (await app.outbox.get_referral_notification_settings()).max_attempts == 6


@pytest.mark.parametrize('declared,actual', [(48001, b'{}'), (None, b'{}'), (100, b'X' * 48001), (100, b'\xff')])
async def test_notification_admin_document_limits_reject_without_mutation(app, monkeypatch, declared, actual):
    from bot.handlers import admin

    monkeypatch.setattr(admin, 'is_admin', lambda actor: actor == 999999999)
    save = AsyncMock(side_effect=AssertionError('Invalid document must not be saved'))
    monkeypatch.setattr(app.outbox, 'save_referral_notification_settings', save)
    reply = SimpleNamespace(text=None, caption=None, document=SimpleNamespace(file_size=declared))
    message = settings_admin_message('/referral_notifications_config set', reply=reply)

    async def download(_document, *, destination, timeout):
        destination.write(actual)

    message.bot = SimpleNamespace(download=AsyncMock(side_effect=download))
    await admin.cmd_referral_notifications_config(message)
    save.assert_not_awaited()
    if declared is None or declared > 48000:
        message.bot.download.assert_not_awaited()


@pytest.mark.parametrize('template', [
    '<code>{identity}</code> {bonus}',
    '<pre>{identity}</pre> {bonus}',
    '{identity} <b><code>{bonus}</code></b>',
    '{identity} <code><i>{bonus}</i></code>',
    '{identity} <pre><code>{bonus}</code></pre>',
])
async def test_managed_template_rejects_overlapping_code_entities(app, template):
    with pytest.raises(ValueError):
        app.outbox.validate_referral_notification_settings({'attached_template': template})


async def test_legacy_settings_migration_preserves_values_and_enables_audited_set_reset(app, monkeypatch):
    from bot.config import config
    monkeypatch.setattr(config, "is_admin", lambda value: value == 999999999)
    async with app.backend.connect() as db:
        await db.execute('DROP TABLE bot_settings')
        await db.execute('CREATE TABLE bot_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
        await db.execute("INSERT INTO bot_settings VALUES ('genjutsu.config', 'legacy-value')")
        await app.outbox.init_referral_notification_schema(db)
        await app.outbox.init_referral_notification_schema(db)
        await db.commit()
    await app.outbox.save_referral_notification_settings('{"max_attempts": 3}', admin_id=999999999)
    await app.outbox.reset_referral_notification_settings(admin_id=999999999)
    values = await rows(app, 'SELECT * FROM bot_settings ORDER BY key')
    assert values[0]['value'] == 'legacy-value'
    assert values[0]['updated_by_telegram_id'] is None
    assert values[1]['updated_by_telegram_id'] == 999999999
    assert values[1]['updated_at'] is not None


async def test_schema_migration_supports_raw_postgres_connections(app, monkeypatch):
    statements = []

    class RawPostgresConnection:
        async def execute(self, sql):
            statements.append(sql)

    monkeypatch.setattr(app.backend, 'is_postgres', lambda: True)
    await app.outbox.init_referral_notification_schema(RawPostgresConnection())
    assert sum('ADD COLUMN IF NOT EXISTS' in sql for sql in statements) == 2
    assert not any('PRAGMA' in sql for sql in statements)
