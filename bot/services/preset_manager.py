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
        # Фиксированные цены для fallback
        self._fixed_image_costs = {
            "novita": 3,
            "nanobanana": 3,
            "banana_pro": 5,
            "seedream": 3,
            "z_image_turbo": 3,
        }
        self._fixed_video_costs = {
            "v3_std": 6,
            "v3_pro": 8,
            "v3_omni_std": 8,
            "v3_omni_pro": 8,
            "v3_omni_std_r2v": 8,
            "v3_omni_pro_r2v": 8,
            "v26_pro": 8,
            "v26_motion_pro": 10,
            "v26_motion_std": 8,
            "wanx_lora": 15,
        }
        self.load_all()

    def load_all(self):
        """Загружает все конфигурации"""
        self._load_presets()
        self._load_price()

    def _load_presets(self):
        """Загружает пресеты из JSON (необязательно)"""
        if not self.presets_path.exists():
            # Пресеты больше не используются
            self._categories = {}
            self._presets = {}
            self._default_values = {}
            return

        try:
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
        except Exception as e:
            print(f"Error loading presets: {e}")
            self._categories = {}
            self._presets = {}
            self._default_values = {}

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

    def get_generation_cost(self, model: str, options: dict = None) -> int:
        """
        Возвращает стоимость генерации на основе модели и опций.
        Использует costs_reference из price.json.

        Args:
            model: Идентификатор модели (gemini_2_5_flash, v3_pro, и т.д.)
            options: Дополнительные опции (duration для видео, и т.д.)

        Returns:
            Стоимость в бананах
        """
        costs = self._price_config.get("costs_reference", {})
        image_models = costs.get("image_models", {})
        legacy_keys = costs.get("legacy_keys", {})

        # Normalize model name
        model_lower = model.lower()

        # Map модельных имён к ключам image_models
        model_map = {
            "gemini-2.5-flash-image": "gemini_2_5_flash",
            "gemini-2.5-flash": "gemini_2_5_flash",
            "gemini-3-pro-image-preview": "gemini_3_pro",
            "gemini-3-pro": "gemini_3_pro",
            "gemini-3.1-flash-image-preview": "banana_2",
            "flash": "gemini_2_5_flash",
            "pro": "gemini_3_pro",
            "banana_2": "banana_2",
            "banana_pro": "nano-banana-pro",
            "nano_banana_pro": "nano-banana-pro",
            "z_image_turbo": "z_image_turbo",
            "z-image-turbo": "z_image_turbo",
            "seedream": "seedream",
            "flux_pro": "flux_pro",
            "seedream_lite": "seedream_lite",
        }

        mapped_key = model_map.get(model_lower)

        # Check image_models first
        if mapped_key and mapped_key in image_models:
            return image_models[mapped_key]

        # Fallback to legacy_keys
        if mapped_key and mapped_key in legacy_keys:
            return legacy_keys[mapped_key]

        # Direct lookup
        if model_lower in image_models:
            return image_models[model_lower]
        if model_lower in legacy_keys:
            return legacy_keys[model_lower]

        # Default cost
        return 3

    def get_video_cost(self, model: str, duration: int = 5) -> int:
        """
        Возвращает стоимость генерации видео.

        Args:
            model: Модель (v3_pro, v3_std, v3_omni_pro, v3_omni_std, и т.д.)
            duration: Длительность в секундах (3-15)

        Returns:
            Стоимость в бананах
        """
        costs = self._price_config.get("costs_reference", {})
        video_models = costs.get("video_models", {})
        video_duration_costs = costs.get("video_duration_costs", {})

        # Normalize duration
        duration = max(3, min(15, duration))

        # Normalize model name
        model_lower = model.lower()

        # Map модельных имён к ключам video_models
        model_map = {
            # Kling 3
            "v3_std": "v3_std",
            "v3_pro": "v3_pro",
            "kling-v3-std": "v3_std",
            "kling-v3-pro": "v3_pro",
            "kling_v3_std": "v3_std",
            "kling_v3_pro": "v3_pro",
        }


        mapped_model = model_map.get(model_lower, model_lower)

        # Check if model exists in video_models
        if mapped_model in video_models:
            model_config = video_models[mapped_model]
            duration_costs = model_config.get("duration_costs", {})
            if str(duration) in duration_costs:
                return duration_costs[str(duration)]
            # If duration not found, return base cost
            return model_config.get("base", 8)

        # Fallback to legacy video_duration_costs
        if str(duration) in video_duration_costs:
            return video_duration_costs[str(duration)]

        # Default fallback based on model type
        if "pro" in model_lower or "omni" in model_lower:
            if duration <= 5:
                return 8
            elif duration <= 10:
                return 14
            else:
                return 16
        else:  # std
            if duration <= 5:
                return 6
            elif duration <= 10:
                return 8
            else:
                return 10

    def get_image_cost(self, model: str) -> int:
        """
        Возвращает стоимость генерации изображения.

        Args:
            model: Модель (gemini_2_5_flash, gemini_3_pro, и т.д.)

        Returns:
            Стоимость в бананах
        """
        return self.get_generation_cost(model)


# Глобальный менеджер пресетов
preset_manager = PresetManager()
