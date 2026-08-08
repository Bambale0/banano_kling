import asyncio
import os

import pytest

pytestmark = pytest.mark.skipif(
    os.getenv("PARTNER_POSTGRES_TEST") != "1",
    reason="requires the dedicated PostgreSQL partner-approval CI job",
)


async def _bootstrap_production_like_partner_schema() -> None:
    """Create only the legacy tables required by the partner/referral runtime.

    Production PostgreSQL is an existing schema. The compatibility adapter does
    not support cold-starting the entire SQLite DDL on an empty PostgreSQL DB,
    so this focused CI job recreates the pre-existing contract explicitly and
    then exercises all feature operations through db_backend.connect().
    """

    import psycopg

    dsn = os.environ["DATABASE_URL"]
    async with await psycopg.AsyncConnection.connect(dsn) as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id BIGSERIAL PRIMARY KEY,
                    telegram_id BIGINT UNIQUE NOT NULL,
                    credits DOUBLE PRECISION DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    referral_code TEXT UNIQUE,
                    referred_by BIGINT REFERENCES users(id),
                    referral_earned DOUBLE PRECISION DEFAULT 0,
                    has_paid BOOLEAN DEFAULT FALSE,
                    partner_agreed_at TIMESTAMP,
                    partner_total_revenue_rub DOUBLE PRECISION DEFAULT 0,
                    partner_balance_rub DOUBLE PRECISION DEFAULT 0,
                    partner_withdrawn_rub DOUBLE PRECISION DEFAULT 0,
                    prompt_repeat_balance_rub DOUBLE PRECISION DEFAULT 0,
                    prompt_repeat_total_rub DOUBLE PRECISION DEFAULT 0,
                    partner_tier TEXT DEFAULT 'basic',
                    channel_url TEXT,
                    photo_url TEXT,
                    is_banned BOOLEAN DEFAULT FALSE,
                    banned_at TIMESTAMP,
                    banned_by_telegram_id BIGINT
                )
                """
            )
            await cur.execute(
                """
                CREATE TABLE IF NOT EXISTS transactions (
                    id BIGSERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL REFERENCES users(id),
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            await cur.execute(
                """
                CREATE TABLE IF NOT EXISTS referrals (
                    id BIGSERIAL PRIMARY KEY,
                    referrer_id BIGINT NOT NULL REFERENCES users(id),
                    referred_id BIGINT NOT NULL REFERENCES users(id),
                    bonus_credits DOUBLE PRECISION DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(referrer_id, referred_id)
                )
                """
            )

            # postgres_aiosqlite's compatibility bootstrap expects these legacy
            # tables to exist before its first connection and normalizes costs.
            await cur.execute(
                """
                CREATE TABLE IF NOT EXISTS generation_tasks (
                    id BIGSERIAL PRIMARY KEY,
                    cost DOUBLE PRECISION DEFAULT 0,
                    is_public_feed BOOLEAN DEFAULT FALSE,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            await cur.execute(
                """
                CREATE TABLE IF NOT EXISTS generation_history (
                    id BIGSERIAL PRIMARY KEY,
                    cost DOUBLE PRECISION DEFAULT 0
                )
                """
            )
            await cur.execute(
                """
                CREATE TABLE IF NOT EXISTS batch_jobs (
                    id BIGSERIAL PRIMARY KEY,
                    total_cost DOUBLE PRECISION DEFAULT 0
                )
                """
            )
        await conn.commit()


@pytest.mark.asyncio
async def test_partner_approval_state_machine_on_postgres():
    from bot import database
    from bot import db as db_backend
    from bot.services import partner_approval_service as approval
    from bot.services import referral_service

    assert db_backend.is_postgres() is True
    await _bootstrap_production_like_partner_schema()
    await approval.ensure_partner_approval_schema()

    referrer = await database.get_or_create_user(98100001)
    visitor = await database.get_or_create_user(98100002)

    # Two simultaneous application attempts must produce one durable pending row
    # and only one caller may report that it created/re-submitted the request.
    submissions = await asyncio.gather(
        approval.submit_partner_application(referrer.telegram_id, source="miniapp"),
        approval.submit_partner_application(referrer.telegram_id, source="telegram_bot"),
    )
    assert {item["status"] for item in submissions} == {approval.PARTNER_APPLICATION_PENDING}
    assert sum(bool(item["created"]) for item in submissions) == 1
    application_ids = {int(item["application_id"]) for item in submissions}
    assert len(application_ids) == 1
    application_id = application_ids.pop()

    approval.install_partner_referral_approval_guard()
    blocked = await referral_service.process_referral_click(
        visitor.telegram_id,
        referrer.referral_code,
        source="postgres-test",
        start_param=f"ref_{referrer.referral_code}",
    )
    assert blocked.attached is False
    assert blocked.reason == "blocked_referrer"

    # Competing terminal decisions must have a single winner. PostgreSQL
    # re-evaluates the conditional UPDATE after a concurrent updater commits.
    decisions = await asyncio.gather(
        approval.review_partner_application(
            application_id,
            approve=True,
            admin_telegram_id=99000001,
        ),
        approval.review_partner_application(
            application_id,
            approve=False,
            admin_telegram_id=99000002,
        ),
    )
    winners = [item for item in decisions if item.get("ok")]
    losers = [item for item in decisions if not item.get("ok")]
    assert len(winners) == 1
    assert len(losers) == 1
    assert losers[0].get("reason") in {"already_processed", "race_lost"}

    final_state = await approval.get_partner_application_state(referrer.telegram_id)
    assert final_state["status"] in {
        approval.PARTNER_APPLICATION_APPROVED,
        approval.PARTNER_APPLICATION_REJECTED,
    }

    # If rejection won, re-submit and approve so we can verify the legacy
    # financial activation flag and the referral path after approval.
    if final_state["status"] == approval.PARTNER_APPLICATION_REJECTED:
        resubmitted = await approval.submit_partner_application(
            referrer.telegram_id,
            source="postgres-test",
        )
        assert resubmitted["created"] is True
        reviewed = await approval.review_partner_application(
            resubmitted["application_id"],
            approve=True,
            admin_telegram_id=99000001,
        )
        assert reviewed["ok"] is True

    referrer_after = await database.get_or_create_user(referrer.telegram_id)
    assert referrer_after.partner_agreed_at is not None

    attached = await referral_service.process_referral_click(
        visitor.telegram_id,
        referrer.referral_code,
        source="postgres-test",
        start_param=f"ref_{referrer.referral_code}",
    )
    assert attached.attached is True
    assert attached.reason == "attached"


@pytest.mark.asyncio
async def test_legacy_partner_is_grandfathered_on_postgres():
    from bot import database
    from bot import db as db_backend
    from bot.services import partner_approval_service as approval

    assert db_backend.is_postgres() is True
    await _bootstrap_production_like_partner_schema()
    await approval.ensure_partner_approval_schema()

    user = await database.get_or_create_user(98100003)
    assert await database.accept_partner_agreement(user.telegram_id) is True

    state = await approval.get_partner_application_state(user.telegram_id)
    submit = await approval.submit_partner_application(user.telegram_id, source="postgres-test")

    assert state["status"] == approval.PARTNER_APPLICATION_APPROVED
    assert state["is_partner"] is True
    assert state["application_id"] is None
    assert submit["created"] is False
    assert submit["status"] == approval.PARTNER_APPLICATION_APPROVED
