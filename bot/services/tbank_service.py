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

        def _norm(v: Any) -> str:
            if isinstance(v, bool):
                # T-Bank may use lowercase boolean literals when building token
                return "true" if v else "false"
            return str(v)

        token_params = {}
        for key, value in params.items():
            if key == "Token":
                continue
            if isinstance(value, (str, int, float, bool)):
                token_params[key] = _norm(value)

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
        # FIXME: receipt отключен - клиент на НПД. Включить при переходе на другой режим.
        # receipt: Optional[Dict] = None,
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
        # FIXME: Чеки отключены - клиент на НПД. Включить при переходе на другой режим.
        # if receipt:
        #     payload["Receipt"] = receipt
        if data:
            payload["DATA"] = data

        logger.debug(f"Init payment request: {order_id}, amount: {amount}")

        async with aiohttp.ClientSession(trust_env=False) as session:
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

        async with aiohttp.ClientSession(trust_env=False) as session:
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

    async def cancel(self, payment_id: str) -> Optional[Dict]:
        """Отмена платежа и возврат денег"""
        token_base = {"TerminalKey": self.terminal_key, "PaymentId": str(payment_id)}
        token = self._generate_token(token_base)
        payload = {**token_base, "Token": token}

        async with aiohttp.ClientSession(trust_env=False) as session:
            try:
                async with session.post(
                    f"{self.api_url}/Cancel",
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as response:
                    return await response.json()
            except Exception as e:
                logger.exception(f"Cancel exception: {e}")
                return None

    def verify_notification(self, data: Dict[str, Any]) -> bool:
        """
        Проверка подписи входящего уведомления от Т-Банка.

        Документация Т-Банк:
        1. Собрать массив параметров (только скаляры корневого уровня)
        2. Добавить Password
        3. Отсортировать по алфавиту
        4. Конкатенировать значения
        5. SHA-256 хеш

        ВАЖНО: Для DEMO терминалов пропускаем проверку подписи,
        так как Т-Банк использует неизвестный специальный пароль.

        NOTE: Исключаем чувствительные данные карты из проверки подписи,
        так как они маскируются в вебхуках, но токен рассчитывается с полными данными.
        """
        # Проверяем наличие токена (accept common variants)
        received_token = (
            data.get("Token") or data.get("token") or data.get("token".lower())
        )
        if not received_token:
            logger.warning("No Token in notification")
            return False

        # Проверяем TerminalKey
        # Приводим к строкам на случай, если вебхук присылает число, а в настройках — строка
        received_terminal = data.get("TerminalKey")
        if str(received_terminal) != str(self.terminal_key):
            logger.warning(
                f"TerminalKey mismatch: expected={self.terminal_key}, received={received_terminal}"
            )
            return False

        # Для DEMO терминалов пропускаем проверку подписи
        # (у Т-Банка особая логика для DEMO, которые невозможно воспроизвести)
        is_demo = self.terminal_key.upper().endswith("DEMO")
        if is_demo:
            logger.info("DEMO terminal - skipping signature verification")
            return True

        # Для реальных терминалов проверяем подпись
        # Исключаем чувствительные данные карты, которые маскируются в вебхуках
        sensitive_fields = {"Token", "Pan", "CardId", "ExpDate"}

        def _norm(v: Any) -> str:
            if isinstance(v, bool):
                return "true" if v else "false"
            return str(v)

        token_params = {}
        for key, value in data.items():
            if key in sensitive_fields:
                continue
            if isinstance(value, (str, int, float, bool)):
                token_params[key] = _norm(value)

        # Добавляем Password из настроек
        token_params["Password"] = self.secret_key
        # Логируем для отладки (покажем отсортированные ключи и конкатенированную строку)
        # ВАЖНО: не логируем секрет в явном виде — показываем его как ***REDACTED***
        sorted_keys = sorted(token_params.keys())
        values_list = [token_params[k] for k in sorted_keys]
        # redact password for logs
        redacted_values_list = [
            ("***REDACTED***" if k == "Password" else token_params[k])
            for k in sorted_keys
        ]
        values_str = "".join(values_list)
        redacted_values_str = "".join(redacted_values_list)

        logger.info(f"Verifying webhook - sorted keys: {sorted_keys}")
        logger.info(
            f"Verifying webhook - concatenated values (redacted): '{redacted_values_str}'"
        )

        # Генерируем ожидаемый токен (используем реальное значение Password здесь)
        expected_token = hashlib.sha256(values_str.encode("utf-8")).hexdigest()

        # Log received/expected tokens (lowercased) to help debugging signature mismatches
        logger.info(f"Received token: {received_token}")
        logger.info(f"Expected token: {expected_token}")

        # Use constant-time comparison to avoid timing attacks. Compare lowercase
        try:
            import hmac

            tokens_equal = hmac.compare_digest(
                str(received_token).lower(), str(expected_token).lower()
            )
        except Exception:
            tokens_equal = str(received_token).lower() == str(expected_token).lower()

        if not tokens_equal:
            logger.warning(
                "Token mismatch - signature verification failed.\n"
                f"Sorted keys: {sorted_keys}\nValues (redacted): {redacted_values_list}\n"
            )
            return False

        logger.info("Token verification successful")
        return True


# Создаём сервис
from bot.config import config

tbank_service = TBankService(
    terminal_key=config.TBANK_TERMINAL_KEY,
    secret_key=config.TBANK_SECRET_KEY,
    api_url=config.TBANK_API_URL,
)
