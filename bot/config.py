import os
import logging
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

    # AI Services API Keys
    OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "")
    NANOBANANA_API_KEY: str = os.getenv("NANOBANANA_API_KEY", "")
    FREEPIK_API_KEY: str = os.getenv("FREEPIK_API_KEY", "")

    # Legacy API Keys (optional fallbacks)
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    KLING_API_KEY: str = os.getenv("KLING_API_KEY", "")

    # API Endpoints
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    NANOBANANA_BASE_URL: str = "https://api.nanobanana.com/v1"
    FREEPIK_BASE_URL: str = "https://api.freepik.com/v1"
    KLING_BASE_URL: str = "https://api.freepik.com/v1"  # Legacy alias

    # Вебхуки
    WEBHOOK_HOST: str = os.getenv("WEBHOOK_HOST", "")
    WEBHOOK_PATH: str = "/webhook"
    WEBHOOK_PORT: int = int(os.getenv("WEBHOOK_PORT", "8080"))

    # База данных
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///bot.db")

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
            return [int(id.strip()) for id in self.ADMIN_IDS_STR.split(",") if id.strip()]
        except ValueError:
            logger.warning(f"Invalid ADMIN_IDS format: {self.ADMIN_IDS_STR}")
            return []
    
    def is_admin(self, telegram_id: int) -> bool:
        """Проверяет, является ли пользователь админом"""
        return telegram_id in self.admin_ids
    
    @property
    def webhook_url(self) -> str:
        return f"{self.WEBHOOK_HOST}{self.WEBHOOK_PATH}"

    @property
    def tbank_notification_url(self) -> str:
        return f"{self.WEBHOOK_HOST}/webhook/tbank"

    @property
    def kling_notification_url(self) -> str:
        return f"{self.WEBHOOK_HOST}/webhook/kling"


config = Config()
