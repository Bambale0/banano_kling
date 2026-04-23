import hashlib
import hmac
import logging
from typing import Any, Dict, Optional

import aiohttp

from bot.config import config

logger = logging.getLogger(__name__)


class CryptoBotService:
    def __init__(self, api_token: str, base_url: str):
        self.api_token = api_token
        self.base_url = base_url.rstrip("/")
        self.enabled = bool(api_token)
        self._session = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=60)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    async def _request(
        self, method: str, api_method: str, payload: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        if not self.enabled:
            logger.warning("Crypto Bot is not configured")
            return None

        session = await self._get_session()
        headers = {
            "Crypto-Pay-API-Token": self.api_token,
            "Content-Type": "application/json",
        }
        url = f"{self.base_url}/api/{api_method}"

        try:
            async with session.request(
                method=method,
                url=url,
                headers=headers,
                json=payload or {},
            ) as response:
                data = await response.json(content_type=None)
                if response.status == 200 and data.get("ok"):
                    return data.get("result")

                logger.error(
                    "Crypto Bot %s failed: status=%s payload=%s response=%s",
                    api_method,
                    response.status,
                    payload,
                    data,
                )
                return None
        except Exception as exc:
            logger.exception("Crypto Bot request failed: %s", exc)
            return None

    async def create_invoice(
        self,
        amount_rub: float,
        order_id: str,
        description: str,
        paid_btn_url: str,
    ) -> Optional[Dict[str, Any]]:
        payload = {
            "currency_type": "fiat",
            "fiat": "RUB",
            "amount": f"{amount_rub:.2f}",
            "accepted_assets": config.CRYPTOBOT_ACCEPTED_ASSETS,
            "description": description[:1024],
            "payload": order_id,
            "paid_btn_name": "callback",
            "paid_btn_url": paid_btn_url,
            "allow_comments": False,
            "allow_anonymous": True,
            "expires_in": config.CRYPTOBOT_EXPIRES_IN,
        }
        result = await self._request("POST", "createInvoice", payload)
        if not result:
            return None

        return {
            "Success": True,
            "PaymentId": str(result["invoice_id"]),
            "PaymentURL": result.get("bot_invoice_url")
            or result.get("mini_app_invoice_url")
            or result.get("web_app_invoice_url"),
            "Raw": result,
        }

    async def get_invoice(self, invoice_id: str) -> Optional[Dict[str, Any]]:
        result = await self._request(
            "POST", "getInvoices", {"invoice_ids": str(invoice_id)}
        )
        if not result:
            return None

        items = result.get("items") or []
        if not items:
            return None
        return items[0]

    def verify_webhook_signature(self, raw_body: bytes, signature: str) -> bool:
        if not self.enabled or not signature:
            return False

        secret = hashlib.sha256(self.api_token.encode("utf-8")).digest()
        digest = hmac.new(secret, raw_body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(digest, signature)

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()


cryptobot_service = CryptoBotService(
    api_token=config.CRYPTOBOT_API_TOKEN,
    base_url=config.CRYPTOBOT_BASE_URL,
)
