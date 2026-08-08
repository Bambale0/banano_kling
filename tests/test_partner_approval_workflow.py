import asyncio
import importlib
from pathlib import Path

import pytest


def _reload_partner_modules(monkeypatch, db_path):
    monkeypatch.setenv("DATABASE_PATH", str(db_path))

    import bot.database as database_module

    database = importlib.reload(database_module)

    import bot.services.referral_service as referral_service_module

    referral_service = importlib.reload(referral_service_module)

    import bot.services.partner_approval_service as approval_service_module

    approval_service = importlib.reload(approval_service_module)

    return database, referral_service, approval_service


@pytest.mark.asyncio
async def test_new_user_keeps_welcome_bonus_and_partner_is_not_active(tmp_path, monkeypatch):
    database, _referral_service, approval = _reload_partner_modules(
        monkeypatch,
        tmp_path / "partner-approval.db",
    )
    await database.init_db()

    user = await database.get_or_create_user(810001)
    state = await approval.get_partner_application_state(user.telegram_id)

    # Product rule: every new account receives the 5-banana welcome bonus.
    assert float(user.credits) == float(database.PARTNER_NEW_USER_BONUS)
    assert database.PARTNER_NEW_USER_BONUS == 5
    assert state["status"] == approval.PARTNER_APPLICATION_AVAILABLE
    assert state["is_partner"] is False
    assert state["can_apply"] is True


@pytest.mark.asyncio
async def test_partner_application_is_idempotent_while_pending(tmp_path, monkeypatch):
    database, _referral_service, approval = _reload_partner_modules(
        monkeypatch,
        tmp_path / "partner-pending.db",
    )
    await database.init_db()
    user = await database.get_or_create_user(810002)

    first = await approval.submit_partner_application(
        user.telegram_id,
        source="miniapp",
    )
    second = await approval.submit_partner_application(
        user.telegram_id,
        source="telegram_bot",
    )

    assert first["status"] == approval.PARTNER_APPLICATION_PENDING
    assert first["created"] is True
    assert second["status"] == approval.PARTNER_APPLICATION_PENDING
    assert second["created"] is False
    assert second["application_id"] == first["application_id"]


@pytest.mark.asyncio
async def test_concurrent_partner_application_has_single_winner(tmp_path, monkeypatch):
    database, _referral_service, approval = _reload_partner_modules(
        monkeypatch,
        tmp_path / "partner-concurrent.db",
    )
    await database.init_db()
    user = await database.get_or_create_user(810008)

    results = await asyncio.gather(
        approval.submit_partner_application(user.telegram_id, source="miniapp"),
        approval.submit_partner_application(user.telegram_id, source="telegram_bot"),
    )

    assert {item["status"] for item in results} == {approval.PARTNER_APPLICATION_PENDING}
    assert sum(bool(item["created"]) for item in results) == 1
    assert len({item["application_id"] for item in results}) == 1


@pytest.mark.asyncio
async def test_admin_approval_activates_existing_partner_financial_flag(tmp_path, monkeypatch):
    database, _referral_service, approval = _reload_partner_modules(
        monkeypatch,
        tmp_path / "partner-approved.db",
    )
    await database.init_db()
    user = await database.get_or_create_user(810003)

    submitted = await approval.submit_partner_application(
        user.telegram_id,
        source="telegram_bot",
    )
    reviewed = await approval.review_partner_application(
        submitted["application_id"],
        approve=True,
        admin_telegram_id=999001,
    )

    updated_user = await database.get_or_create_user(user.telegram_id)
    state = await approval.get_partner_application_state(user.telegram_id)

    assert reviewed["ok"] is True
    assert reviewed["status"] == approval.PARTNER_APPLICATION_APPROVED
    assert updated_user.partner_agreed_at is not None
    assert state["status"] == approval.PARTNER_APPLICATION_APPROVED
    assert state["is_partner"] is True


@pytest.mark.asyncio
async def test_legacy_activated_partner_is_grandfathered_without_application(tmp_path, monkeypatch):
    database, _referral_service, approval = _reload_partner_modules(
        monkeypatch,
        tmp_path / "partner-legacy.db",
    )
    await database.init_db()
    user = await database.get_or_create_user(810009)

    assert await database.accept_partner_agreement(user.telegram_id) is True

    state = await approval.get_partner_application_state(user.telegram_id)
    submitted = await approval.submit_partner_application(
        user.telegram_id,
        source="telegram_bot",
    )

    assert state["status"] == approval.PARTNER_APPLICATION_APPROVED
    assert state["is_partner"] is True
    assert state["application_id"] is None
    assert submitted["status"] == approval.PARTNER_APPLICATION_APPROVED
    assert submitted["created"] is False
    assert submitted["application_id"] is None


@pytest.mark.asyncio
async def test_rejected_partner_can_submit_again(tmp_path, monkeypatch):
    database, _referral_service, approval = _reload_partner_modules(
        monkeypatch,
        tmp_path / "partner-rejected.db",
    )
    await database.init_db()
    user = await database.get_or_create_user(810004)

    submitted = await approval.submit_partner_application(
        user.telegram_id,
        source="miniapp",
    )
    rejected = await approval.review_partner_application(
        submitted["application_id"],
        approve=False,
        admin_telegram_id=999001,
    )
    rejected_state = await approval.get_partner_application_state(user.telegram_id)

    resubmitted = await approval.submit_partner_application(
        user.telegram_id,
        source="telegram_bot",
    )
    pending_state = await approval.get_partner_application_state(user.telegram_id)

    assert rejected["ok"] is True
    assert rejected_state["status"] == approval.PARTNER_APPLICATION_REJECTED
    assert rejected_state["can_apply"] is True
    assert resubmitted["created"] is True
    assert resubmitted["application_id"] == submitted["application_id"]
    assert pending_state["status"] == approval.PARTNER_APPLICATION_PENDING


@pytest.mark.asyncio
async def test_referral_code_does_not_attach_until_partner_is_approved(tmp_path, monkeypatch):
    database, referral_service, approval = _reload_partner_modules(
        monkeypatch,
        tmp_path / "partner-referral-guard.db",
    )
    await database.init_db()

    referrer = await database.get_or_create_user(810005)
    visitor = await database.get_or_create_user(810006)

    approval.install_partner_referral_approval_guard()

    blocked = await referral_service.process_referral_click(
        visitor.telegram_id,
        referrer.referral_code,
        source="test",
        start_param=f"ref_{referrer.referral_code}",
    )
    visitor_after_block = await database.get_or_create_user(visitor.telegram_id)

    assert blocked.attached is False
    assert blocked.reason == "blocked_referrer"
    assert visitor_after_block.referred_by is None

    submitted = await approval.submit_partner_application(
        referrer.telegram_id,
        source="telegram_bot",
    )
    approved = await approval.review_partner_application(
        submitted["application_id"],
        approve=True,
        admin_telegram_id=999001,
    )
    assert approved["ok"] is True

    attached = await referral_service.process_referral_click(
        visitor.telegram_id,
        referrer.referral_code,
        source="test",
        start_param=f"ref_{referrer.referral_code}",
    )
    visitor_after_approval = await database.get_or_create_user(visitor.telegram_id)

    assert attached.attached is True
    assert attached.reason == "attached"
    assert visitor_after_approval.referred_by == referrer.id


@pytest.mark.asyncio
async def test_rejected_partner_referral_code_remains_blocked(tmp_path, monkeypatch):
    database, referral_service, approval = _reload_partner_modules(
        monkeypatch,
        tmp_path / "partner-rejected-referral.db",
    )
    await database.init_db()

    referrer = await database.get_or_create_user(810010)
    visitor = await database.get_or_create_user(810011)
    approval.install_partner_referral_approval_guard()

    submitted = await approval.submit_partner_application(referrer.telegram_id, source="miniapp")
    rejected = await approval.review_partner_application(
        submitted["application_id"],
        approve=False,
        admin_telegram_id=999001,
    )
    assert rejected["ok"] is True

    blocked = await referral_service.process_referral_click(
        visitor.telegram_id,
        referrer.referral_code,
        source="test",
        start_param=f"ref_{referrer.referral_code}",
    )

    assert blocked.attached is False
    assert blocked.reason == "blocked_referrer"
    assert (await database.get_or_create_user(visitor.telegram_id)).referred_by is None


@pytest.mark.asyncio
async def test_review_is_single_transition_from_pending(tmp_path, monkeypatch):
    database, _referral_service, approval = _reload_partner_modules(
        monkeypatch,
        tmp_path / "partner-review-once.db",
    )
    await database.init_db()
    user = await database.get_or_create_user(810007)
    submitted = await approval.submit_partner_application(
        user.telegram_id,
        source="telegram_bot",
    )

    first = await approval.review_partner_application(
        submitted["application_id"],
        approve=True,
        admin_telegram_id=999001,
    )
    second = await approval.review_partner_application(
        submitted["application_id"],
        approve=False,
        admin_telegram_id=999002,
    )

    assert first["ok"] is True
    assert first["status"] == approval.PARTNER_APPLICATION_APPROVED
    assert second["ok"] is False
    assert second["reason"] == "already_processed"
    assert second["status"] == approval.PARTNER_APPLICATION_APPROVED


def test_telegram_legacy_entry_points_are_intercepted_before_common_router():
    handlers_source = (
        Path(__file__).resolve().parents[1] / "bot" / "handlers" / "__init__.py"
    ).read_text(encoding="utf-8")
    approval_source = (
        Path(__file__).resolve().parents[1] / "bot" / "handlers" / "partner_approval.py"
    ).read_text(encoding="utf-8")

    assert "common_router.include_router(partner_approval_user_router)" in handlers_source
    assert handlers_source.index("common_router.include_router(partner_approval_user_router)") < handlers_source.index(
        "common_router.include_router(legacy_common_router)"
    )
    assert 'Command("ref", "earn", "partner")' in approval_source
    assert 'F.data.in_({"menu_referrals", "menu_partner"})' in approval_source
    assert 'F.data == "partner_accept"' in approval_source
    assert 'F.data == "partner_stats"' in approval_source


def test_miniapp_partner_ui_requires_explicit_application_action():
    root = Path(__file__).resolve().parents[1]
    source = (
        root
        / "frontend"
        / "miniapp-v0"
        / "components"
        / "partner-approval-sheet.tsx"
    ).read_text(encoding="utf-8")
    shell_source = (
        root / "frontend" / "miniapp-v0" / "components" / "mini-app-shell.tsx"
    ).read_text(encoding="utf-8")

    assert "executeMiniAppAction('partner_apply')" in source
    assert "Активировать ссылку" in source
    assert "Заявка на рассмотрении" in source
    assert "Заявка отклонена" in source
    assert "Партнёрский кабинет активирован" in source
    assert "<PartnerApprovalSheet />" in shell_source


def test_miniapp_backend_intercepts_partner_overview_and_action_server_side():
    source = (
        Path(__file__).resolve().parents[1]
        / "bot"
        / "handlers"
        / "miniapp_regression_safety.py"
    ).read_text(encoding="utf-8")

    assert 'endswith("/api/partner-overview")' in source
    assert 'endswith("/api/action")' in source
    assert '"partner_apply"' in source
    assert "_partner_action_with_approval" in source
    assert 'payload["referral_link"] = ""' in source
    assert 'payload["referral_bot_link"] = ""' in source
