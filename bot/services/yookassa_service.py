import logging
import uuid
from typing import Any, Dict, Optional

from yookassa import Configuration, Payment

from bot.config import config

logger = logging.getLogger(__name__)


class YooKassaService:
    """Асинхронная обёртка над YooKassa SDK."""

    def __init__(self, shop_id: str, secret_key: str, return_url: str = ""):
        self.shop_id = shop_id
        self.secret_key = secret_key
        self.return_url = return_url
        self.enabled = bool(shop_id and secret_key)

        if self.enabled:
            Configuration.account_id = shop_id
            Configuration.secret_key = secret_key

    async def create_payment(
        self,
        amount_rub: float,
        order_id: str,
        description: str,
        return_url: Optional[str] = None,
        notification_url: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        if not self.enabled:
            logger.warning("YooKassa is not configured")
            return None

        payload = {
            "amount": {"value": f"{amount_rub:.2f}", "currency": "RUB"},
            "capture": True,
            "confirmation": {
                "type": "redirect",
                "return_url": return_url or self.return_url or "https://t.me/",
            },
            "description": description[:128],
            "metadata": {"order_id": order_id},
        }

        if notification_url:
            payload["metadata"]["notification_url"] = notification_url

        try:
            payment = Payment.create(payload, str(uuid.uuid4()))
            logger.info("YooKassa payment created: %s", payment.id)
            return {
                "Success": True,
                "PaymentId": payment.id,
                "PaymentURL": payment.confirmation.confirmation_url,
                "Raw": payment,
            }
        except Exception as exc:
            logger.exception("YooKassa payment creation failed: %s", exc)
            return {"Success": False, "Message": str(exc)}

    async def get_payment(self, payment_id: str) -> Optional[Dict[str, Any]]:
        if not self.enabled:
            return None

        try:
            payment = Payment.find_one(payment_id)
            return {
                "id": payment.id,
                "status": payment.status,
                "paid": payment.paid,
                "metadata": getattr(payment, "metadata", {}) or {},
                "amount": getattr(payment, "amount", None),
                "Raw": payment,
            }
        except Exception as exc:
            logger.exception("YooKassa payment lookup failed: %s", exc)
            return None

    @staticmethod
    def extract_order_id(payment: Any) -> Optional[str]:
        metadata = getattr(payment, "metadata", None) or {}
        order_id = metadata.get("order_id")
        return str(order_id) if order_id else None


yookassa_service = YooKassaService(
    shop_id=config.YOOKASSA_SHOP_ID,
    secret_key=config.YOOKASSA_SECRET_KEY,
    return_url=config.YOOKASSA_RETURN_URL,
)
