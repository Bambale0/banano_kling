from yookassa import Configuration, Payment
import uuid
import os
from typing import Optional, Dict, Any


class YooKassaClient:
    def __init__(self, shop_id: Optional[str] = None, secret_key: Optional[str] = None):
        shop_id = shop_id or os.getenv("YOOKASSA_SHOP_ID")
        secret_key = secret_key or os.getenv("YOOKASSA_SECRET_KEY")
        if not shop_id or not secret_key:
            raise ValueError("YOOKASSA_SHOP_ID and YOOKASSA_SECRET_KEY must be set")

        Configuration.account_id = shop_id
        Configuration.secret_key = secret_key

    def create_payment(self, amount: float, return_url: str, description: str = "Оплата") -> Dict[str, Any]:
        payment = Payment.create({
            "amount": {
                "value": f"{amount:.2f}",
                "currency": "RUB"
            },
            "confirmation": {
                "type": "redirect",
                "return_url": return_url
            },
            "capture": True,
            "description": description
        }, str(uuid.uuid4()))

        return {
            "payment_id": payment.id,
            "confirmation_url": getattr(payment, "confirmation", {}).get("confirmation_url") if hasattr(payment, "confirmation") else getattr(payment.confirmation, "confirmation_url", None)
        }

    def get_payment(self, payment_id: str) -> Dict[str, Any]:
        payment = Payment.find_one(payment_id)

        return {
            "status": payment.status,
            "paid": getattr(payment, "paid", None),
            "amount": getattr(payment.amount, "value", None)
        }
