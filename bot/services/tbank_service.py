import hashlib
import json
import logging
from typing import Any, Dict, Optional

import aiohttp

logger = logging.getLogger(__name__)


class TBankService:
    """Асинхронная версия TBank API для работы с эквайрингом"""

    def __init__(self, terminal_key: str, secret_key: str, api_url: str):
        self.terminal_key = terminal_key
        self.secret_key = secret_key
        self.api_url = api_url.rstrip("/")

    def _generate_token(self, params: Dict[str, Any]) -> str:
        """
        Генерация токена подписи по документации Т-Банк:
        1. Берём только скалярные параметры корневого уровня
        2. Добавляем Password
        3. Сортируем по алфавиту
        4. Конкатенируем значения
        5. SHA-256 хеш
        """
        token_params = {}
        for key, value in params.items():
            if key == "Token":
                continue
            if isinstance(value, (str, int, float, bool)):
                token_params[key] = str(value)

        token_params["Password"] = self.secret_key
        sorted_keys = sorted(token_params.keys())
        values_str = "".join(token_params[k] for k in sorted_keys)

        return hashlib.sha256(values_str.encode("utf-8")).hexdigest()

    async def init_payment(
        self,
        amount: int,  # в копейках
        order_id: str,
        description: str,
        customer_key: str,
        success_url: str,
        fail_url: str,
        notification_url: str,
        receipt: Optional[Dict] = None,
        data: Optional[Dict] = None,
    ) -> Optional[Dict]:
        """
        Инициализация платежа

        Args:
            amount: Сумма в копейках (например, 29900 для 299₽)
            order_id: Уникальный ID заказа
            description: Описание платежа
            customer_key: ID пользователя в системе
            success_url: URL для успешной оплаты
            fail_url: URL для неуспешной оплаты
            notification_url: URL для вебхука уведомлений
        """
        # Параметры для токена (только корневые скаляры)
        token_base = {
            "TerminalKey": self.terminal_key,
            "Amount": amount,
            "OrderId": str(order_id),
            "Description": description[:140] if description else "",
            "CustomerKey": str(customer_key),
            "SuccessURL": success_url,
            "FailURL": fail_url,
            "NotificationURL": notification_url,
            "PayType": "O",  # Одностадийная оплата
            "Language": "ru",
        }

        token = self._generate_token(token_base)
        payload = {**token_base, "Token": token}

        # Добавляем вложенные объекты (не участвуют в токене!)
        if receipt:
            payload["Receipt"] = receipt
        if data:
            payload["DATA"] = data

        logger.debug(f"Init payment request: {order_id}, amount: {amount}")

        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(
                    f"{self.api_url}/Init",
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as response:
                    result = await response.json()

                    if result.get("Success"):
                        logger.info(f"Payment init success: {result.get('PaymentId')}")
                        return result
                    else:
                        logger.error(
                            f"Payment init failed: {result.get('ErrorCode')} - {result.get('Message')}"
                        )
                        return result

            except Exception as e:
                logger.exception(f"Payment init exception: {e}")
                return None

    async def get_state(self, payment_id: str) -> Optional[Dict]:
        """Проверка статуса платежа"""
        token_base = {"TerminalKey": self.terminal_key, "PaymentId": str(payment_id)}
        token = self._generate_token(token_base)
        payload = {**token_base, "Token": token}

        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(
                    f"{self.api_url}/GetState",
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as response:
                    return await response.json()
            except Exception as e:
                logger.exception(f"Get state exception: {e}")
                return None

    def verify_notification(self, data: Dict[str, Any]) -> bool:
        """
        Проверка подписи входящего уведомления от Т-Банка
        """
        received_token = data.pop("Token", None)
        if not received_token:
            return False

        # Генерируем ожидаемый токен
        expected_token = self._generate_token(data)

        # Восстанавливаем Token для возможной дальнейшей обработки
        data["Token"] = received_token

        return received_token == expected_token


# Создаём сервис
from bot.config import config

tbank_service = TBankService(
    terminal_key=config.TBANK_TERMINAL_KEY,
    secret_key=config.TBANK_SECRET_KEY,
    api_url=config.TBANK_API_URL,
)
