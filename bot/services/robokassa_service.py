import decimal
import hashlib
from typing import Any, Dict
from urllib.parse import urlencode, urlparse

from bot.config import config


class RobokassaService:
    """Сервис для работы с Robokassa."""

    def __init__(
        self, merchant_login: str, password1: str, password2: str, test: bool = False
    ):
        self.merchant_login = merchant_login
        self.password1 = password1
        self.password2 = password2
        self.test = 1 if test else 0
        self.payment_url = "https://auth.robokassa.ru/Merchant/Index.aspx"
        self.enabled = bool(merchant_login and password1 and password2)

    def calculate_signature(self, *args) -> str:
        return hashlib.md5(":".join(str(arg) for arg in args).encode()).hexdigest()

    def parse_response(self, query_str: str) -> Dict[str, str]:
        params = {}
        for item in urlparse(query_str).query.split("&"):
            if "=" in item:
                key, value = item.split("=", 1)
                params[key] = value
        return params

    def check_signature_result(
        self,
        order_number: int,
        received_sum: decimal.Decimal,
        received_signature: str,
        password: str,
    ) -> bool:
        signature = self.calculate_signature(received_sum, order_number, password)
        return signature.lower() == received_signature.lower()

    def generate_payment_link(
        self,
        cost: decimal.Decimal,
        number: str,
        description: str,
        success_url: str,
        result_url: str,
    ) -> str:
        signature = self.calculate_signature(
            self.merchant_login, cost, number, self.password1
        )
        data = {
            "MerchantLogin": self.merchant_login,
            "OutSum": str(cost),
            "InvId": number,
            "Description": description,
            "SignatureValue": signature,
            "IsTest": self.test,
            "SuccessURL": success_url,
            "ResultURL": result_url,
        }
        return f"{self.payment_url}?{urlencode(data)}"

    async def create_payment(
        self,
        amount_rub: float,
        order_id: str,
        description: str,
        success_url: str,
        result_url: str,
    ) -> Dict[str, Any]:
        if not self.enabled:
            return {"Success": False, "Message": "Robokassa not configured"}
        try:
            cost = decimal.Decimal(amount_rub).quantize(decimal.Decimal("0.01"))
            payment_url = self.generate_payment_link(
                cost, order_id, description, success_url, result_url
            )
            return {
                "Success": True,
                "PaymentId": order_id,
                "PaymentURL": payment_url,
            }
        except Exception as e:
            return {"Success": False, "Message": str(e)}

    def verify_result(self, query_str: str, password: str = None) -> Dict[str, Any]:
        params = self.parse_response(query_str)
        if (
            "OutSum" not in params
            or "InvId" not in params
            or "SignatureValue" not in params
        ):
            return {"valid": False, "message": "Missing required params"}
        try:
            out_sum = decimal.Decimal(params["OutSum"])
            inv_id = int(params["InvId"])
            signature = params["SignatureValue"]
            use_password = password or self.password2
            if self.check_signature_result(inv_id, out_sum, signature, use_password):
                return {
                    "valid": True,
                    "order_id": str(inv_id),
                    "amount_rub": float(out_sum),
                }
            return {"valid": False, "message": "bad sign"}
        except Exception as e:
            return {"valid": False, "message": str(e)}


robokassa_service = RobokassaService(
    config.ROBOKASSA_MERCHANT_LOGIN,
    config.ROBOKASSA_PASSWORD1,
    config.ROBOKASSA_PASSWORD2,
    config.ROBOKASSA_TEST,
)
