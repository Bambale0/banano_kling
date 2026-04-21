import asyncio
import decimal
from typing import Any, Dict
from urllib.parse import urlparse

from aiorobokassa import RoboKassaClient

from bot.config import config


class RobokassaService:
    """Асинхронный сервис для работы с Robokassa."""

    def __init__(self):
        self.merchant_login = config.ROBOKASSA_MERCHANT_LOGIN
        self.password1 = config.ROBOKASSA_PASSWORD1
        self.password2 = config.ROBOKASSA_PASSWORD2
        self.test = config.ROBOKASSA_TEST
        self.enabled = bool(self.merchant_login and self.password1 and self.password2)

        if self.enabled:
            self.client = RoboKassaClient(
                merchant_login=self.merchant_login,
                password1=self.password1,
                password2=self.password2,
                test_mode=self.test,
            )
        else:
            self.client = None

    def parse_response(self, query_str: str) -> Dict[str, str]:
        params = {}
        for item in urlparse(query_str).query.split("&"):
            if "=" in item:
                key, value = item.split("=", 1)
                params[key] = value
        return params

    async def create_payment(
        self,
        amount_rub: float,
        order_id: str,
        description: str,
    ) -> Dict[str, Any]:
        if not self.enabled or not self.client:
            return {"Success": False, "Message": "Robokassa not configured"}
        try:
            amount = decimal.Decimal(amount_rub).quantize(decimal.Decimal("0.01"))
            inv_id = int(order_id)
            loop = asyncio.get_running_loop()
            payment_url = await loop.run_in_executor(
                None,
                self.client.create_payment_url,
                float(amount),
                description[:1024],  # limit
                inv_id,
            )
            return {
                "Success": True,
                "PaymentId": order_id,
                "PaymentURL": payment_url,
            }
        except Exception as e:
            return {"Success": False, "Message": str(e)}

    def verify_result(self, params: Dict[str, str]) -> Dict[str, Any]:
        if not self.enabled or not self.client:
            return {"valid": False, "message": "Robokassa not configured"}
        if (
            "OutSum" not in params
            or "InvId" not in params
            or "SignatureValue" not in params
        ):
            return {"valid": False, "message": "Missing required params"}
        try:
            self.client.verify_result_url(
                params["OutSum"], params["InvId"], params["SignatureValue"]
            )
            out_sum = decimal.Decimal(params["OutSum"])
            inv_id = params["InvId"]
            return {
                "valid": True,
                "order_id": inv_id,
                "amount_rub": float(out_sum),
            }
        except Exception as e:
            return {"valid": False, "message": str(e)}

    async def close(self):
        if self.client:
            await self.client.close()


robokassa_service = RobokassaService()
