import logging
import re
from typing import Any

import aiohttp

from bot.config import config

logger = logging.getLogger(__name__)


class JumpFinanceError(Exception):
    """Ошибка интеграции Jump Finance."""


class JumpFinanceService:
    def __init__(self) -> None:
        self.base_url = config.JUMP_FINANCE_BASE_URL.rstrip("/")
        self.client_key = config.JUMP_FINANCE_CLIENT_KEY
        self._agent_id: int | None = None
        self._session: aiohttp.ClientSession | None = None

    @property
    def enabled(self) -> bool:
        return bool(self.client_key and self.base_url)

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=60)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def _request(
        self,
        method: str,
        path: str,
        json_data: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self.enabled:
            missing = ", ".join(config.jump_finance_missing_settings)
            raise JumpFinanceError(f"Jump Finance не настроен: заполните {missing}")

        session = await self._get_session()
        url = f"{self.base_url}{path}"
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Client-Key": self.client_key,
        }

        async with session.request(
            method=method,
            url=url,
            headers=headers,
            json=json_data,
            params=params,
        ) as response:
            text = await response.text()
            try:
                data = await response.json(content_type=None)
            except Exception:
                data = {}

            if response.status >= 400:
                error = data.get("error") or {}
                detail = error.get("detail") or text or "Неизвестная ошибка"
                fields = error.get("fields") or []
                if fields:
                    formatted = []
                    for field in fields:
                        name = field.get("field", "field")
                        messages = ", ".join(field.get("messages") or [])
                        formatted.append(f"{name}: {messages}")
                    detail = f"{detail} ({'; '.join(formatted)})"
                raise JumpFinanceError(detail)

            if not isinstance(data, dict):
                raise JumpFinanceError("Jump Finance вернул неожиданный ответ")
            return data

    async def get_default_agent_id(self) -> int:
        if config.JUMP_FINANCE_AGENT_ID > 0:
            return config.JUMP_FINANCE_AGENT_ID
        if self._agent_id:
            return self._agent_id

        data = await self._request("GET", "/agents", params={"per_page": 2})
        items = data.get("items")
        if not isinstance(items, list) or not items:
            raise JumpFinanceError("В Jump Finance не найдено ни одного юрлица")
        if len(items) > 1:
            raise JumpFinanceError(
                "В Jump Finance найдено несколько юрлиц. "
                "Укажите нужное в JUMP_FINANCE_AGENT_ID"
            )

        agent_id = items[0].get("id") if isinstance(items[0], dict) else None
        if not agent_id:
            raise JumpFinanceError("Jump Finance не вернул ID юрлица")
        self._agent_id = int(agent_id)
        logger.info("Resolved Jump Finance agent_id from /agents: %s", self._agent_id)
        return self._agent_id

    @staticmethod
    def parse_full_name(full_name: str) -> tuple[str, str, str]:
        cleaned = re.sub(r"\s+", " ", (full_name or "").strip())
        parts = cleaned.split(" ")
        if len(parts) < 2:
            raise JumpFinanceError("Укажите минимум имя и фамилию")
        last_name = parts[0]
        first_name = parts[1]
        middle_name = " ".join(parts[2:]) if len(parts) > 2 else ""
        return last_name, first_name, middle_name

    async def upsert_contractor(
        self,
        *,
        phone: str,
        full_name: str,
        agent_id: int | None = None,
        inn: str | None = None,
    ) -> dict[str, Any]:
        last_name, first_name, middle_name = self.parse_full_name(full_name)
        resolved_agent_id = agent_id or await self.get_default_agent_id()
        payload: dict[str, Any] = {
            "phone": phone,
            "last_name": last_name,
            "first_name": first_name,
            "middle_name": middle_name,
            "legal_form_id": 1,
            "agent_id": resolved_agent_id,
        }
        if inn:
            payload["inn"] = inn
        data = await self._request("POST", "/contractors", payload)
        item = data.get("item")
        if not isinstance(item, dict) or not item.get("id"):
            raise JumpFinanceError("Не удалось создать исполнителя")
        return item

    async def create_payment(
        self,
        *,
        contractor_id: int,
        amount_rub: float,
        card_number: str,
        customer_payment_id: str,
        service_name: str,
        payment_purpose: str,
        agent_id: int | None = None,
        bank_account_id: int | None = None,
    ) -> dict[str, Any]:
        resolved_agent_id = agent_id or await self.get_default_agent_id()
        payload: dict[str, Any] = {
            "contractor_id": contractor_id,
            "amount": round(float(amount_rub), 2),
            "agent_id": resolved_agent_id,
            "customer_payment_id": customer_payment_id[:36],
            "service_name": service_name[:150],
            "payment_purpose": payment_purpose[:125],
            "requisite": {
                "type_id": 8,
                "account_number": card_number,
            },
        }
        if bank_account_id or config.JUMP_FINANCE_BANK_ACCOUNT_ID:
            payload["bank_account_id"] = (
                bank_account_id or config.JUMP_FINANCE_BANK_ACCOUNT_ID
            )

        data = await self._request("POST", "/payments", payload)
        item = data.get("item")
        if not isinstance(item, dict) or not item.get("id"):
            raise JumpFinanceError("Не удалось создать выплату")
        return item

    async def get_payment(self, payment_id: int | str) -> dict[str, Any]:
        data = await self._request("GET", f"/payments/{payment_id}")
        item = data.get("item")
        if not isinstance(item, dict):
            raise JumpFinanceError("Не удалось получить статус выплаты")
        return item


jump_finance_service = JumpFinanceService()
