from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

import aiosqlite

from bot import database


PUSH_SCENARIO_CONFIG_KEY = "push_scenarios_config"
PUSH_SCENARIO_STATE_KEY = "push_scenarios_state"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _sqlite_timestamp(value: datetime) -> str:
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value.strftime("%Y-%m-%d %H:%M:%S")


@dataclass(frozen=True)
class PushScenarioRule:
    key: str
    title: str
    delay: timedelta
    template: str
    enabled: bool = True
    bonus_credits: int = 0
    promo_code: str | None = None
    package_code: str | None = None

    def to_json(self) -> dict[str, Any]:
        data = asdict(self)
        data["delay_seconds"] = int(self.delay.total_seconds())
        data.pop("delay")
        return data

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "PushScenarioRule":
        return cls(
            key=str(data["key"]),
            title=str(data["title"]),
            delay=timedelta(seconds=int(data.get("delay_seconds", 0))),
            template=str(data.get("template", "")),
            enabled=bool(data.get("enabled", True)),
            bonus_credits=int(data.get("bonus_credits", 0) or 0),
            promo_code=data.get("promo_code"),
            package_code=data.get("package_code"),
        )


@dataclass(frozen=True)
class PushScenarioConfig:
    enabled: bool = True
    rules: tuple[PushScenarioRule, ...] = field(default_factory=tuple)

    @classmethod
    def defaults(cls) -> "PushScenarioConfig":
        return cls(
            rules=(
                PushScenarioRule(
                    key="generation_abandoned",
                    title="Не завершил генерацию",
                    delay=timedelta(hours=1),
                    template=(
                        "Похоже, генерация зависла или не была завершена. "
                        "Вернитесь в бот и попробуйте еще раз."
                    ),
                ),
                PushScenarioRule(
                    key="payment_abandoned",
                    title="Не оплатил",
                    delay=timedelta(hours=24),
                    template=(
                        "Дарим бонус, чтобы проще было попробовать генерацию."
                    ),
                    bonus_credits=1,
                ),
                PushScenarioRule(
                    key="inactive_user",
                    title="Давно не заходил",
                    delay=timedelta(days=7),
                    template=(
                        "Мы соскучились. Возвращайтесь за новой генерацией "
                        "с персональным промокодом."
                    ),
                    promo_code="COMEBACK7",
                ),
                PushScenarioRule(
                    key="first_generation_success",
                    title="Первая генерация успешна",
                    delay=timedelta(),
                    template=(
                        "Первая генерация готова. Самое время выбрать пакет "
                        "для следующих идей."
                    ),
                    package_code="starter",
                ),
            )
        )

    def get_rule(self, key: str) -> PushScenarioRule | None:
        return next((rule for rule in self.rules if rule.key == key), None)

    def to_json(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "rules": [rule.to_json() for rule in self.rules],
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "PushScenarioConfig":
        default_rules = {rule.key: rule for rule in cls.defaults().rules}
        raw_rules = data.get("rules") or []
        rules: list[PushScenarioRule] = []

        for raw_rule in raw_rules:
            if not isinstance(raw_rule, dict) or "key" not in raw_rule:
                continue
            base = default_rules.get(str(raw_rule["key"]))
            merged = base.to_json() if base else {}
            merged.update(raw_rule)
            rules.append(PushScenarioRule.from_json(merged))

        seen = {rule.key for rule in rules}
        rules.extend(rule for key, rule in default_rules.items() if key not in seen)

        return cls(
            enabled=bool(data.get("enabled", True)),
            rules=tuple(rules),
        )


@dataclass(frozen=True)
class PushScenarioEvent:
    scenario_key: str
    user_id: int
    telegram_id: int
    due_at: datetime
    event_key: str
    title: str
    message: str
    payload: dict[str, Any] = field(default_factory=dict)


class JsonSettingsStore(Protocol):
    async def get_json(self, key: str, default: dict[str, Any]) -> dict[str, Any]:
        ...

    async def set_json(self, key: str, value: dict[str, Any]) -> None:
        ...


class BotSettingsJsonStore:
    async def get_json(self, key: str, default: dict[str, Any]) -> dict[str, Any]:
        raw_value = await database.get_bot_setting(
            key, json.dumps(default, ensure_ascii=False)
        )
        try:
            value = json.loads(raw_value)
        except (TypeError, json.JSONDecodeError):
            return default
        return value if isinstance(value, dict) else default

    async def set_json(self, key: str, value: dict[str, Any]) -> None:
        await database.set_bot_setting(key, json.dumps(value, ensure_ascii=False))


class PushScenarioService:
    def __init__(self, store: JsonSettingsStore | None = None) -> None:
        self.store = store or BotSettingsJsonStore()

    async def get_config(self) -> PushScenarioConfig:
        raw_config = await self.store.get_json(
            PUSH_SCENARIO_CONFIG_KEY, PushScenarioConfig.defaults().to_json()
        )
        return PushScenarioConfig.from_json(raw_config)

    async def save_config(self, config: PushScenarioConfig) -> None:
        await self.store.set_json(PUSH_SCENARIO_CONFIG_KEY, config.to_json())

    async def set_enabled(self, enabled: bool) -> PushScenarioConfig:
        current = await self.get_config()
        updated = PushScenarioConfig(enabled=enabled, rules=current.rules)
        await self.save_config(updated)
        return updated

    async def collect_due_events(
        self,
        *,
        now: datetime | None = None,
        limit: int = 100,
        mark_enqueued: bool = False,
    ) -> list[PushScenarioEvent]:
        now = now or _utc_now()
        config = await self.get_config()
        if not config.enabled or limit <= 0:
            return []

        state = await self._get_state()
        emitted = state.setdefault("emitted", {})
        events: list[PushScenarioEvent] = []

        for rule in config.rules:
            if not rule.enabled:
                continue

            candidates = await self._scenario_candidates(rule, now, limit)
            for candidate in candidates:
                if len(events) >= limit:
                    break
                event_key = self._event_key(rule.key, candidate)
                if event_key in emitted:
                    continue
                events.append(self._build_event(rule, candidate, event_key))

            if len(events) >= limit:
                break

        if mark_enqueued and events:
            stamp = now.isoformat()
            for event in events:
                emitted[event.event_key] = {
                    "scenario_key": event.scenario_key,
                    "user_id": event.user_id,
                    "telegram_id": event.telegram_id,
                    "enqueued_at": stamp,
                }
            state["last_collected_at"] = stamp
            await self._save_state(state)

        return events

    async def mark_event_sent(
        self,
        event: PushScenarioEvent,
        *,
        sent_at: datetime | None = None,
    ) -> None:
        sent_at = sent_at or _utc_now()
        state = await self._get_state()
        emitted = state.setdefault("emitted", {})
        emitted[event.event_key] = {
            "scenario_key": event.scenario_key,
            "user_id": event.user_id,
            "telegram_id": event.telegram_id,
            "sent_at": sent_at.isoformat(),
        }
        await self._save_state(state)

    async def was_user_contacted_recently(
        self,
        telegram_id: int,
        *,
        now: datetime | None = None,
        cooldown_seconds: int = 86400,
    ) -> bool:
        if cooldown_seconds <= 0:
            return False
        now = now or _utc_now()
        state = await self._get_state()
        contacted = state.setdefault("user_contacted", {})
        raw_value = contacted.get(str(telegram_id))
        if not raw_value:
            return False
        try:
            contacted_at = self._parse_db_datetime(raw_value)
        except (TypeError, ValueError):
            return False
        return (now - contacted_at).total_seconds() < cooldown_seconds

    async def mark_user_contacted(
        self,
        telegram_id: int,
        *,
        contacted_at: datetime | None = None,
    ) -> None:
        contacted_at = contacted_at or _utc_now()
        state = await self._get_state()
        contacted = state.setdefault("user_contacted", {})
        contacted[str(telegram_id)] = contacted_at.isoformat()
        await self._save_state(state)

    async def reset_state(self) -> None:
        await self._save_state({"emitted": {}})

    async def _get_state(self) -> dict[str, Any]:
        return await self.store.get_json(PUSH_SCENARIO_STATE_KEY, {"emitted": {}})

    async def _save_state(self, state: dict[str, Any]) -> None:
        await self.store.set_json(PUSH_SCENARIO_STATE_KEY, state)

    async def _scenario_candidates(
        self,
        rule: PushScenarioRule,
        now: datetime,
        limit: int,
    ) -> list[dict[str, Any]]:
        handler = {
            "generation_abandoned": self._abandoned_generation_candidates,
            "payment_abandoned": self._payment_abandoned_candidates,
            "inactive_user": self._inactive_user_candidates,
            "first_generation_success": self._first_generation_success_candidates,
        }.get(rule.key)
        if handler is None:
            return []
        threshold = now - rule.delay
        return await handler(threshold, limit)

    async def _abandoned_generation_candidates(
        self, threshold: datetime, limit: int
    ) -> list[dict[str, Any]]:
        async with aiosqlite.connect(database.DATABASE_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT gt.id, gt.user_id, gt.telegram_id, gt.task_id, gt.created_at
                FROM generation_tasks gt
                WHERE gt.telegram_id IS NOT NULL
                  AND gt.status NOT IN ('completed', 'failed')
                  AND gt.created_at <= ?
                ORDER BY gt.created_at ASC
                LIMIT ?
                """,
                (_sqlite_timestamp(threshold), limit),
            )
            return [dict(row) for row in await cursor.fetchall()]

    async def _payment_abandoned_candidates(
        self, threshold: datetime, limit: int
    ) -> list[dict[str, Any]]:
        async with aiosqlite.connect(database.DATABASE_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT u.id AS user_id, u.telegram_id, u.created_at
                FROM users u
                WHERE COALESCE(u.has_paid, 0) = 0
                  AND u.created_at <= ?
                  AND NOT EXISTS (
                      SELECT 1
                      FROM transactions t
                      WHERE t.user_id = u.id
                        AND t.status = 'completed'
                  )
                ORDER BY u.created_at ASC
                LIMIT ?
                """,
                (_sqlite_timestamp(threshold), limit),
            )
            return [dict(row) for row in await cursor.fetchall()]

    async def _inactive_user_candidates(
        self, threshold: datetime, limit: int
    ) -> list[dict[str, Any]]:
        async with aiosqlite.connect(database.DATABASE_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT u.id AS user_id, u.telegram_id, u.updated_at
                FROM users u
                WHERE u.updated_at <= ?
                ORDER BY u.updated_at ASC
                LIMIT ?
                """,
                (_sqlite_timestamp(threshold), limit),
            )
            return [dict(row) for row in await cursor.fetchall()]

    async def _first_generation_success_candidates(
        self, threshold: datetime, limit: int
    ) -> list[dict[str, Any]]:
        async with aiosqlite.connect(database.DATABASE_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT
                    gt.user_id,
                    gt.telegram_id,
                    MIN(gt.task_id) AS task_id,
                    MIN(COALESCE(gt.completed_at, gt.created_at)) AS completed_at,
                    COUNT(*) AS completed_count
                FROM generation_tasks gt
                WHERE gt.telegram_id IS NOT NULL
                  AND gt.status = 'completed'
                  AND COALESCE(gt.completed_at, gt.created_at) <= ?
                GROUP BY gt.user_id, gt.telegram_id
                HAVING completed_count = 1
                ORDER BY completed_at ASC
                LIMIT ?
                """,
                (_sqlite_timestamp(threshold), limit),
            )
            return [dict(row) for row in await cursor.fetchall()]

    def _event_key(self, scenario_key: str, candidate: dict[str, Any]) -> str:
        user_id = int(candidate["user_id"])
        if scenario_key == "generation_abandoned":
            return f"{scenario_key}:{user_id}:{candidate['task_id']}"
        if scenario_key == "first_generation_success":
            return f"{scenario_key}:{user_id}:{candidate['task_id']}"
        return f"{scenario_key}:{user_id}"

    def _build_event(
        self,
        rule: PushScenarioRule,
        candidate: dict[str, Any],
        event_key: str,
    ) -> PushScenarioEvent:
        payload: dict[str, Any] = {}
        for key in ("task_id", "bonus_credits", "promo_code", "package_code"):
            value = candidate.get(key, getattr(rule, key, None))
            if value not in (None, "", 0):
                payload[key] = value

        source_due_at = (
            candidate.get("created_at")
            or candidate.get("updated_at")
            or candidate.get("completed_at")
        )
        due_at = self._parse_db_datetime(source_due_at) + rule.delay

        return PushScenarioEvent(
            scenario_key=rule.key,
            user_id=int(candidate["user_id"]),
            telegram_id=int(candidate["telegram_id"]),
            due_at=due_at,
            event_key=event_key,
            title=rule.title,
            message=rule.template,
            payload=payload,
        )

    def _parse_db_datetime(self, value: Any) -> datetime:
        if isinstance(value, datetime):
            if value.tzinfo is None:
                return value.replace(tzinfo=timezone.utc)
            return value.astimezone(timezone.utc)
        text = str(value or _sqlite_timestamp(_utc_now()))
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)


push_scenario_service = PushScenarioService()
