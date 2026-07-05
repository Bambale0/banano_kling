import logging
import asyncio
from typing import Any, Dict, Optional

import aiohttp

from bot.config import config

logger = logging.getLogger(__name__)


def _preview_lava_error_body(raw_text: str, limit: int = 500) -> str:
    text = (raw_text or "").strip()
    if not text:
        return ""
    lowered = text.lower()
    if lowered.startswith("<!doctype html") or lowered.startswith("<html"):
        return f"[html response: {len(text)} chars]"
    if len(text) > limit:
        return text[:limit] + f"... [truncated, {len(text)} chars total]"
    return text


class LavaService:
    """lava.top Public API client.

    Swagger: lava.top Public API 1.17.0
    Auth: X-Api-Key header.
    Create invoice: POST /api/v3/invoice.
    Get invoice: GET /api/v2/invoices/{id}.
    Webhook payload contains eventType, contractId, amount, currency, status.
    """

    def __init__(self, api_key: str, base_url: str = "https://gate.lava.top"):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self._session: Optional[aiohttp.ClientSession] = None

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=30)
            )
        return self._session

    def _headers(self) -> Dict[str, str]:
        return {
            "X-Api-Key": self.api_key,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    async def _request(
        self,
        method: str,
        path: str,
        payload: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if not self.enabled:
            return {"ok": False, "error": "LAVA_API_KEY is not configured"}

        session = await self._get_session()
        url = f"{self.base_url}/{path.lstrip('/')}"
        max_attempts = 3 if method.upper() == "GET" else 1

        for attempt in range(1, max_attempts + 1):
            try:
                async with session.request(
                    method.upper(),
                    url,
                    headers=self._headers(),
                    json=payload,
                    params=params,
                ) as resp:
                    raw_text = await resp.text()
                    try:
                        data = await resp.json(content_type=None)
                    except Exception:
                        data = {"raw": raw_text}

                    if resp.status >= 400:
                        if resp.status in {500, 502, 503, 504} and attempt < max_attempts:
                            logger.info(
                                "Lava API transient error %s %s attempt=%s/%s",
                                resp.status,
                                url,
                                attempt,
                                max_attempts,
                            )
                            await asyncio.sleep(0.5 * attempt)
                            continue
                        logger.warning(
                            "Lava API error %s %s: %s",
                            resp.status,
                            url,
                            _preview_lava_error_body(raw_text),
                        )
                        return {
                            "ok": False,
                            "status": resp.status,
                            "error": data,
                            "raw": raw_text,
                        }

                    if isinstance(data, dict):
                        data.setdefault("ok", True)
                        return data
                    return {"ok": True, "result": data}
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                if attempt < max_attempts:
                    logger.info(
                        "Lava API request failed %s attempt=%s/%s: %s",
                        url,
                        attempt,
                        max_attempts,
                        exc,
                    )
                    await asyncio.sleep(0.5 * attempt)
                    continue
                logger.warning("Lava API request failed %s: %s", url, exc)
                return {"ok": False, "status": None, "error": str(exc), "raw": ""}

        return {"ok": False, "status": None, "error": "request failed", "raw": ""}

    async def create_invoice(
        self,
        email: str,
        offer_id: str,
        currency: str = "RUB",
        amount: Optional[float] = None,
        payment_provider: Optional[str] = None,
        payment_method: Optional[str] = None,
        buyer_language: Optional[str] = None,
        periodicity: Optional[str] = None,
        client_utm: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "email": email,
            "offerId": offer_id,
            "currency": currency,
        }
        if amount is not None:
            payload["amount"] = float(amount)
        if payment_provider:
            payload["paymentProvider"] = payment_provider
        if payment_method:
            payload["paymentMethod"] = payment_method
        if buyer_language:
            payload["buyerLanguage"] = buyer_language
        if periodicity:
            payload["periodicity"] = periodicity
        if client_utm:
            payload["clientUtm"] = client_utm

        return await self._request("POST", "/api/v3/invoice", payload=payload)

    async def get_invoice(self, invoice_id: str) -> Optional[Dict[str, Any]]:
        response = await self._request("GET", f"/api/v2/invoices/{invoice_id}")
        if not response.get("ok"):
            return None
        return response

    def extract_invoice_id(self, response: Dict[str, Any]) -> Optional[str]:
        value = response.get("id")
        if value:
            return str(value)
        data = response.get("data")
        if isinstance(data, dict) and data.get("id"):
            return str(data["id"])
        result = response.get("result")
        if isinstance(result, dict) and result.get("id"):
            return str(result["id"])
        return None

    def extract_payment_url(self, response: Dict[str, Any]) -> Optional[str]:
        candidates = [
            response.get("paymentUrl"),
            response.get("payment_url"),
            response.get("url"),
            response.get("link"),
        ]
        for container_name in ("data", "result"):
            container = response.get(container_name)
            if isinstance(container, dict):
                candidates.extend(
                    [
                        container.get("paymentUrl"),
                        container.get("payment_url"),
                        container.get("url"),
                        container.get("link"),
                    ]
                )
        return next((item for item in candidates if item), None)

    @staticmethod
    def _find_first(payload: Any, keys: tuple[str, ...]) -> Optional[str]:
        if isinstance(payload, dict):
            for key in keys:
                value = payload.get(key)
                if value not in (None, ""):
                    return str(value)
            for value in payload.values():
                found = LavaService._find_first(value, keys)
                if found:
                    return found
        elif isinstance(payload, list):
            for value in payload:
                found = LavaService._find_first(value, keys)
                if found:
                    return found
        return None

    @staticmethod
    def webhook_event_type(payload: Dict[str, Any]) -> str:
        return (
            LavaService._find_first(payload, ("eventType", "event_type"))
            or ""
        ).lower()

    @staticmethod
    def webhook_status(payload: Dict[str, Any]) -> str:
        return (
            LavaService._find_first(payload, ("status", "contractStatus", "contract_status"))
            or ""
        ).lower()

    @classmethod
    def is_success_webhook(cls, payload: Dict[str, Any]) -> bool:
        event_type = cls.webhook_event_type(payload)
        status = cls.webhook_status(payload)
        return event_type == "payment.success" or status in {
            "completed",
            "success",
            "succeeded",
            "paid",
        }

    @classmethod
    def is_failed_webhook(cls, payload: Dict[str, Any]) -> bool:
        event_type = cls.webhook_event_type(payload)
        status = cls.webhook_status(payload)
        return event_type == "payment.failed" or status in {
            "cancelled",
            "canceled",
            "failed",
            "expired",
        }

    @classmethod
    def webhook_contract_id(cls, payload: Dict[str, Any]) -> Optional[str]:
        value = cls._find_first(
            payload,
            ("contractId", "contract_id", "invoiceId", "invoice_id"),
        )
        return str(value) if value else None

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()


lava_service = LavaService(
    api_key=config.LAVA_API_KEY,
    base_url=config.LAVA_API_BASE_URL,
)
