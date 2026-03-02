"""Тесты для novita_service.py"""
import asyncio
from unittest.mock import AsyncMock, Mock, patch

import pytest


class TestNovitaServiceInit:
    """Тесты инициализации сервиса"""

    def test_service_initialization(self):
        """Тест: инициализация сервиса"""
        from bot.services.novita_service import NovitaService

        service = NovitaService(api_key="test_api_key")

        assert service.api_key == "test_api_key"
        assert service.BASE_URL == "https://api.novita.ai"
        assert service.headers["Authorization"] == "Bearer test_api_key"
        assert service.headers["Content-Type"] == "application/json"

    def test_valid_parameters(self):
        """Тест: проверка валидных параметров"""
        from bot.services.novita_service import NovitaService

        assert NovitaService.MIN_SIZE == 256
        assert NovitaService.MAX_SIZE == 1536
        assert NovitaService.MAX_IMAGES == 3

    def test_size_presets(self):
        """Тест: проверка пресетов размеров"""
        from bot.services.novita_service import NovitaService

        assert "1:1" in NovitaService.SIZE_PRESETS
        assert "16:9" in NovitaService.SIZE_PRESETS
        assert "9:16" in NovitaService.SIZE_PRESETS
        assert "4:3" in NovitaService.SIZE_PRESETS
        assert "3:4" in NovitaService.SIZE_PRESETS
        assert "21:9" in NovitaService.SIZE_PRESETS

        # Проверяем значения
        assert NovitaService.SIZE_PRESETS["1:1"] == (1024, 1024)
        assert NovitaService.SIZE_PRESETS["16:9"] == (1280, 720)
        assert NovitaService.SIZE_PRESETS["9:16"] == (720, 1280)


class TestParseSize:
    """Тесты парсинга размера"""

    def test_parse_preset_1_1(self):
        """Тест: парсинг пресета 1:1"""
        from bot.services.novita_service import NovitaService

        service = NovitaService(api_key="test")

        width, height = service._parse_size("1:1")

        assert width == 1024
        assert height == 1024

    def test_parse_preset_16_9(self):
        """Тест: парсинг пресета 16:9"""
        from bot.services.novita_service import NovitaService

        service = NovitaService(api_key="test")

        width, height = service._parse_size("16:9")

        assert width == 1280
        assert height == 720

    def test_parse_preset_9_16(self):
        """Тест: парсинг пресета 9:16"""
        from bot.services.novita_service import NovitaService

        service = NovitaService(api_key="test")

        width, height = service._parse_size("9:16")

        assert width == 720
        assert height == 1280

    def test_parse_width_height_format(self):
        """Тест: парсинг формата WIDTHxHEIGHT"""
        from bot.services.novita_service import NovitaService

        service = NovitaService(api_key="test")

        width, height = service._parse_size("800x600")

        assert width == 800
        assert height == 600

    def test_parse_width_height_uppercase(self):
        """Тест: парсинг формата WIDTHxHEIGHT (верхний регистр)"""
        from bot.services.novita_service import NovitaService

        service = NovitaService(api_key="test")

        width, height = service._parse_size("1024X1024")

        assert width == 1024
        assert height == 1024

    def test_size_clamping_min(self):
        """Тест: ограничение минимального размера"""
        from bot.services.novita_service import NovitaService

        service = NovitaService(api_key="test")

        width, height = service._parse_size("100x100")

        assert width == 256  # MIN_SIZE
        assert height == 256  # MIN_SIZE

    def test_size_clamping_max(self):
        """Тест: ограничение максимального размера"""
        from bot.services.novita_service import NovitaService

        service = NovitaService(api_key="test")

        width, height = service._parse_size("2000x2000")

        assert width == 1536  # MAX_SIZE
        assert height == 1536  # MAX_SIZE

    def test_invalid_format(self):
        """Тест: невалидный формат"""
        from bot.services.novita_service import NovitaService

        service = NovitaService(api_key="test")

        width, height = service._parse_size("invalid")

        # Должен вернуть значение по умолчанию
        assert width == 1024
        assert height == 1024


class TestGenerateImage:
    """Тесты генерации изображений"""

    @pytest.mark.asyncio
    async def test_generate_image_basic(self):
        """Тест: базовая генерация изображения"""
        from bot.services.novita_service import NovitaService

        service = NovitaService(api_key="test")

        with patch.object(service, "_post_request", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = {"task_id": "novita_task_123", "status": "CREATED"}

            result = await service.generate_image(prompt="A beautiful sunset")

            assert result["task_id"] == "novita_task_123"
            mock_post.assert_called_once()

            # Проверяем, что payload содержит правильные данные (по умолчанию HQ - 1536px)
            call_args = mock_post.call_args
            payload = call_args[0][1]

            assert payload["prompt"] == "A beautiful sunset"
            assert payload["width"] == 1536  # Default is now 1:1_hq
            assert payload["height"] == 1536
            assert payload["seed"] == -1
            assert payload["response_format"] == "url"

    @pytest.mark.asyncio
    async def test_generate_image_with_size(self):
        """Тест: генерация с указанием размера"""
        from bot.services.novita_service import NovitaService

        service = NovitaService(api_key="test")

        with patch.object(service, "_post_request", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = {"task_id": "task_456", "status": "CREATED"}

            result = await service.generate_image(
                prompt="A cat",
                size="16:9"
            )

            call_args = mock_post.call_args
            payload = call_args[0][1]

            assert payload["width"] == 1280
            assert payload["height"] == 720

    @pytest.mark.asyncio
    async def test_generate_image_with_seed(self):
        """Тест: генерация с указанием seed"""
        from bot.services.novita_service import NovitaService

        service = NovitaService(api_key="test")

        with patch.object(service, "_post_request", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = {"task_id": "task_789", "status": "CREATED"}

            result = await service.generate_image(
                prompt="A dog",
                seed=12345
            )

            call_args = mock_post.call_args
            payload = call_args[0][1]

            assert payload["seed"] == 12345

    @pytest.mark.asyncio
    async def test_generate_image_with_webhook(self):
        """Тест: генерация с webhook"""
        from bot.services.novita_service import NovitaService

        service = NovitaService(api_key="test")

        with patch.object(service, "_post_request", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = {"task_id": "task_webhook", "status": "CREATED"}

            result = await service.generate_image(
                prompt="A landscape",
                webhook_url="https://example.com/webhook"
            )

            call_args = mock_post.call_args
            payload = call_args[0][1]

            assert payload["webhook_url"] == "https://example.com/webhook"

    @pytest.mark.asyncio
    async def test_generate_image_custom_dimensions(self):
        """Тест: генерация с кастомными размерами"""
        from bot.services.novita_service import NovitaService

        service = NovitaService(api_key="test")

        with patch.object(service, "_post_request", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = {"task_id": "task_custom", "status": "CREATED"}

            result = await service.generate_image(
                prompt="Test",
                size="800x600"
            )

            call_args = mock_post.call_args
            payload = call_args[0][1]

            assert payload["width"] == 800
            assert payload["height"] == 600


class TestEditImage:
    """Тесты редактирования изображений"""

    @pytest.mark.asyncio
    async def test_edit_image_basic(self):
        """Тест: базовое редактирование изображения"""
        from bot.services.novita_service import NovitaService

        service = NovitaService(api_key="test")

        with patch.object(service, "_post_request", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = {"task_id": "edit_task_123", "status": "CREATED"}

            result = await service.edit_image(
                prompt="Make it more colorful",
                images=["https://example.com/image1.jpg"]
            )

            assert result["task_id"] == "edit_task_123"

            call_args = mock_post.call_args
            payload = call_args[0][1]

            assert payload["prompt"] == "Make it more colorful"
            assert payload["images"] == ["https://example.com/image1.jpg"]

    @pytest.mark.asyncio
    async def test_edit_image_multiple_images(self):
        """Тест: редактирование с несколькими изображениями"""
        from bot.services.novita_service import NovitaService

        service = NovitaService(api_key="test")

        with patch.object(service, "_post_request", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = {"task_id": "edit_task_456", "status": "CREATED"}

            images = [
                "https://example.com/image1.jpg",
                "https://example.com/image2.jpg",
                "https://example.com/image3.jpg"
            ]

            result = await service.edit_image(
                prompt="Apply style",
                images=images
            )

            call_args = mock_post.call_args
            payload = call_args[0][1]

            assert len(payload["images"]) == 3

    @pytest.mark.asyncio
    async def test_edit_image_too_many_images(self):
        """Тест: ошибка при слишком many изображениях"""
        from bot.services.novita_service import NovitaService

        service = NovitaService(api_key="test")

        images = [
            "https://example.com/image1.jpg",
            "https://example.com/image2.jpg",
            "https://example.com/image3.jpg",
            "https://example.com/image4.jpg",  # Слишком много
        ]

        result = await service.edit_image(
            prompt="Test",
            images=images
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_edit_image_with_size(self):
        """Тест: редактирование с указанием размера"""
        from bot.services.novita_service import NovitaService

        service = NovitaService(api_key="test")

        with patch.object(service, "_post_request", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = {"task_id": "edit_task_size", "status": "CREATED"}

            result = await service.edit_image(
                prompt="Edit",
                images=["https://example.com/image.jpg"],
                size="9:16"
            )

            call_args = mock_post.call_args
            payload = call_args[0][1]

            assert payload["width"] == 720
            assert payload["height"] == 1280


class TestGetTaskResult:
    """Тесты получения результата задачи"""

    @pytest.mark.asyncio
    async def test_get_task_result_completed(self):
        """Тест: получение результата завершённой задачи"""
        from bot.services.novita_service import NovitaService

        service = NovitaService(api_key="test")

        with patch.object(service, "_get_request", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {
                "task_id": "task_123",
                "status": "COMPLETED",
                "data": {
                    "images": ["https://example.com/result.jpg"]
                }
            }

            result = await service.get_task_result("task_123")

            assert result["status"] == "COMPLETED"

    @pytest.mark.asyncio
    async def test_get_task_result_pending(self):
        """Тест: получение результата задачи в ожидании"""
        from bot.services.novita_service import NovitaService

        service = NovitaService(api_key="test")

        with patch.object(service, "_get_request", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {
                "task_id": "task_456",
                "status": "PROCESSING"
            }

            result = await service.get_task_result("task_456")

            assert result["status"] == "PROCESSING"


class TestWaitForCompletion:
    """Тесты ожидания завершения задачи"""

    @pytest.mark.asyncio
    async def test_wait_completed(self):
        """Тест: ожидание завершения задачи"""
        from bot.services.novita_service import NovitaService

        service = NovitaService(api_key="test")

        with patch.object(service, "get_task_result", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {
                "task_id": "task_123",
                "status": "COMPLETED"
            }

            result = await service.wait_for_completion("task_123", max_attempts=5, delay=1)

            assert result["status"] == "COMPLETED"
            assert mock_get.call_count == 1

    @pytest.mark.asyncio
    async def test_wait_multiple_attempts(self):
        """Тест: ожидание с несколькими попытками"""
        from bot.services.novita_service import NovitaService

        service = NovitaService(api_key="test")

        call_count = 0

        async def mock_get_task(task_id):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                return {"task_id": task_id, "status": "PROCESSING"}
            return {"task_id": task_id, "status": "COMPLETED"}

        with patch.object(service, "get_task_result", side_effect=mock_get_task):
            result = await service.wait_for_completion("task_123", max_attempts=5, delay=1)

            assert result["status"] == "COMPLETED"
            assert call_count == 3

    @pytest.mark.asyncio
    async def test_wait_failed(self):
        """Тест: задача завершилась с ошибкой"""
        from bot.services.novita_service import NovitaService

        service = NovitaService(api_key="test")

        with patch.object(service, "get_task_result", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {
                "task_id": "task_123",
                "status": "FAILED",
                "error": "Generation failed"
            }

            result = await service.wait_for_completion("task_123", max_attempts=5, delay=1)

            assert result["status"] == "FAILED"

    @pytest.mark.asyncio
    async def test_wait_timeout(self):
        """Тест: таймаут при ожидании"""
        from bot.services.novita_service import NovitaService

        service = NovitaService(api_key="test")

        with patch.object(service, "get_task_result", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {"task_id": "task_123", "status": "PROCESSING"}

            result = await service.wait_for_completion("task_123", max_attempts=3, delay=0.1)

            assert result is None
            assert mock_get.call_count == 3


class TestPostRequest:
    """Тесты HTTP POST запросов (проверяем что метод существует)"""

    def test_post_request_method_exists(self):
        """Тест: метод _post_request существует"""
        from bot.services.novita_service import NovitaService

        service = NovitaService(api_key="test")

        assert hasattr(service, "_post_request")
        assert callable(service._post_request)

    def test_headers_include_auth(self):
        """Тест: заголовки содержат авторизацию"""
        from bot.services.novita_service import NovitaService

        service = NovitaService(api_key="my_secret_key")

        assert "Authorization" in service.headers
        assert service.headers["Authorization"] == "Bearer my_secret_key"


class TestGetRequest:
    """Тесты HTTP GET запросов (проверяем что метод существует)"""

    def test_get_request_method_exists(self):
        """Тест: метод _get_request существует"""
        from bot.services.novita_service import NovitaService

        service = NovitaService(api_key="test")

        assert hasattr(service, "_get_request")
        assert callable(service._get_request)


class TestNovitaServiceIntegration:
    """Интеграционные тесты сервиса"""

    def test_service_import(self):
        """Тест: импорт сервиса"""
        from bot.services.novita_service import NovitaService, novita_service

        assert NovitaService is not None
        assert novita_service is None  # Не инициализирован без API ключа

    def test_service_in_config(self):
        """Тест: наличие в __init__"""
        from bot.services import novita_service, NovitaService

        assert "novita_service" in dir()
        assert NovitaService is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
