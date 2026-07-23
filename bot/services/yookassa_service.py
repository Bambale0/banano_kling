"""Compatibility adapter for deployments that still use the old YooKassa alias.

The product now uses FreeKassa. Keeping ``yookassa_service`` as an import alias
lets older Telegram/Mini App call sites migrate without a flag-day rewrite and
without loading the YooKassa SDK.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Dict, List, Optional

from bot.services.freekassa_service import freekassa_service

logger = logging.getLogger(__name__)


class FreeKassaLegacyAliasService:
    """Expose the old method names while executing FreeKassa operations."""

    @property
    def enabled(self) -> bool:
        return freekassa_service.enabled

    async def create_payment(
        self,
        amount_rub: float,
        order_id: str,
        description: str,
        return_url: Optional[str] = None,
        notification_url: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        result = await freekassa_service.create_payment(
            amount_rub=amount_rub,
            order_id=order_id,
            description=description,
            return_url=return_url,
            notification_url=notification_url,
        )
        if not result.get("ok"):
            return {
                "Success": False,
                "Message": result.get("error") or "FreeKassa payment creation failed",
                "Provider": "freekassa",
            }
        return {
            "Success": True,
            "PaymentId": result["payment_id"],
            "PaymentURL": result["payment_url"],
            "Provider": "freekassa",
            "Raw": result,
        }

    async def get_payment(self, payment_id: str) -> Optional[Dict[str, Any]]:
        result = await freekassa_service.get_payment(
            payment_id,
            merchant_order_id=payment_id,
        )
        if not result:
            return None
        return {
            "id": result.get("id") or payment_id,
            "status": result.get("status") or "",
            "paid": bool(result.get("paid")),
            "failed": bool(result.get("failed")),
            "metadata": {"order_id": result.get("merchant_order_id") or payment_id},
            "amount": result.get("amount"),
            "currency": result.get("currency"),
            "Raw": result,
        }

    async def poll_pending_transactions(
        self,
        limit: int = 100,
        complete_order: Optional[
            Callable[[str], Awaitable[Dict[str, Any]]]
        ] = None,
    ) -> List[Dict[str, Any]]:
        # Old Mini App clients may still save provider='yookassa'. Reconcile
        # those rows through the FreeKassa merchant API during the transition.
        return await freekassa_service.poll_pending_transactions(
            limit=limit,
            providers=("yookassa",),
            complete_order=complete_order,
        )

    @staticmethod
    def extract_order_id(payment: Any) -> Optional[str]:
        if isinstance(payment, dict):
            metadata = payment.get("metadata") or {}
            order_id = (
                metadata.get("order_id")
                or payment.get("merchant_order_id")
                or payment.get("payment_id")
            )
            return str(order_id) if order_id else None
        metadata = getattr(payment, "metadata", None) or {}
        order_id = metadata.get("order_id")
        return str(order_id) if order_id else None


# Deliberately retained symbol for compatibility with existing imports.
yookassa_service = FreeKassaLegacyAliasService()
