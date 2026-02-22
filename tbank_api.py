"""Модуль для работы с API Т-Банк (эквайринг)."""
import hashlib
import json
import logging
from typing import Dict, List, Optional

import requests

logger = logging.getLogger(__name__)


class TBankAPI:
    """Класс для работы с API Т-Банк по документации https://developer.tbank.ru/eacq/api"""

    def __init__(self, terminal_key: str, secret_key: str, api_url: str):
        self.terminal_key = terminal_key
        self.secret_key = secret_key
        self.api_url = api_url.rstrip("/")

    def _generate_token(self, params: Dict) -> str:
        """
        Генерация токена подписи по документации Т-Банк:

        1. Берём только параметры корневого объекта (без вложенных объектов и массивов)
        2. Добавляем {"Password": secret_key}
        3. Сортируем по алфавиту по ключу
        4. Конкатенируем значения в одну строку
        5. SHA-256 хеш
        """
        # Берём только скалярные параметры корневого уровня (str, int, bool)
        # Исключаем: Token, Receipt, DATA, Shops и другие объекты/массивы
        token_params = {}
        for key, value in params.items():
            # Пропускаем Token и сложные объекты
            if key == "Token":
                continue
            if isinstance(value, (str, int, float, bool)):
                token_params[key] = str(value)

        # Добавляем Password
        token_params["Password"] = self.secret_key

        # Сортируем по алфавиту
        sorted_keys = sorted(token_params.keys())

        # Конкатенируем значения
        values_str = "".join(token_params[k] for k in sorted_keys)

        # SHA-256
        return hashlib.sha256(values_str.encode("utf-8")).hexdigest()

    def init_payment(
        self,
        amount: int,  # в копейках
        order_id: str,
        description: str,
        customer_key: str,
        success_url: str,
        fail_url: str,
        notification_url: str,
        pay_type: str = "O",  # O - одностадийная, T - двухстадийная
        receipt: Optional[Dict] = None,
        data: Optional[Dict] = None,
    ) -> Optional[Dict]:
        """
        Инициализация платежа (метод Init).

        Параметры Receipt и DATA не участвуют в формировании токена!
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
            "PayType": pay_type,
            "Language": "ru",
        }

        # Формируем токен
        token = self._generate_token(token_base)

        # Итоговый payload с токеном и доп. объектами
        payload = {**token_base, "Token": token}

        # Добавляем вложенные объекты (не участвуют в токене!)
        if receipt:
            payload["Receipt"] = receipt
        if data:
            payload["DATA"] = data

        logger.debug(f"Init request: {json.dumps(payload, ensure_ascii=False)}")

        try:
            response = requests.post(
                f"{self.api_url}/Init",
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=15,
            )
            response.raise_for_status()
            result = response.json()

            logger.info(
                f"Init response: {result.get('Success')}, PaymentId={result.get('PaymentId')}"
            )

            if result.get("Success"):
                return result
            else:
                logger.error(
                    f"Init failed: {result.get('ErrorCode')} - {result.get('Message')}"
                )
                return None

        except Exception as e:
            logger.exception(f"Init request failed: {e}")
            return None

    def get_state(self, payment_id: str) -> Optional[Dict]:
        """Проверка статуса платежа (метод GetState)."""
        # Только скалярные параметры
        token_base = {"TerminalKey": self.terminal_key, "PaymentId": str(payment_id)}

        token = self._generate_token(token_base)

        payload = {**token_base, "Token": token}

        try:
            response = requests.post(
                f"{self.api_url}/GetState",
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=10,
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.exception(f"GetState failed: {e}")
            return None

    def confirm(self, payment_id: str, amount: int = None) -> Optional[Dict]:
        """Подтверждение списания для двухстадийного платежа (метод Confirm)."""
        token_base = {"TerminalKey": self.terminal_key, "PaymentId": str(payment_id)}
        if amount is not None:
            token_base["Amount"] = amount

        token = self._generate_token(token_base)

        payload = {**token_base, "Token": token}

        try:
            response = requests.post(
                f"{self.api_url}/Confirm",
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=10,
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.exception(f"Confirm failed: {e}")
            return None

    def cancel(self, payment_id: str) -> Optional[Dict]:
        """Отмена платежа (метод Cancel)."""
        token_base = {"TerminalKey": self.terminal_key, "PaymentId": str(payment_id)}

        token = self._generate_token(token_base)

        payload = {**token_base, "Token": token}

        try:
            response = requests.post(
                f"{self.api_url}/Cancel",
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=10,
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.exception(f"Cancel failed: {e}")
            return None

    def build_receipt(
        self, email: str, phone: str, items: List[Dict], taxation: str = "osn"
    ) -> Dict:
        """
        Формирование чека для 54-ФЗ.

        items: [{"Name": "...", "Price": 10000, "Quantity": 1.0, "Amount": 10000, "Tax": "none"}]
        """
        return {"Email": email, "Phone": phone, "Taxation": taxation, "Items": items}
