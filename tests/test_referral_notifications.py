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
