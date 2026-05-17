import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import List

logger = logging.getLogger(__name__)

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
except Exception:
    pass


@dataclass
class Config:
    # Telegram
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")

    CHANNEL_USERNAME: str = "@FS_2Loop"

    # YooKassa
    YOOKASSA_SHOP_ID: str = os.getenv("YOOKASSA_SHOP_ID", "")
    YOOKASSA_SECRET_KEY: str = os.getenv("YOOKASSA_SECRET_KEY", "")
    YOOKASSA_RETURN_URL: str = os.getenv("YOOKASSA_RETURN_URL", "")
    YOOKASSA_WEBHOOK_SECRET: str = os.getenv("YOOKASSA_WEBHOOK_SECRET", "")
    YOOKASSA_RECEIPT_EMAIL: str = os.getenv(
        "YOOKASSA_RECEIPT_EMAIL", "payments@2loop.chillcreative.ru"
    )
    YOOKASSA_RECEIPT_PHONE: str = os.getenv("YOOKASSA_RECEIPT_PHONE", "")
    YOOKASSA_VAT_CODE: int = int(os.getenv("YOOKASSA_VAT_CODE", "1"))
    YOOKASSA_PAYMENT_SUBJECT: str = os.getenv("YOOKASSA_PAYMENT_SUBJECT", "service")
    YOOKASSA_PAYMENT_MODE: str = os.getenv(
        "YOOKASSA_PAYMENT_MODE", "full_prepayment"
    )
    PAYMENT_PROVIDER: str = os.getenv("PAYMENT_PROVIDER", "yookassa")

    # Robokassa
    ROBOKASSA_MERCHANT_LOGIN: str = os.getenv("ROBOKASSA_MERCHANT_LOGIN", "")
    ROBOKASSA_PASSWORD1: str = os.getenv("ROBOKASSA_PASSWORD1", "")
    ROBOKASSA_PASSWORD2: str = os.getenv("ROBOKASSA_PASSWORD2", "")
    ROBOKASSA_TEST: bool = os.getenv("ROBOKASSA_TEST", "0").lower() in (
        "1",
        "true",
        "yes",
    )
    BOT_USERNAME: str = os.getenv("BOT_USERNAME", "")

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
    KIE_AI_WEBHOOK_SECRET: str = os.getenv("KIE_AI_WEBHOOK_SECRET", "")
    KIE_AI_REQUIRE_WEBHOOK_SECRET: bool = os.getenv(
        "KIE_AI_REQUIRE_WEBHOOK_SECRET", "1"
    ).lower() in ("1", "true", "yes", "on")
    KIE_BASE_URL: str = os.getenv("KIE_BASE_URL", "https://api.kie.ai")

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

    # Вебхуки
    # WEBHOOK_HOST must be the full external URL, e.g. "https://example.com"
    WEBHOOK_HOST: str = os.getenv("WEBHOOK_HOST", "")
    WEBHOOK_IP: str = os.getenv("WEBHOOK_IP", "")
    # NOTE: previously a typo included a leading space in the env var name
    # which caused WEBHOOK_PATH to be empty even when WEBHOOK_PATH was set.
    # Default to "/webhook" to avoid registering an empty route in aiohttp.
    WEBHOOK_PATH: str = os.getenv("WEBHOOK_PATH", "/webhook")
    WEBHOOK_PORT: int = int(os.getenv("WEBHOOK_PORT", "8443"))

    # База данных
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///bot.db")
    POSTGRES_DSN: str = os.getenv("POSTGRES_DSN", "")
    REQUIRE_POSTGRES_REDIS: bool = os.getenv(
        "REQUIRE_POSTGRES_REDIS", "1"
    ).lower() in ("1", "true", "yes", "on")

    # Redis / FSM storage
    REDIS_URL: str = os.getenv("REDIS_URL", "")
    FSM_STORAGE: str = os.getenv("FSM_STORAGE", "redis")
    FSM_REDIS_PREFIX: str = os.getenv("FSM_REDIS_PREFIX", "2loop:fsm")

    # Партнёрская программа
    PARTNER_OFFER_URL: str = os.getenv("PARTNER_OFFER_URL", "")
    PARTNER_RULES_URL: str = os.getenv("PARTNER_RULES_URL", "")
    PARTNER_MIN_WITHDRAWAL_RUB: int = int(
        os.getenv("PARTNER_MIN_WITHDRAWAL_RUB", "2000")
    )

    # Пути к JSON
    PRESETS_PATH: str = "data/presets.json"
    PRICE_PATH: str = "data/price.json"

    # Публичная статика, которую nginx раздаёт наружу.
    STATIC_ROOT: str = os.getenv("TWOLOOP_STATIC_ROOT", "/var/www/2loop/static")
    UPLOADS_ROOT: str = os.getenv(
        "TWOLOOP_UPLOADS_ROOT", os.path.join(STATIC_ROOT, "uploads")
    )
    MINIAPP_ADMIN_ONLY: bool = os.getenv(
        "TWOLOOP_MINIAPP_ADMIN_ONLY", "1"
    ).lower() in ("1", "true", "yes", "on")

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
    def effective_postgres_dsn(self) -> str:
        """Postgres DSN can be provided explicitly or via DATABASE_URL."""
        if self.POSTGRES_DSN:
            return self.POSTGRES_DSN
        if self.DATABASE_URL.startswith(("postgres://", "postgresql://")):
            return self.DATABASE_URL
        return ""

    def validate_required_infra_config(self) -> None:
        """Fail fast when mandatory Redis/Postgres config is absent."""
        if not self.REQUIRE_POSTGRES_REDIS:
            return
        if not self.effective_postgres_dsn:
            raise RuntimeError(
                "PostgreSQL is required: set POSTGRES_DSN or DATABASE_URL=postgresql://..."
            )
        if not self.REDIS_URL:
            raise RuntimeError("Redis is required: set REDIS_URL")
        if (self.FSM_STORAGE or "").lower() != "redis":
            raise RuntimeError("Redis FSM is required: set FSM_STORAGE=redis")

    @property
    def webhook_url(self) -> str:
        # Normalize joining host and path to avoid double-slashes or missing slash
        host = (self.WEBHOOK_HOST or "").rstrip("/")
        path = self.WEBHOOK_PATH or "/webhook"
        if not path.startswith("/"):
            path = "/" + path
        return f"{host}{path}"

    @property
    def yookassa_notification_url(self) -> str:
        return f"{self.WEBHOOK_HOST}/yookassa/webhook"

    @property
    def payment_provider(self) -> str:
        return self.PAYMENT_PROVIDER

    @property
    def has_yookassa(self) -> bool:
        return bool(self.YOOKASSA_SHOP_ID and self.YOOKASSA_SECRET_KEY)

    @property
    def has_robokassa(self) -> bool:
        return bool(
            self.ROBOKASSA_MERCHANT_LOGIN
            and self.ROBOKASSA_PASSWORD1
            and self.ROBOKASSA_PASSWORD2
        )

    @property
    def robokassa_result_url(self) -> str:
        host = self.WEBHOOK_HOST.rstrip("/")
        return f"{host}/robokassa/result"

    @property
    def robokassa_success_url(self) -> str:
        host = self.WEBHOOK_HOST.rstrip("/")
        return f"{host}/robokassa/success"

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

    def public_upload_dir(self, *parts: str) -> str:
        """Физический путь для файлов, доступных по /uploads/..."""
        return os.path.join(self.UPLOADS_ROOT, *parts)

    def public_upload_url(self, *parts: str) -> str:
        """Публичный URL для файлов из public_upload_dir."""
        path = "/".join(part.strip("/") for part in parts if part)
        return f"{self.static_base_url.rstrip('/')}/uploads/{path}"


config = Config()
