import logging
from typing import Any, Dict, Optional

from bot.config import config
from tbank_payment.client import TBankAsyncClient
from tbank_payment.exceptions import TBankAPIError, TBankAuthError, TBankValidationError
from tbank_payment.models import GetStateRequest, InitPaymentRequest
from tbank_payment.webhooks import WebhookHandler

logger = logging.getLogger(__name__)


class TBankService:
    """Обертка над TBankAsyncClient для совместимости с текущим кодом бота"""

    def __init__(self, terminal_key: str, secret_key: str, api_url: str = None):
        if not terminal_key or not terminal_key.strip():
            raise ValueError(
                "TBANK_TERMINAL_KEY is required and cannot be empty. Please set the environment variable TBANK_TERMINAL_KEY with your T-Bank terminal key."
            )
        if not secret_key or not secret_key.strip():
            raise ValueError(
                "TBANK_SECRET_KEY is required and cannot be empty. Please set the environment variable TBANK_SECRET_KEY with your T-Bank secret key."
            )

        self.terminal_key = terminal_key
        self.secret_key = secret_key
        self.client = TBankAsyncClient(
            terminal_key=terminal_key,
            password=secret_key,
        )
        self.webhook_handler = WebhookHandler(secret_key)

    async def init_payment(
        self,
        amount: int,  # в копейках
        order_id: str,
        description: str,
        customer_key: str,
        success_url: str,
        fail_url: str,
        notification_url: str,
        data: Optional[Dict] = None,
    ) -> Optional[Dict]:
        """Инициализация платежа (совместимый интерфейс)"""
        request = InitPaymentRequest(
            Amount=amount,
            OrderId=order_id,
            Description=description,
            CustomerKey=customer_key,
            SuccessURL=success_url,
            FailURL=fail_url,
            NotificationURL=notification_url,
            DATA=data,
            PayType="O",  # Одностадийная
            Language="ru",
        )
        try:
            result = await self.client.init_payment(request)
            return (
                result.model_dump(mode="json")
                if hasattr(result, "model_dump")
                else dict(result)
            )
        except (TBankAPIError, TBankAuthError, TBankValidationError) as e:
            logger.error(f"T-Bank init_payment error: {e}")
            return {
                "Success": False,
                "ErrorCode": getattr(e, "error_code", None),
                "Message": str(e),
            }
        except Exception as e:
            logger.error(f"T-Bank init_payment unexpected error: {e}")
            return {"Success": False, "Message": f"Unexpected error: {str(e)}"}

    async def get_state(self, payment_id: str) -> Optional[Dict]:
        """Проверка статуса платежа"""
        try:
            result = await self.client.get_state(payment_id)
            return (
                result.model_dump(mode="json")
                if hasattr(result, "model_dump")
                else result
            )
        except Exception as e:
            logger.error(f"T-Bank get_state error: {e}")
            return {"Success": False, "Message": str(e)}

    async def cancel(self, payment_id: str) -> Optional[Dict]:
        """Отмена платежа"""
        try:
            result = await self.client.cancel_payment(payment_id)
            return (
                result.model_dump(mode="json")
                if hasattr(result, "model_dump")
                else result
            )
        except Exception as e:
            logger.error(f"T-Bank cancel error: {e}")
            return {"Success": False, "Message": str(e)}

    def verify_notification(self, data: Dict[str, Any]) -> bool:
        """Проверка подписи уведомления"""
        return self.webhook_handler.validate_notification(data)


# Создаём сервис (совместимость с текущим кодом)
tbank_service = TBankService(
    terminal_key=config.TBANK_TERMINAL_KEY,
    secret_key=config.TBANK_SECRET_KEY,
)
