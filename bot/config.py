import logging
import os
from dataclasses import dataclass
from typing import List

logger = logging.getLogger(__name__)


@dataclass
class Config:
    # Telegram
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")

    # T-Bank (эквайринг)
    TBANK_TERMINAL_KEY: str = os.getenv("TBANK_TERMINAL_KEY", "")
    TBANK_SECRET_KEY: str = os.getenv("TBANK_SECRET_KEY", "")
    TBANK_API_URL: str = os.getenv("TBANK_API_URL", "https://securepay.tinkoff.ru/v2/")
    TBANK_SUCCESS_URL: str = os.getenv("TBANK_SUCCESS_URL", "")

    # Crypto Bot
    # Backward-compatible fallback for older env files that still use
    # CRYPTOBOT_API_KEY instead of CRYPTOBOT_API_TOKEN.
    CRYPTOBOT_API_TOKEN: str = os.getenv("CRYPTOBOT_API_TOKEN", "") or os.getenv(
        "CRYPTOBOT_API_KEY", ""
    )
    CRYPTOBOT_BASE_URL: str = os.getenv("CRYPTOBOT_BASE_URL", "https://pay.crypt.bot")
    CRYPTOBOT_ACCEPTED_ASSETS: str = os.getenv(
        "CRYPTOBOT_ACCEPTED_ASSETS",
        "USDT,TON,BTC,ETH,LTC,BNB,TRX,USDC",
    )
    CRYPTOBOT_EXPIRES_IN: int = int(os.getenv("CRYPTOBOT_EXPIRES_IN", "3600"))
    PAYMENT_PROVIDER: str = os.getenv("PAYMENT_PROVIDER", "tbank").lower()

    # AI Services API Keys
    NANOBANANA_API_KEY: str = os.getenv("NANOBANANA_API_KEY", "")

    FREEPIK_API_KEY: str = os.getenv("FREEPIK_API_KEY", "")
    NOVITA_API_KEY: str = os.getenv("NOVITA_API_KEY", "")
    REPLICATE_API_TOKEN: str = os.getenv("REPLICATE_API_TOKEN", "")
    # Optional secret used to verify incoming Replicate webhooks (HMAC SHA256).
    # If set, the webhook handler will validate signatures to prevent spoofing.
    REPLICATE_WEBHOOK_SECRET: str = os.getenv("REPLICATE_WEBHOOK_SECRET", "")
    KIE_AI_API_KEY: str = os.getenv("KIE_AI_API_KEY", "")
    KIE_AI_WEBHOOK_PATH: str = os.getenv("KIE_AI_WEBHOOK_PATH", "/webhook/kie_ai")

    # Legacy API Keys (optional fallbacks)
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    KLING_API_KEY: str = os.getenv("KLING_API_KEY", "")
    # PIAPI_API_KEY is used by kling_service. Allow fallback to KLING_API_KEY
    # for environments that still provide the old variable name.
    PIAPI_API_KEY: str = os.getenv("PIAPI_API_KEY", "") or os.getenv(
        "KLING_API_KEY", ""
    )

    # NSFW Content Control
    ALLOW_NSFW: bool = os.getenv("ALLOW_NSFW", "0").lower() in (
        "1",
        "true",
        "yes",
        "on",
    )

    # API Endpoints
    NANOBANANA_BASE_URL: str = "https://api.nanobanana.com/v1"

    FREEPIK_BASE_URL: str = "https://api.freepik.com/v1"
    KLING_BASE_URL: str = "https://api.freepik.com/v1"  # Legacy alias
    PIAPI_BASE_URL: str = "https://api.piapi.ai"
    NOVITA_BASE_URL: str = "https://api.novita.ai"

    KIE_BASE_URL: str = "https://api.kie.ai"

    # Вебхуки
    # WEBHOOK_HOST must be the full external URL, e.g. "https://example.com"
    WEBHOOK_HOST: str = os.getenv("WEBHOOK_HOST", "")
    # NOTE: previously a typo included a leading space in the env var name
    # which caused WEBHOOK_PATH to be empty even when WEBHOOK_PATH was set.
    # Default to "/webhook" to avoid registering an empty route in aiohttp.
    WEBHOOK_PATH: str = os.getenv("WEBHOOK_PATH", "/webhook")
    WEBHOOK_PORT: int = int(os.getenv("WEBHOOK_PORT", "8443"))

    # База данных
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///bot.db")

    # Партнёрская программа
    PARTNER_OFFER_URL: str = os.getenv("PARTNER_OFFER_URL", "")
    PARTNER_RULES_URL: str = os.getenv("PARTNER_RULES_URL", "")
    PARTNER_MIN_WITHDRAWAL_RUB: int = int(
        os.getenv("PARTNER_MIN_WITHDRAWAL_RUB", "2000")
    )
    JUMP_FINANCE_CLIENT_KEY: str = os.getenv("JUMP_FINANCE_CLIENT_KEY", "")
    JUMP_FINANCE_BASE_URL: str = os.getenv(
        "JUMP_FINANCE_BASE_URL", "https://api.jump.finance/services/openapi"
    )
    JUMP_FINANCE_AGENT_ID: int = int(os.getenv("JUMP_FINANCE_AGENT_ID", "0"))
    JUMP_FINANCE_BANK_ACCOUNT_ID: int = int(
        os.getenv("JUMP_FINANCE_BANK_ACCOUNT_ID", "0")
    )
    JUMP_FINANCE_PAYOUT_SERVICE_NAME: str = os.getenv(
        "JUMP_FINANCE_PAYOUT_SERVICE_NAME",
        "Партнерское вознаграждение",
    )
    JUMP_FINANCE_PAYOUT_PURPOSE: str = os.getenv(
        "JUMP_FINANCE_PAYOUT_PURPOSE",
        "Выплата партнерского вознаграждения",
    )

    # Пути к JSON
    PRESETS_PATH: str = "data/presets.json"
    PRICE_PATH: str = "data/price.json"

    # Админы (список ID через запятую)
    ADMIN_IDS_STR: str = os.getenv("ADMIN_IDS", "")

    @property
    def admin_ids(self) -> List[int]:
        """Парсит список ID админов из строки"""
        if not self.ADMIN_IDS_STR:
            return []
        try:
            return [
                int(id.strip()) for id in self.ADMIN_IDS_STR.split(",") if id.strip()
            ]
        except ValueError:
            logger.warning(f"Invalid ADMIN_IDS format: {self.ADMIN_IDS_STR}")
            return []

    def is_admin(self, telegram_id: int) -> bool:
        """Проверяет, является ли пользователь админом"""
        return telegram_id in self.admin_ids

    @property
    def webhook_url(self) -> str:
        # Normalize joining host and path to avoid double-slashes or missing slash
        host = (self.WEBHOOK_HOST or "").rstrip("/")
        path = self.WEBHOOK_PATH or "/webhook"
        if not path.startswith("/"):
            path = "/" + path
        return f"{host}{path}"

    @property
    def tbank_notification_url(self) -> str:
        return f"{self.WEBHOOK_HOST}/tbank/webhook"

    @property
    def cryptobot_notification_url(self) -> str:
        return f"{self.WEBHOOK_HOST}/cryptobot/webhook"

    @property
    def payment_provider(self) -> str:
        if self.PAYMENT_PROVIDER in {"cryptobot", "tbank"}:
            return self.PAYMENT_PROVIDER
        return "tbank"

    @property
    def has_cryptobot(self) -> bool:
        return bool(self.CRYPTOBOT_API_TOKEN)

    @property
    def has_jump_finance(self) -> bool:
        return bool(self.JUMP_FINANCE_CLIENT_KEY and self.JUMP_FINANCE_AGENT_ID > 0)

    @property
    def kling_notification_url(self) -> str:
        return f"{self.WEBHOOK_HOST}/webhook/kling"

    @property
    def replicate_notification_url(self) -> str:
        return f"{self.WEBHOOK_HOST}/webhook/replicate"

    @property
    def z_image_turbo_notification_url(self) -> str:
        return f"{self.WEBHOOK_HOST}/webhook/z-image-turbo"

    @property
    def kie_notification_url(self) -> str:
        path = self.KIE_AI_WEBHOOK_PATH
        if not path.startswith("/"):
            path = "/" + path
        return f"{self.WEBHOOK_HOST.rstrip('/')}{path}"

    @property
    def wanx_notification_url(self) -> str:
        return f"{self.WEBHOOK_HOST}/webhook/wanx"

    def _old_kling_notification_url(self) -> str:
        return f"{self.WEBHOOK_HOST}/webhook/kling"

    @property
    def static_base_url(self) -> str:
        """URL для доступа к статическим файлам"""
        if hasattr(self, "STATIC_BASE_URL") and self.STATIC_BASE_URL:
            return self.STATIC_BASE_URL
        # По умолчанию используем WEBHOOK_HOST
        return (
            self.WEBHOOK_HOST if self.WEBHOOK_HOST else "https://dev.chillcreative.ru"
        )


config = Config()
