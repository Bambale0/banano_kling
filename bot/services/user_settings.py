import json
import logging
from pathlib import Path
from typing import Optional, Dict, Any
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)


@dataclass
class UserSettings:
    """Настройки пользователя"""
    user_id: int
    image_model: str = "flash"  # flash или pro
    video_quality: str = "std"  # std или pro
    default_aspect_ratio: str = "1:1"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict) -> "UserSettings":
        return cls(**data)


class UserSettingsManager:
    """Простое хранилище настроек в JSON"""

    def __init__(self, storage_path: str = "data/user_settings.json"):
        self.storage_path = Path(storage_path)
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self._cache: Dict[int, UserSettings] = {}
        self._load_all()

    def _load_all(self):
        """Загружает все настройки"""
        if self.storage_path.exists():
            try:
                with open(self.storage_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for user_id, settings_data in data.items():
                        self._cache[int(user_id)] = UserSettings.from_dict(settings_data)
            except Exception as e:
                logger.error(f"Failed to load settings: {e}")

    def _save_all(self):
        """Сохраняет все настройки"""
        try:
            data = {str(uid): s.to_dict() for uid, s in self._cache.items()}
            with open(self.storage_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Failed to save settings: {e}")

    def get_settings(self, user_id: int) -> UserSettings:
        """Получает настройки пользователя (создаёт дефолтные если нет)"""
        # Всегда перезагружаем из файла чтобы получить актуальные настройки
        self._load_all()
        if user_id not in self._cache:
            self._cache[user_id] = UserSettings(user_id=user_id)
            self._save_all()
        return self._cache[user_id]

    def update_settings(self, user_id: int, **kwargs):
        """Обновляет настройки"""
        settings = self.get_settings(user_id)
        for key, value in kwargs.items():
            if hasattr(settings, key):
                setattr(settings, key, value)
        self._save_all()

    def get_image_model(self, user_id: int) -> str:
        """Возвращает модель для генерации изображений"""
        return self.get_settings(user_id).image_model

    def get_video_quality(self, user_id: int) -> str:
        """Возвращает качество видео"""
        return self.get_settings(user_id).video_quality


# Глобальный менеджер
settings_manager = UserSettingsManager()
