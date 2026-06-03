"""Admin AI planner for safe natural-language bot management."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

import aiohttp

from bot.config import config

logger = logging.getLogger(__name__)


READ_ONLY_ACTIONS = {
    "stats",
    "user_info",
    "maintenance_status",
    "list_promos",
    "bot_report",
    "analyze_logs",
    "research_ai",
    "help",
}
MUTATING_ACTIONS = {
    "add_credits",
    "deduct_credits",
    "ban_user",
    "unban_user",
    "maintenance_set",
    "create_promo",
    "deactivate_promo",
}
SUPPORTED_ACTIONS = READ_ONLY_ACTIONS | MUTATING_ACTIONS | {"export_users", "clear_context"}


class AdminAIService:
    """Turns an admin's natural-language request into a safe action plan."""

    ENDPOINT = "/gpt-5-2/v1/chat/completions"

    def __init__(self) -> None:
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60))
        return self._session

    async def plan_action(self, admin_message: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        """Return a normalized action plan. Falls back to deterministic parsing."""
        fallback = self._fallback_plan(admin_message)
        if not config.KIE_AI_API_KEY:
            return fallback

        ai_plan = await self._ask_model(admin_message, context or {})
        if not ai_plan:
            return fallback

        normalized = self._normalize_plan(ai_plan)
        if normalized.get("action") == "unknown" and fallback.get("action") != "unknown":
            return fallback
        return normalized

    async def _ask_model(self, admin_message: str, context: dict[str, Any]) -> dict[str, Any] | None:
        session = await self._get_session()
        headers = {
            "Authorization": f"Bearer {config.KIE_AI_API_KEY}",
            "Content-Type": "application/json",
        }
        payload = {
            "messages": [
                {
                    "role": "developer",
                    "content": [
                        {
                            "type": "text",
                            "text": self._system_prompt(),
                        }
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(
                                {"request": admin_message, "context": context},
                                ensure_ascii=False,
                            ),
                        }
                    ],
                },
            ],
            "stream": False,
            "reasoning_effort": "low",
        }
        try:
            async with session.post(
                f"{config.KIE_BASE_URL}{self.ENDPOINT}",
                headers=headers,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=45),
            ) as response:
                text = await response.text()
                if response.status != 200:
                    logger.warning("Admin AI planner failed %s: %s", response.status, text[:500])
                    return None
                data = json.loads(text)
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                if isinstance(content, list):
                    content = "\n".join(
                        item.get("text", "") for item in content if isinstance(item, dict)
                    )
                return self._extract_json(str(content))
        except (aiohttp.ClientError, asyncio.TimeoutError, json.JSONDecodeError) as exc:
            logger.warning("Admin AI planner request failed: %r", exc)
            return None

    def _system_prompt(self) -> str:
        return """
Ты планировщик админ-действий Telegram-бота Banana Boom.
Верни СТРОГО один JSON без markdown.

Схема:
{
  "action": "stats|user_info|add_credits|deduct_credits|ban_user|unban_user|maintenance_status|maintenance_set|create_promo|deactivate_promo|list_promos|export_users|bot_report|analyze_logs|research_ai|clear_context|help|unknown",
  "params": {},
  "actions": [{"action": "...", "params": {}, "summary": "..."}],
  "summary": "короткое описание для админа",
  "confidence": 0.0-1.0
}

Параметры:
- user_info/ban_user/unban_user/add_credits/deduct_credits: telegram_id:int
- add_credits/deduct_credits: amount:int
- maintenance_set: enabled:bool
- create_promo: code:str, promo_type:"discount|bananas|generation", value:int, max_uses:int, expires_at:"YYYY-MM-DD"|null
- deactivate_promo: code:str
- analyze_logs: query:str, lines:int
- research_ai: query:str
- bot_report: scope:str

Для сложных запросов верни actions со списком шагов. Например отчёт по боту:
stats -> maintenance_status -> list_promos -> analyze_logs.

Правила безопасности:
- Не придумывай ID, суммы, коды, даты.
- Если параметров не хватает, action="unknown" и summary объясняет, что нужно уточнить.
- Массовую рассылку не выполняй через AI: action="unknown", предложи штатный раздел рассылки.
""".strip()

    def _extract_json(self, content: str) -> dict[str, Any] | None:
        content = content.strip()
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.S)
        match = re.search(r"\{.*\}", content, flags=re.S)
        if not match:
            return None
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None

    def _normalize_plan(self, plan: dict[str, Any]) -> dict[str, Any]:
        action = str(plan.get("action") or "unknown").strip().lower()
        if action not in SUPPORTED_ACTIONS:
            action = "unknown"
        params = plan.get("params") if isinstance(plan.get("params"), dict) else {}
        summary = str(plan.get("summary") or "").strip()
        try:
            confidence = float(plan.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = max(0.0, min(confidence, 1.0))

        actions = plan.get("actions")
        normalized_actions = []
        if isinstance(actions, list):
            for item in actions[:6]:
                if not isinstance(item, dict):
                    continue
                item_action = str(item.get("action") or "").strip().lower()
                if item_action not in SUPPORTED_ACTIONS:
                    continue
                item_params = item.get("params") if isinstance(item.get("params"), dict) else {}
                normalized_actions.append(
                    {
                        "action": item_action,
                        "params": self._clean_params(item_action, item_params),
                        "summary": str(item.get("summary") or self._default_summary(item_action, item_params)),
                    }
                )

        result = {
            "action": action,
            "params": self._clean_params(action, params),
            "summary": summary or self._default_summary(action, params),
            "confidence": confidence,
            "requires_confirmation": action in MUTATING_ACTIONS or action == "export_users",
        }
        if normalized_actions:
            result["actions"] = normalized_actions
            result["requires_confirmation"] = any(
                item["action"] in MUTATING_ACTIONS or item["action"] == "export_users"
                for item in normalized_actions
            )
        return result

    def _clean_params(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        cleaned: dict[str, Any] = {}
        if action in {"user_info", "add_credits", "deduct_credits", "ban_user", "unban_user"}:
            cleaned["telegram_id"] = self._to_int(params.get("telegram_id"))
        if action in {"add_credits", "deduct_credits"}:
            cleaned["amount"] = self._to_int(params.get("amount"))
        if action == "maintenance_set":
            cleaned["enabled"] = bool(params.get("enabled"))
        if action in {"create_promo", "deactivate_promo"}:
            code = re.sub(r"[^A-Za-z0-9_-]", "", str(params.get("code") or "")).upper()
            cleaned["code"] = code
        if action == "create_promo":
            promo_type = str(params.get("promo_type") or "discount").lower()
            if promo_type not in {"discount", "bananas", "generation"}:
                promo_type = "discount"
            cleaned.update(
                {
                    "promo_type": promo_type,
                    "value": self._to_int(params.get("value")),
                    "max_uses": self._to_int(params.get("max_uses")),
                    "expires_at": self._clean_date(params.get("expires_at")),
                }
            )
        if action == "analyze_logs":
            cleaned["query"] = str(params.get("query") or "").strip()[:500]
            cleaned["lines"] = min(self._to_int(params.get("lines")) or 250, 1000)
        if action == "research_ai":
            cleaned["query"] = str(params.get("query") or "").strip()[:500]
        if action == "bot_report":
            cleaned["scope"] = str(params.get("scope") or "health").strip()[:80]
        return cleaned

    def _fallback_plan(self, text: str) -> dict[str, Any]:
        normalized = " ".join((text or "").strip().lower().split())
        params: dict[str, Any] = {}
        action = "unknown"

        user_id = self._find_user_id(normalized)
        amount = self._find_amount(normalized)

        if "контекст" in normalized and any(word in normalized for word in ("очист", "сброс")):
            action = "clear_context"
        elif any(word in normalized for word in ("отчет", "отчёт", "сводк", "состояние бота", "health")):
            action = "bot_report"
            params["scope"] = normalized[:80]
        elif any(word in normalized for word in ("лог", "ошибк", "почему упал", "упал", "traceback")):
            action = "analyze_logs"
            params["query"] = normalized
            params["lines"] = amount or 250
        elif any(phrase in normalized for phrase in ("новые ии", "новые ai", "новые модели", "рынок ии", "генерации контента", "content generation")):
            action = "research_ai"
            params["query"] = normalized
        elif any(word in normalized for word in ("статист", "выручк", "сколько пользовател")):
            action = "stats"
        elif "экспорт" in normalized and "польз" in normalized:
            action = "export_users"
        elif "промокод" in normalized and any(word in normalized for word in ("список", "покажи", "последн")):
            action = "list_promos"
        elif "техрежим" in normalized or "техническ" in normalized:
            if any(word in normalized for word in ("включ", "закрой", "закрыть")):
                action = "maintenance_set"
                params["enabled"] = True
            elif any(word in normalized for word in ("выключ", "открой", "открыть")):
                action = "maintenance_set"
                params["enabled"] = False
            else:
                action = "maintenance_status"
        elif re.search(r"\b(разбан|разбань|разблок|разблокируй)\b", normalized) and user_id:
            action = "unban_user"
            params["telegram_id"] = user_id
        elif re.search(r"\b(бан|забань|заблок|заблокируй)\b", normalized) and user_id:
            action = "ban_user"
            params["telegram_id"] = user_id
        elif any(word in normalized for word in ("начисл", "добав", "пополн")) and user_id and amount:
            action = "add_credits"
            params.update({"telegram_id": user_id, "amount": amount})
        elif any(word in normalized for word in ("спиш", "снять", "вычти")) and user_id and amount:
            action = "deduct_credits"
            params.update({"telegram_id": user_id, "amount": amount})
        elif user_id:
            action = "user_info"
            params["telegram_id"] = user_id
        elif "создай" in normalized and "промокод" in normalized:
            action = "create_promo"
            params = self._parse_promo(normalized)
        elif any(word in normalized for word in ("удали промокод", "отключи промокод")):
            code_match = re.search(r"\b([a-z0-9_-]{3,32})\b", normalized, flags=re.I)
            action = "deactivate_promo"
            params["code"] = code_match.group(1).upper() if code_match else ""

        plan = {
            "action": action,
            "params": params,
            "summary": self._default_summary(action, params),
            "confidence": 0.65 if action != "unknown" else 0.0,
        }
        if action == "bot_report":
            plan["actions"] = [
                {"action": "stats", "params": {}, "summary": "Собрать статистику"},
                {"action": "maintenance_status", "params": {}, "summary": "Проверить техрежим"},
                {"action": "list_promos", "params": {}, "summary": "Посмотреть промокоды"},
                {"action": "analyze_logs", "params": {"query": normalized, "lines": 250}, "summary": "Проверить последние логи"},
            ]
        return self._normalize_plan(plan)

    def _parse_promo(self, text: str) -> dict[str, Any]:
        code_match = re.search(r"(?:промокод|код)\s+([a-z0-9_-]{3,32})", text, flags=re.I)
        number_source = text
        if code_match:
            number_source = number_source.replace(code_match.group(1), "", 1)
        numbers = [int(n) for n in re.findall(r"\b\d+\b", number_source)]
        promo_type = "discount"
        if any(word in text for word in ("BoomCoin", "banana")):
            promo_type = "bananas"
        elif any(word in text for word in ("генерац", "generation")):
            promo_type = "generation"
        date_match = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", text)
        return {
            "code": code_match.group(1).upper() if code_match else "",
            "promo_type": promo_type,
            "value": numbers[0] if numbers else None,
            "max_uses": numbers[1] if len(numbers) > 1 else None,
            "expires_at": date_match.group(1) if date_match else None,
        }

    def _find_user_id(self, text: str) -> int | None:
        for match in re.findall(r"\b\d{5,15}\b", text):
            return int(match)
        return None

    def _find_amount(self, text: str) -> int | None:
        for match in re.findall(r"\b\d{1,4}\b", text):
            value = int(match)
            if value > 0:
                return value
        return None

    def _to_int(self, value: Any) -> int | None:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return None
        return parsed if parsed > 0 else None

    def _clean_date(self, value: Any) -> str | None:
        if value in (None, "", "null"):
            return None
        text = str(value).strip()
        return text if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text) else None

    def _default_summary(self, action: str, params: dict[str, Any]) -> str:
        if action == "unknown":
            return (
                "Не понял действие. Можно попросить: отчёт по боту, анализ логов, "
                "исследование новых AI-моделей, статистику, пользователя, баланс, бан, промокод."
            )
        if action == "bot_report":
            return "Собрать агентный отчёт по состоянию бота."
        if action == "analyze_logs":
            return "Проанализировать последние логи бота."
        if action == "research_ai":
            return "Найти и кратко разобрать новые AI-инструменты для генерации контента."
        if action == "clear_context":
            return "Очистить контекст ИИ-админа."
        return f"Выполнить действие {action}: {params}"

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()


admin_ai_service = AdminAIService()
