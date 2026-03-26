import logging
import uuid
from typing import Any, Dict, List, Optional

import aiosqlite
from yookassa import Configuration, Payment

from bot import database as db
from bot.config import config
from bot.database import DATABASE_PATH

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
            # Some integrations expect notification URL to be present in metadata;
            # also include it at top-level when provided — harmless and can help
            # third-party SDKs or API versions that accept it there.
            payload["metadata"]["notification_url"] = notification_url
            payload["notification_url"] = notification_url

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
                "paid": getattr(payment, "paid", False)
                or getattr(payment, "paid_at", False),
                "metadata": getattr(payment, "metadata", {}) or {},
                "amount": getattr(payment, "amount", None),
                "Raw": payment,
            }
        except Exception as exc:
            logger.exception("YooKassa payment lookup failed: %s", exc)
            return None

    async def poll_pending_transactions(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Reconcile pending YooKassa transactions by querying YooKassa API.

        This will look for transactions in the local DB with provider='yookassa' and
        status='pending' and try to fetch their current state from YooKassa. If a
        payment is confirmed/paid, the transaction will be marked 'completed' and
        user credits will be credited. If the payment is failed/canceled, the
        transaction will be marked 'failed'.

        Returns list of results for diagnostics.
        """
        if not self.enabled:
            logger.warning("YooKassa is not configured — skipping poll")
            return []

        results: List[Dict[str, Any]] = []

        async with aiosqlite.connect(DATABASE_PATH) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(
                "SELECT id, order_id, user_id, payment_id, credits FROM transactions WHERE provider = 'yookassa' AND status = 'pending' AND payment_id IS NOT NULL LIMIT ?",
                (limit,),
            )
            rows = await cursor.fetchall()

        for row in rows:
            order_id = row["order_id"]
            payment_id = row["payment_id"]
            user_id = row["user_id"]
            credits = row["credits"]

            try:
                payment = await self.get_payment(payment_id)
            except Exception as exc:
                logger.exception("Error fetching payment %s: %s", payment_id, exc)
                results.append(
                    {"order_id": order_id, "payment_id": payment_id, "error": str(exc)}
                )
                continue

            if not payment:
                results.append(
                    {
                        "order_id": order_id,
                        "payment_id": payment_id,
                        "status": "not_found",
                    }
                )
                continue

            status = (payment.get("status") or "").lower()
            paid = bool(payment.get("paid"))

            # treat paid/succeeded as completed
            if paid or status in ("succeeded", "paid", "captured"):
                # credit user
                telegram_id = await db.get_telegram_id_by_user_id(user_id)
                if telegram_id:
                    await db.add_credits(telegram_id, credits)
                    await db.mark_user_paid(telegram_id)
                await db.update_transaction_status(order_id, "completed")
                logger.info(
                    "Reconciled YooKassa payment %s -> completed (order=%s)",
                    payment_id,
                    order_id,
                )
                results.append(
                    {
                        "order_id": order_id,
                        "payment_id": payment_id,
                        "action": "completed",
                    }
                )
                continue

            # treat canceled/failed
            if status in ("canceled", "failed", "rejected"):
                await db.update_transaction_status(order_id, "failed")
                logger.info(
                    "Reconciled YooKassa payment %s -> failed (order=%s, status=%s)",
                    payment_id,
                    order_id,
                    status,
                )
                results.append(
                    {
                        "order_id": order_id,
                        "payment_id": payment_id,
                        "action": "failed",
                        "status": status,
                    }
                )
                continue

            # otherwise still pending
            results.append(
                {
                    "order_id": order_id,
                    "payment_id": payment_id,
                    "action": "still_pending",
                    "status": status,
                }
            )

        return results

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
