import pytest

from bot import database
from bot import db as db_backend


@pytest.mark.asyncio
async def test_admin_counts_new_partners_without_legacy_agreement(monkeypatch):
    from bot.services import referral_service

    monkeypatch.setattr(referral_service, "DATABASE_PATH", database.DATABASE_PATH)
    await referral_service.init_referral_tables_if_needed()
    partner = await database.get_or_create_user(871001)
    visitor = await database.get_or_create_user(871002)
    idle = await database.get_or_create_user(871003)
    async with db_backend.connect() as conn:
        await conn.execute("UPDATE users SET referred_by = ? WHERE id = ?", (partner.id, visitor.id))
        await conn.execute("INSERT INTO referrals(referrer_id, referred_id) VALUES (?, ?)", (partner.id, visitor.id))
        await conn.commit()

    summary = await database.get_admin_partner_stats()
    assert summary["total_partners"] == 3
    assert summary["active_partners"] == 1
    assert summary["top_partners"][0]["telegram_id"] == partner.telegram_id
    for user in (partner, visitor, idle):
        detail = await database.get_admin_partner_details(user.telegram_id)
        assert detail["is_partner"] is True
        assert detail["partner_agreed_at"] is None
        assert detail["overview"]["is_partner"] is True
