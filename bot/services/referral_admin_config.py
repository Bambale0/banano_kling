"""Admin-facing referral, partner, and antifraud configuration service."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol


CONFIG_SETTING_KEY = "referral_admin_config"
PAYOUTS_SETTING_KEY = "referral_partner_payouts"

BONUS_TRIGGERS = {"signup", "first_payment"}
PAYOUT_STATUSES = {"pending", "paid", "frozen"}


@dataclass(frozen=True)
class AntiFraudRule:
    key: str
    title: str
    enabled: bool = True
    threshold: int = 1
    window_hours: int = 24
    action: str = "flag"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AntiFraudRule":
        return cls(
            key=str(data.get("key", "")).strip(),
            title=str(data.get("title", "")).strip(),
            enabled=bool(data.get("enabled", True)),
            threshold=max(0, int(data.get("threshold", 1))),
            window_hours=max(1, int(data.get("window_hours", 24))),
            action=str(data.get("action", "flag")).strip() or "flag",
        )

    def validate(self) -> None:
        if not self.key:
            raise ValueError("Anti-fraud rule key is required")
        if not self.title:
            raise ValueError("Anti-fraud rule title is required")
        if self.threshold < 0:
            raise ValueError("Anti-fraud rule threshold must be non-negative")
        if self.window_hours <= 0:
            raise ValueError("Anti-fraud rule window must be positive")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


DEFAULT_ANTIFRAUD_RULES: tuple[AntiFraudRule, ...] = (
    AntiFraudRule(
        key="same_device_accounts",
        title="Много аккаунтов с одного устройства",
        threshold=3,
        window_hours=24,
        action="flag",
    ),
    AntiFraudRule(
        key="referrals_without_payments",
        title="Рефералы без оплат",
        threshold=10,
        window_hours=168,
        action="flag",
    ),
    AntiFraudRule(
        key="promo_abuse",
        title="Подозрительное использование промокодов",
        threshold=5,
        window_hours=24,
        action="flag",
    ),
    AntiFraudRule(
        key="free_generation_reuse",
        title="Повторное использование бесплатных генераций",
        threshold=3,
        window_hours=24,
        action="limit",
    ),
    AntiFraudRule(
        key="partner_fraud",
        title="Некачественный партнёрский трафик",
        threshold=20,
        window_hours=168,
        action="freeze",
    ),
)


@dataclass(frozen=True)
class ReferralAdminConfig:
    referrer_bonus_credits: int = 30
    friend_bonus_credits: int = 30
    bonus_trigger: str = "first_payment"
    daily_referral_limit: int = 20
    antifraud_rules: list[AntiFraudRule] = field(
        default_factory=lambda: list(DEFAULT_ANTIFRAUD_RULES)
    )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ReferralAdminConfig":
        rules_data = data.get("antifraud_rules")
        if not isinstance(rules_data, list):
            rules = list(DEFAULT_ANTIFRAUD_RULES)
        else:
            rules = []
            for item in rules_data:
                if isinstance(item, AntiFraudRule):
                    rules.append(item)
                elif isinstance(item, dict):
                    rules.append(AntiFraudRule.from_dict(item))

        config = cls(
            referrer_bonus_credits=max(0, int(data.get("referrer_bonus_credits", 30))),
            friend_bonus_credits=max(0, int(data.get("friend_bonus_credits", 30))),
            bonus_trigger=str(data.get("bonus_trigger", "first_payment")),
            daily_referral_limit=max(0, int(data.get("daily_referral_limit", 20))),
            antifraud_rules=rules,
        )
        config.validate()
        return config

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def validate(self) -> None:
        if self.referrer_bonus_credits < 0:
            raise ValueError("Referrer bonus must be non-negative")
        if self.friend_bonus_credits < 0:
            raise ValueError("Friend bonus must be non-negative")
        if self.bonus_trigger not in BONUS_TRIGGERS:
            raise ValueError("Bonus trigger must be signup or first_payment")
        if self.daily_referral_limit < 0:
            raise ValueError("Daily referral limit must be non-negative")
        keys = set()
        for rule in self.antifraud_rules:
            rule.validate()
            if rule.key in keys:
                raise ValueError(f"Duplicate anti-fraud rule key: {rule.key}")
            keys.add(rule.key)

    def with_updates(self, **updates: Any) -> "ReferralAdminConfig":
        data = self.to_dict()
        data.update(updates)
        return ReferralAdminConfig.from_dict(data)


@dataclass(frozen=True)
class PartnerSummary:
    partner: str
    users_count: int
    payments_count: int
    revenue_rub: float
    commission_rub: float
    promo_code: str
    referral_link: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PartnerPayout:
    id: int
    partner: str
    amount_rub: float
    status: str = "pending"
    revenue_rub: float = 0.0
    commission_percent: float = 0.0
    comment: str = ""
    created_at: str = field(default_factory=lambda: _utc_now_iso())
    updated_at: str = field(default_factory=lambda: _utc_now_iso())

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PartnerPayout":
        payout = cls(
            id=int(data.get("id", 0)),
            partner=str(data.get("partner", "")).strip(),
            amount_rub=round(float(data.get("amount_rub", 0)), 2),
            status=str(data.get("status", "pending")),
            revenue_rub=round(float(data.get("revenue_rub", 0)), 2),
            commission_percent=round(float(data.get("commission_percent", 0)), 2),
            comment=str(data.get("comment", "")),
            created_at=str(data.get("created_at") or _utc_now_iso()),
            updated_at=str(data.get("updated_at") or _utc_now_iso()),
        )
        payout.validate()
        return payout

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def validate(self) -> None:
        if self.id < 0:
            raise ValueError("Payout id must be non-negative")
        if not self.partner:
            raise ValueError("Payout partner is required")
        if self.amount_rub < 0:
            raise ValueError("Payout amount must be non-negative")
        if self.status not in PAYOUT_STATUSES:
            raise ValueError("Payout status must be pending, paid, or frozen")

    def with_status(self, status: str, comment: str | None = None) -> "PartnerPayout":
        data = self.to_dict()
        data["status"] = status
        data["updated_at"] = _utc_now_iso()
        if comment is not None:
            data["comment"] = comment
        return PartnerPayout.from_dict(data)


class ReferralSettingsStore(Protocol):
    async def get(self, key: str, default: str = "") -> str:
        ...

    async def set(self, key: str, value: str) -> None:
        ...


class BotSettingsStore:
    """JSON storage adapter over bot_settings via bot.database helpers."""

    async def get(self, key: str, default: str = "") -> str:
        from bot.database import get_bot_setting

        return await get_bot_setting(key, default)

    async def set(self, key: str, value: str) -> None:
        from bot.database import set_bot_setting

        await set_bot_setting(key, value)


class ReferralAdminConfigService:
    def __init__(self, store: ReferralSettingsStore | None = None) -> None:
        self.store = store or BotSettingsStore()

    async def get_config(self) -> ReferralAdminConfig:
        raw = await self.store.get(CONFIG_SETTING_KEY, "")
        if not raw:
            return ReferralAdminConfig()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return ReferralAdminConfig()
        if not isinstance(data, dict):
            return ReferralAdminConfig()
        return ReferralAdminConfig.from_dict(data)

    async def save_config(self, config: ReferralAdminConfig) -> ReferralAdminConfig:
        config.validate()
        await self.store.set(
            CONFIG_SETTING_KEY,
            json.dumps(config.to_dict(), ensure_ascii=False, sort_keys=True),
        )
        return config

    async def update_config(self, **updates: Any) -> ReferralAdminConfig:
        config = await self.get_config()
        return await self.save_config(config.with_updates(**updates))

    async def set_antifraud_rule_enabled(
        self, rule_key: str, enabled: bool
    ) -> ReferralAdminConfig:
        config = await self.get_config()
        rules = [
            AntiFraudRule.from_dict({**rule.to_dict(), "enabled": enabled})
            if rule.key == rule_key
            else rule
            for rule in config.antifraud_rules
        ]
        if not any(rule.key == rule_key for rule in config.antifraud_rules):
            raise ValueError(f"Unknown anti-fraud rule: {rule_key}")
        return await self.save_config(config.with_updates(antifraud_rules=rules))

    def build_partner_summary(
        self,
        *,
        partner: str,
        users_count: int,
        payments_count: int,
        revenue_rub: float,
        commission_rub: float,
        promo_code: str,
        referral_link: str,
    ) -> PartnerSummary:
        return PartnerSummary(
            partner=partner,
            users_count=max(0, int(users_count)),
            payments_count=max(0, int(payments_count)),
            revenue_rub=round(float(revenue_rub), 2),
            commission_rub=round(float(commission_rub), 2),
            promo_code=promo_code,
            referral_link=referral_link,
        )

    async def list_payouts(self) -> list[PartnerPayout]:
        raw = await self.store.get(PAYOUTS_SETTING_KEY, "[]")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = []
        if not isinstance(data, list):
            data = []
        return [
            PartnerPayout.from_dict(item)
            for item in data
            if isinstance(item, dict)
        ]

    async def save_payouts(self, payouts: list[PartnerPayout]) -> list[PartnerPayout]:
        for payout in payouts:
            payout.validate()
        await self.store.set(
            PAYOUTS_SETTING_KEY,
            json.dumps([payout.to_dict() for payout in payouts], ensure_ascii=False, sort_keys=True),
        )
        return payouts

    async def create_payout(
        self,
        *,
        partner: str,
        amount_rub: float,
        revenue_rub: float = 0.0,
        commission_percent: float = 0.0,
        comment: str = "",
    ) -> PartnerPayout:
        payouts = await self.list_payouts()
        next_id = max((payout.id for payout in payouts), default=0) + 1
        payout = PartnerPayout(
            id=next_id,
            partner=partner,
            amount_rub=round(float(amount_rub), 2),
            revenue_rub=round(float(revenue_rub), 2),
            commission_percent=round(float(commission_percent), 2),
            comment=comment,
        )
        await self.save_payouts([*payouts, payout])
        return payout

    async def update_payout_status(
        self, payout_id: int, status: str, comment: str | None = None
    ) -> PartnerPayout | None:
        payouts = await self.list_payouts()
        updated: PartnerPayout | None = None
        next_payouts: list[PartnerPayout] = []
        for payout in payouts:
            if payout.id == payout_id:
                updated = payout.with_status(status, comment)
                next_payouts.append(updated)
            else:
                next_payouts.append(payout)
        if updated is None:
            return None
        await self.save_payouts(next_payouts)
        return updated


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


referral_admin_config_service = ReferralAdminConfigService()
