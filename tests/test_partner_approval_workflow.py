import asyncio
import importlib
from pathlib import Path

import pytest


def _reload_partner_modules(monkeypatch, db_path):
    monkeypatch.setenv("DATABASE_PATH", str(db_path))
    import bot.database as database_module
    import bot.services.partner_approval_service as approval_service_module
    import bot.services.referral_service as referral_service_module

    database = importlib.reload(database_module)
    referral_service = importlib.reload(referral_service_module)
    approval_service = importlib.reload(approval_service_module)
    return database, referral_service, approval_service


async def _seed_application(database, approval, user, status):
    await approval.ensure_partner_approval_schema()
    async with database.db_backend.connect(database.DATABASE_PATH) as db:
        await db.execute(
            """INSERT INTO partner_applications
               (user_id, status, source, requested_at, reviewed_at, reviewed_by_telegram_id)
               VALUES (?, ?, 'legacy', '2026-08-10 12:00:00', ?, ?)""",
            (user.id, status, None if status == "pending" else "2026-08-11 12:00:00",
             None if status == "pending" else 999999999),
        )
        await db.commit()
        cursor = await db.execute("SELECT id FROM partner_applications WHERE user_id = ?", (user.id,))
        return int((await cursor.fetchone())[0])


@pytest.mark.asyncio
@pytest.mark.parametrize("created_at", ["2020-01-01 00:00:00", "2026-10-09 00:00:00"])
async def test_all_accounts_are_partners_without_consent_or_application(tmp_path, monkeypatch, created_at):
    database, _, approval = _reload_partner_modules(monkeypatch, tmp_path / "open-partners.db")
    await database.init_db()
    user = await database.get_or_create_user(810001)
    async with database.db_backend.connect(database.DATABASE_PATH) as db:
        await db.execute("UPDATE users SET created_at = ? WHERE id = ?", (created_at, user.id))
        await db.commit()

    state = await approval.get_partner_application_state(user.telegram_id)

    assert float(user.credits) == float(database.PARTNER_NEW_USER_BONUS) == 5
    assert state["status"] == approval.PARTNER_APPLICATION_APPROVED
    assert state["is_partner"] is True
    assert state["can_apply"] is False
    assert state["application_id"] is None
    assert (await database.get_or_create_user(user.telegram_id)).partner_agreed_at is None


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["pending", "rejected", "approved"])
async def test_historical_applications_do_not_gate_access_or_change(tmp_path, monkeypatch, status):
    database, _, approval = _reload_partner_modules(monkeypatch, tmp_path / "history.db")
    await database.init_db()
    user = await database.get_or_create_user(810002)
    application_id = await _seed_application(database, approval, user, status)
    original = await approval.get_partner_application(application_id)

    state = await approval.get_partner_application_state(user.telegram_id)
    submits = await asyncio.gather(
        approval.submit_partner_application(user.telegram_id, source="miniapp"),
        approval.submit_partner_application(user.telegram_id, source="telegram_bot"),
    )

    assert state["is_partner"] is True
    assert state["status"] == "approved"
    assert state["can_apply"] is False
    assert state["application_status"] == status
    assert state["application_id"] == application_id
    assert all(result["created"] is False and result["is_partner"] for result in submits)
    assert await approval.get_partner_application(application_id) == original
    assert (await database.get_or_create_user(user.telegram_id)).partner_agreed_at is None


@pytest.mark.asyncio
async def test_stale_apply_is_repeatable_without_creating_application(tmp_path, monkeypatch):
    database, _, approval = _reload_partner_modules(monkeypatch, tmp_path / "stale-submit.db")
    await database.init_db()
    user = await database.get_or_create_user(810003)
    results = await asyncio.gather(*[
        approval.submit_partner_application(user.telegram_id, source="miniapp")
        for _ in range(3)
    ])
    assert all(result["ok"] and not result["created"] and result["is_partner"] for result in results)
    assert all(result["application_id"] is None for result in results)
    async with database.db_backend.connect(database.DATABASE_PATH) as db:
        cursor = await db.execute("SELECT COUNT(*) FROM partner_applications")
        assert (await cursor.fetchone())[0] == 0
    assert (await database.get_or_create_user(user.telegram_id)).partner_agreed_at is None


@pytest.mark.asyncio
async def test_historical_consent_is_preserved(tmp_path, monkeypatch):
    database, _, approval = _reload_partner_modules(monkeypatch, tmp_path / "consent.db")
    await database.init_db()
    user = await database.get_or_create_user(810004)
    consent = "2026-06-01 10:11:12"
    async with database.db_backend.connect(database.DATABASE_PATH) as db:
        await db.execute("UPDATE users SET partner_agreed_at = ? WHERE id = ?", (consent, user.id))
        await db.commit()
    await approval.get_partner_application_state(user.telegram_id)
    await approval.submit_partner_application(user.telegram_id, source="telegram_bot")
    assert (await database.get_or_create_user(user.telegram_id)).partner_agreed_at.isoformat(sep=" ") == consent


@pytest.mark.asyncio
@pytest.mark.parametrize("approve", [True, False])
async def test_stale_review_never_changes_history_or_eligibility(tmp_path, monkeypatch, approve):
    database, _, approval = _reload_partner_modules(monkeypatch, tmp_path / "review.db")
    await database.init_db()
    user = await database.get_or_create_user(810005)
    application_id = await _seed_application(database, approval, user, "pending")
    original = await approval.get_partner_application(application_id)
    result = await approval.review_partner_application(
        application_id, approve=approve, admin_telegram_id=999999999,
    )
    assert result["ok"] is False
    assert result["reason"] == "activation_not_required"
    assert await approval.get_partner_application(application_id) == original
    assert (await database.get_or_create_user(user.telegram_id)).partner_agreed_at is None
    assert (await approval.get_partner_application_state(user.telegram_id))["is_partner"] is True


@pytest.mark.asyncio
async def test_review_service_retains_admin_authorization(tmp_path, monkeypatch):
    database, _, approval = _reload_partner_modules(monkeypatch, tmp_path / "unauthorized.db")
    await database.init_db()
    result = await approval.review_partner_application(1, approve=True, admin_telegram_id=810006)
    assert result == {"ok": False, "reason": "forbidden"}


@pytest.mark.asyncio
@pytest.mark.parametrize("historical_status", [None, "pending", "rejected"])
async def test_referral_attaches_without_activation_and_keeps_security(tmp_path, monkeypatch, historical_status):
    database, referral, approval = _reload_partner_modules(monkeypatch, tmp_path / "referral.db")
    await database.init_db()
    referrer = await database.get_or_create_user(810007)
    visitor = await database.get_or_create_user(810008)
    if historical_status:
        await _seed_application(database, approval, referrer, historical_status)
    canonical_click = referral.process_referral_click
    canonical_attach = referral.attach_referral_in_transaction
    approval.install_partner_referral_approval_guard()
    approval.install_partner_referral_approval_guard()
    assert referral.process_referral_click is canonical_click
    assert referral.attach_referral_in_transaction is canonical_attach

    attached = await referral.process_referral_click(visitor.telegram_id, referrer.referral_code, source="test")
    assert attached.attached is True
    assert (await database.get_or_create_user(visitor.telegram_id)).referred_by == referrer.id
    repeated = await referral.process_referral_click(visitor.telegram_id, referrer.referral_code, source="test")
    self_click = await referral.process_referral_click(referrer.telegram_id, referrer.referral_code, source="test")
    missing = await referral.process_referral_click(810009, "DOES_NOT_EXIST", source="test")
    assert repeated.attached is False
    assert self_click.attached is False and self_click.reason == "self_ref"
    assert missing.attached is False and missing.reason == "code_not_found"
    assert (await database.get_or_create_user(referrer.telegram_id)).partner_agreed_at is None


@pytest.mark.asyncio
async def test_open_eligibility_preserves_banned_referrer_block(tmp_path, monkeypatch):
    database, referral, approval = _reload_partner_modules(monkeypatch, tmp_path / "banned.db")
    await database.init_db()
    referrer = await database.get_or_create_user(810010)
    visitor = await database.get_or_create_user(810011)
    async with database.db_backend.connect(database.DATABASE_PATH) as db:
        await db.execute("UPDATE users SET is_banned = 1 WHERE id = ?", (referrer.id,))
        await db.commit()
    approval.install_partner_referral_approval_guard()
    result = await referral.process_referral_click(visitor.telegram_id, referrer.referral_code, source="test")
    assert result.attached is False and result.reason == "blocked_referrer"
    assert (await database.get_or_create_user(visitor.telegram_id)).referred_by is None


def test_telegram_legacy_entry_points_are_intercepted_before_common_router():
    root = Path(__file__).resolve().parents[1]
    handlers = (root / "bot/handlers/__init__.py").read_text(encoding="utf-8")
    approval = (root / "bot/handlers/partner_approval.py").read_text(encoding="utf-8")
    assert handlers.index("common_router.include_router(partner_approval_user_router)") < handlers.index(
        "common_router.include_router(legacy_common_router)"
    )
    for route in ['Command("ref", "earn", "partner")', 'F.data.in_({"menu_referrals", "menu_partner"})',
                  'F.data == "partner_accept"', 'F.data == "partner_stats"']:
        assert route in approval
