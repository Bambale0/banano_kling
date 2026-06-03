import importlib

import pytest

from bot.services.referral_admin_config import (
    CONFIG_SETTING_KEY,
    PAYOUTS_SETTING_KEY,
    AntiFraudRule,
    PartnerPayout,
    ReferralAdminConfig,
    ReferralAdminConfigService,
)


class MemorySettingsStore:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    async def get(self, key: str, default: str = "") -> str:
        return self.values.get(key, default)

    async def set(self, key: str, value: str) -> None:
        self.values[key] = value


@pytest.mark.asyncio
async def test_default_config_is_returned_when_setting_is_missing():
    service = ReferralAdminConfigService(MemorySettingsStore())

    config = await service.get_config()

    assert config.referrer_bonus_credits == 30
    assert config.friend_bonus_credits == 30
    assert config.bonus_trigger == "first_payment"
    assert config.daily_referral_limit == 20
    assert {rule.key for rule in config.antifraud_rules} == {
        "same_device_accounts",
        "referrals_without_payments",
        "promo_abuse",
        "free_generation_reuse",
        "partner_fraud",
    }


@pytest.mark.asyncio
async def test_config_is_saved_as_json_and_loaded_back():
    store = MemorySettingsStore()
    service = ReferralAdminConfigService(store)

    saved = await service.save_config(
        ReferralAdminConfig(
            referrer_bonus_credits=12,
            friend_bonus_credits=7,
            bonus_trigger="signup",
            daily_referral_limit=3,
            antifraud_rules=[
                AntiFraudRule(
                    key="same_device_accounts",
                    title="Same device",
                    enabled=False,
                    threshold=2,
                    window_hours=12,
                    action="freeze",
                )
            ],
        )
    )
    loaded = await service.get_config()

    assert CONFIG_SETTING_KEY in store.values
    assert loaded == saved
    assert loaded.antifraud_rules[0].enabled is False
    assert loaded.antifraud_rules[0].action == "freeze"


@pytest.mark.asyncio
async def test_update_config_validates_bonus_trigger():
    service = ReferralAdminConfigService(MemorySettingsStore())

    with pytest.raises(ValueError, match="Bonus trigger"):
        await service.update_config(bonus_trigger="payment_every_time")


@pytest.mark.asyncio
async def test_toggle_antifraud_rule_enabled():
    service = ReferralAdminConfigService(MemorySettingsStore())

    updated = await service.set_antifraud_rule_enabled("partner_fraud", False)
    partner_rule = next(rule for rule in updated.antifraud_rules if rule.key == "partner_fraud")

    assert partner_rule.enabled is False

    with pytest.raises(ValueError, match="Unknown anti-fraud rule"):
        await service.set_antifraud_rule_enabled("missing_rule", True)


def test_partner_summary_structure_is_read_only_data_model():
    service = ReferralAdminConfigService(MemorySettingsStore())

    summary = service.build_partner_summary(
        partner="partner-1",
        users_count=4,
        payments_count=2,
        revenue_rub=1500.129,
        commission_rub=675.555,
        promo_code="BANANA",
        referral_link="https://t.me/test_bot?start=BANANA",
    )

    assert summary.to_dict() == {
        "partner": "partner-1",
        "users_count": 4,
        "payments_count": 2,
        "revenue_rub": 1500.13,
        "commission_rub": 675.55,
        "promo_code": "BANANA",
        "referral_link": "https://t.me/test_bot?start=BANANA",
    }


@pytest.mark.asyncio
async def test_payouts_support_pending_paid_and_frozen_statuses():
    store = MemorySettingsStore()
    service = ReferralAdminConfigService(store)

    payout = await service.create_payout(
        partner="partner-1",
        amount_rub=1000,
        revenue_rub=2000,
        commission_percent=50,
        comment="first payout",
    )
    paid = await service.update_payout_status(payout.id, "paid", "sent")
    frozen = await service.create_payout(partner="partner-2", amount_rub=500)
    frozen = await service.update_payout_status(frozen.id, "frozen", "fraud review")

    payouts = await service.list_payouts()

    assert PAYOUTS_SETTING_KEY in store.values
    assert payout.status == "pending"
    assert paid is not None
    assert paid.status == "paid"
    assert frozen is not None
    assert frozen.status == "frozen"
    assert [item.status for item in payouts] == ["paid", "frozen"]


def test_payout_rejects_unknown_status():
    with pytest.raises(ValueError, match="Payout status"):
        PartnerPayout(id=1, partner="partner-1", amount_rub=100, status="done").validate()


@pytest.mark.asyncio
async def test_service_works_with_sqlite_bot_settings_runtime(tmp_path, monkeypatch):
    db_path = tmp_path / "settings.db"
    monkeypatch.setenv("DATABASE_PATH", str(db_path))

    import bot.database as database

    database = importlib.reload(database)
    await database.init_db()

    service = ReferralAdminConfigService()
    await service.update_config(
        referrer_bonus_credits=9,
        friend_bonus_credits=4,
        bonus_trigger="signup",
        daily_referral_limit=11,
    )

    loaded = await service.get_config()

    assert loaded.referrer_bonus_credits == 9
    assert loaded.friend_bonus_credits == 4
    assert loaded.bonus_trigger == "signup"
    assert loaded.daily_referral_limit == 11
