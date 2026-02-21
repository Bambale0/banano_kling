import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class Preset:
    id: str
    name: str
    prompt: str
    cost: int
    model: str
    requires_input: bool
    requires_upload: bool = False
    input_prompt: Optional[str] = None
    placeholders: List[str] = field(default_factory=list)
    aspect_ratio: Optional[str] = None
    duration: Optional[int] = None
    category: str = ""

    def format_prompt(self, **kwargs) -> str:
        """Заполняет плейсхолдеры в промпте"""
        try:
            return self.prompt.format(**kwargs)
        except KeyError as e:
            # Если не все плейсхолдеры заполнены, возвращаем базовый промпт
            return self.prompt


class PresetManager:
    def __init__(
        self,
        presets_path: str = "data/presets.json",
        price_path: str = "data/price.json",
    ):
        self.presets_path = Path(presets_path)
        self.price_path = Path(price_path)
        self._presets: Dict[str, Preset] = {}
        self._categories: Dict[str, Dict] = {}
        self._price_config: Dict = {}
        self._admin_ids: List[int] = []
        self._default_values: Dict[str, List[str]] = {}
        self.load_all()

    def load_all(self):
        """Загружает все конфигурации"""
        self._load_presets()
        self._load_price()

    def _load_presets(self):
        """Загружает пресеты из JSON"""
        if not self.presets_path.exists():
            raise FileNotFoundError(f"Presets file not found: {self.presets_path}")

        with open(self.presets_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self._categories = data.get("categories", {})
        self._presets = {}

        for cat_key, cat_data in self._categories.items():
            for preset_data in cat_data.get("presets", []):
                preset = Preset(
                    id=preset_data["id"],
                    name=preset_data["name"],
                    prompt=preset_data["prompt"],
                    cost=preset_data["cost"],
                    model=preset_data.get("model", "gemini-2.5-flash-image"),
                    requires_input=preset_data.get("requires_input", False),
                    requires_upload=preset_data.get("requires_upload", False),
                    input_prompt=preset_data.get("input_prompt"),
                    placeholders=preset_data.get("placeholders", []),
                    aspect_ratio=preset_data.get("aspect_ratio"),
                    duration=preset_data.get("duration"),
                    category=cat_key,
                )
                self._presets[preset.id] = preset

        # Загружаем значения по умолчанию
        self._default_values = data.get("default_values", {})

    def _load_price(self):
        """Загружает прайс-лист"""
        if not self.price_path.exists():
            raise FileNotFoundError(f"Price file not found: {self.price_path}")

        with open(self.price_path, "r", encoding="utf-8") as f:
            self._price_config = json.load(f)
        self._admin_ids = self._price_config.get("admin_ids", [])

    def reload(self) -> bool:
        """Перезагружает конфигурацию без перезапуска бота"""
        try:
            self.load_all()
            return True
        except Exception as e:
            print(f"Error reloading presets: {e}")
            return False

    def get_preset(self, preset_id: str) -> Optional[Preset]:
        """Возвращает пресет по ID"""
        return self._presets.get(preset_id)

    def get_category_presets(self, category: str) -> List[Preset]:
        """Возвращает пресеты категории"""
        cat_data = self._categories.get(category, {})
        preset_ids = [p["id"] for p in cat_data.get("presets", [])]
        return [self._presets[pid] for pid in preset_ids if pid in self._presets]

    def get_categories(self) -> Dict[str, Dict]:
        """Возвращает все категории с метаданными"""
        return {
            key: {"name": data["name"], "description": data.get("description", "")}
            for key, data in self._categories.items()
        }

    def get_packages(self) -> List[Dict]:
        """Возвращает пакеты кредитов"""
        return self._price_config.get("packages", [])

    def get_package(self, package_id: str) -> Optional[Dict]:
        """Возвращает пакет по ID"""
        for pkg in self.get_packages():
            if pkg["id"] == package_id:
                return pkg
        return None

    def is_admin(self, user_id: int) -> bool:
        """Проверяет, является ли пользователь администратором"""
        return user_id in self._admin_ids

    def get_default_values(self, key: str) -> List[str]:
        """Возвращает значения по умолчанию для плейсхолдеров"""
        return self._default_values.get(key, [])

    def get_all_presets(self) -> Dict[str, Preset]:
        """Возвращает все пресеты"""
        return self._presets.copy()


# Глобальный менеджер пресетов
preset_manager = PresetManager()
