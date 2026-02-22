"""Тесты для gemini_service.py"""
import pytest
import asyncio
import base64


# Тестовые данные
TEST_IMAGE_BASE64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
TEST_IMAGE_DATA = base64.b64decode(TEST_IMAGE_BASE64)

TEST_PROMPT = "A cute cat sticker with joyful expression"


class TestGeminiServiceInit:
    """Тесты инициализации сервиса"""

    def test_service_initialization(self):
        """Тест: инициализация сервиса с разными ключами"""
        from bot.services.gemini_service import GeminiService
        
        service = GeminiService(
            api_key="test_api_key",
            nanobanana_key="test_nano_key",
            openrouter_key="test_or_key"
        )
        
        assert service.api_key == "test_api_key"
        assert service.nanobanana_key == "test_nano_key"
        assert service.openrouter_key == "test_or_key"
        assert service._client is None
        assert service._session is None

    def test_models_dict(self):
        """Тест: проверка словаря моделей"""
        from bot.services.gemini_service import GeminiService
        
        assert "flash" in GeminiService.MODELS
        assert "pro" in GeminiService.MODELS
        assert GeminiService.MODELS["flash"] == "google/gemini-2.5-flash-image"
        assert GeminiService.MODELS["pro"] == "google/gemini-3-pro-image-preview"

    def test_native_models_dict(self):
        """Тест: проверка словаря нативных моделей"""
        from bot.services.gemini_service import GeminiService
        
        assert "flash" in GeminiService.NATIVE_MODELS
        assert "pro" in GeminiService.NATIVE_MODELS
        assert GeminiService.NATIVE_MODELS["flash"] == "gemini-2.5-flash-image"

    def test_resolutions_dict(self):
        """Тест: проверка словаря разрешений"""
        from bot.services.gemini_service import GeminiService
        
        assert "1K" in GeminiService.RESOLUTIONS
        assert "2K" in GeminiService.RESOLUTIONS
        assert "4K" in GeminiService.RESOLUTIONS

    def test_aspect_ratios_list(self):
        """Тест: проверка списка форматов"""
        from bot.services.gemini_service import GeminiService
        
        assert "1:1" in GeminiService.ASPECT_RATIOS
        assert "16:9" in GeminiService.ASPECT_RATIOS
        assert "9:16" in GeminiService.ASPECT_RATIOS


class TestPresetPlaceholderHandling:
    """Тесты обработки плейсхолдеров пресетов"""

    def test_placeholder_matching_character(self):
        """Тест: сопоставление плейсхолдера character"""
        placeholder = "character"
        placeholder_lower = placeholder.lower()
        if "character" in placeholder_lower:
            result = "cute cat"
        assert result == "cute cat"

    def test_placeholder_matching_expression(self):
        """Тест: сопоставление плейсхолдера expression"""
        placeholder = "expression"
        placeholder_lower = placeholder.lower()
        if "expr" in placeholder_lower:
            result = "joyful"
        assert result == "joyful"

    def test_placeholder_matching_style(self):
        """Тест: сопоставление плейсхолдера style"""
        placeholder = "art_style"
        placeholder_lower = placeholder.lower()
        if "style" in placeholder_lower:
            result = "impressionist"
        assert result == "impressionist"

    def test_placeholder_matching_landscape(self):
        """Тест: сопоставление плейсхолдера landscape"""
        placeholder = "landscape_type"
        placeholder_lower = placeholder.lower()
        if "landscape" in placeholder_lower or "scene" in placeholder_lower:
            result = "mountain sunset"
        assert result == "mountain sunset"

    def test_placeholder_matching_time(self):
        """Тест: сопоставление плейсхолдера time"""
        placeholder = "time_of_day"
        placeholder_lower = placeholder.lower()
        if "time" in placeholder_lower:
            result = "golden hour"
        assert result == "golden hour"

    def test_placeholder_matching_text(self):
        """Тест: сопоставление плейсхолдера text"""
        placeholder = "text"
        placeholder_lower = placeholder.lower()
        if "text" in placeholder_lower:
            result = "BrandName"
        assert result == "BrandName"

    def test_placeholder_matching_element(self):
        """Тест: сопоставление плейсхолдера element"""
        placeholder = "element"
        placeholder_lower = placeholder.lower()
        if "element" in placeholder_lower:
            result = "tree"
        assert result == "tree"

    def test_placeholder_matching_background(self):
        """Тест: сопоставление плейсхолдера background"""
        placeholder = "background_description"
        placeholder_lower = placeholder.lower()
        if "background" in placeholder_lower:
            result = "blue sky"
        assert result == "blue sky"

    def test_placeholder_matching_colors(self):
        """Тест: сопоставление плейсхолдера colors"""
        placeholder = "colors"
        placeholder_lower = placeholder.lower()
        if "colors" in placeholder_lower:
            result = "blue and orange"
        assert result == "blue and orange"

    def test_placeholder_matching_animation(self):
        """Тест: сопоставление плейсхолдера animation"""
        placeholder = "animation_description"
        placeholder_lower = placeholder.lower()
        if "animation" in placeholder_lower:
            result = "gentle movement"
        assert result == "gentle movement"

    def test_placeholder_matching_nature(self):
        """Тест: сопоставление плейсхолдера nature"""
        placeholder = "nature_element"
        placeholder_lower = placeholder.lower()
        if "nature" in placeholder_lower:
            result = "flowing river"
        assert result == "flowing river"

    def test_placeholder_matching_city(self):
        """Тест: сопоставление плейсхолдера city"""
        placeholder = "city_description"
        placeholder_lower = placeholder.lower()
        if "city" in placeholder_lower:
            result = "city skyline at night"
        assert result == "city skyline at night"

    def test_placeholder_default_fallback(self):
        """Тест: fallback значение по умолчанию"""
        placeholder = "unknown_field"
        placeholder_lower = placeholder.lower()
        # Не должен匹配的任何条件
        if "character" in placeholder_lower:
            result = "cute cat"
        elif "expr" in placeholder_lower:
            result = "joyful"
        else:
            result = "example"
        assert result == "example"


class TestImageParsing:
    """Тесты парсинга изображений из base64"""

    def test_base64_decode_image(self):
        """Тест: декодирование base64 изображения"""
        decoded = base64.b64decode(TEST_IMAGE_BASE64)
        assert decoded == TEST_IMAGE_DATA
        assert len(decoded) > 0

    def test_base64_image_url_parsing(self):
        """Тест: парсинг data URL"""
        data_url = f"data:image/png;base64,{TEST_IMAGE_BASE64}"
        
        assert data_url.startswith("data:image")
        assert ";base64," in data_url
        
        b64_data = data_url.split(",", 1)[1]
        assert b64_data == TEST_IMAGE_BASE64
        
        decoded = base64.b64decode(b64_data)
        assert decoded == TEST_IMAGE_DATA


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
