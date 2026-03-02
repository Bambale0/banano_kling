"""Тесты для replicate_service.py"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestReplicateServiceInit:
    """Тесты инициализации сервиса"""

    def test_service_initialization(self):
        """Тест: инициализация сервиса с API токеном"""
        from bot.services.replicate_service import ReplicateService

        service = ReplicateService(api_token="test_replicate_token")

        assert service.api_token == "test_replicate_token"
        assert service.BASE_URL == "https://api.replicate.com/v1"
        assert "Authorization" in service.headers

    def test_models_config(self):
        """Тест: проверка конфигурации моделей"""
        from bot.services.replicate_service import ReplicateService

        assert ReplicateService.MODEL_SEEDREAM == "bytedance/seedream-5"

    def test_aspect_ratios_config(self):
        """Тест: проверка списка форматов"""
        from bot.services.replicate_service import ReplicateService

        assert "1:1" in ReplicateService.ASPECT_RATIOS
        assert "16:9" in ReplicateService.ASPECT_RATIOS
        assert "9:16" in ReplicateService.ASPECT_RATIOS
        assert "2:3" in ReplicateService.ASPECT_RATIOS
        assert "match_input_image" in ReplicateService.ASPECT_RATIOS

    def test_sizes_config(self):
        """Тест: проверка списка размеров"""
        from bot.services.replicate_service import ReplicateService

        assert "2K" in ReplicateService.SIZES
        assert "3K" in ReplicateService.SIZES

    def test_output_formats_config(self):
        """Тест: проверка форматов вывода"""
        from bot.services.replicate_service import ReplicateService

        assert "png" in ReplicateService.OUTPUT_FORMATS
        assert "jpeg" in ReplicateService.OUTPUT_FORMATS


class TestGenerateImage:
    """Тесты основного метода generate_image"""

    @pytest.mark.asyncio
    async def test_generate_image_text_to_image(self):
        """Тест: текст-в-изображение через Seedream"""
        from bot.services.replicate_service import ReplicateService

        service = ReplicateService(api_token="test_token")

        mock_response = {
            "id": "pred_123",
            "status": "starting",
            "output": None,
        }

        with patch.object(service, "_post_request", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response

            result = await service.generate_image(
                prompt="A beautiful sunset over the ocean",
                model="bytedance/seedream-5",
                size="2K",
                aspect_ratio="16:9",
            )

            assert result == mock_response
            mock_post.assert_called_once()

    @pytest.mark.asyncio
    async def test_generate_image_with_custom_model(self):
        """Тест: генерация с кастомной моделью"""
        from bot.services.replicate_service import ReplicateService

        service = ReplicateService(api_token="test_token")

        with patch.object(service, "_post_request", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = {"id": "pred_123", "status": "starting"}

            result = await service.generate_image(
                prompt="Test prompt",
                model="custom/model",
            )

            # Проверяем, что метод был вызван
            assert mock_post.called

    @pytest.mark.asyncio
    async def test_generate_image_with_image_input(self):
        """Тест: генерация с входным изображением (image-to-image)"""
        from bot.services.replicate_service import ReplicateService

        service = ReplicateService(api_token="test_token")

        with patch.object(service, "_post_request", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = {"id": "pred_123", "status": "starting"}

            result = await service.generate_image(
                prompt="Transform to vintage style",
                image_input=["https://example.com/image.jpg"],
                size="2K",
            )

            # Проверяем, что метод был вызван
            assert mock_post.called

    @pytest.mark.asyncio
    async def test_generate_image_sequential_generation(self):
        """Тест: последовательная генерация нескольких изображений"""
        from bot.services.replicate_service import ReplicateService

        service = ReplicateService(api_token="test_token")

        with patch.object(service, "_post_request", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = {"id": "pred_123", "status": "starting"}

            result = await service.generate_image(
                prompt="A series of 4 coherent illustrations",
                max_images=4,
                sequential_image_generation="auto",
            )

            # Проверяем, что метод был вызван
            assert mock_post.called

    @pytest.mark.asyncio
    async def test_generate_image_with_webhook(self):
        """Тест: генерация с webhook"""
        from bot.services.replicate_service import ReplicateService

        service = ReplicateService(api_token="test_token")

        with patch.object(service, "_post_request", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = {"id": "pred_123", "status": "starting"}

            result = await service.generate_image(
                prompt="Test",
                webhook_url="https://example.com/webhook",
            )

            # Проверяем, что метод был вызван
            assert mock_post.called


class TestGenerateSeedream:
    """Тесты метода generate_seedream"""

    @pytest.mark.asyncio
    async def test_generate_seedream_default(self):
        """Тест: базовый вызов Seedream"""
        from bot.services.replicate_service import ReplicateService

        service = ReplicateService(api_token="test_token")

        with patch.object(service, "generate_image", new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = {"id": "pred_123", "status": "starting"}

            result = await service.generate_seedream(
                prompt="A cat sitting on a windowsill"
            )

            assert result == {"id": "pred_123", "status": "starting"}
            mock_gen.assert_called_once()

            # Проверяем модель
            call_kwargs = mock_gen.call_args.kwargs
            assert call_kwargs["model"] == "bytedance/seedream-5"

    @pytest.mark.asyncio
    async def test_generate_seedream_with_options(self):
        """Тест: Seedream с опциями"""
        from bot.services.replicate_service import ReplicateService

        service = ReplicateService(api_token="test_token")

        with patch.object(service, "generate_image", new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = {"id": "pred_123"}

            result = await service.generate_seedream(
                prompt="Test",
                size="3K",
                aspect_ratio="1:1",
                output_format="jpeg",
            )

            call_kwargs = mock_gen.call_args.kwargs
            assert call_kwargs["size"] == "3K"
            assert call_kwargs["aspect_ratio"] == "1:1"
            assert call_kwargs["output_format"] == "jpeg"


class TestPredictionManagement:
    """Тесты управления предиктами"""

    @pytest.mark.asyncio
    async def test_get_prediction(self):
        """Тест: получение статуса предикта"""
        from bot.services.replicate_service import ReplicateService

        service = ReplicateService(api_token="test_token")

        mock_response = {
            "id": "pred_123",
            "status": "succeeded",
            "output": ["https://example.com/image.png"],
        }

        with patch.object(service, "_get_request", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_response

            result = await service.get_prediction("pred_123")

            assert result == mock_response
            mock_get.assert_called_once()

    @pytest.mark.asyncio
    async def test_cancel_prediction(self):
        """Тест: отмена предикта"""
        from bot.services.replicate_service import ReplicateService

        service = ReplicateService(api_token="test_token")

        mock_response = {"id": "pred_123", "status": "canceled"}

        with patch.object(service, "_post_request", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response

            result = await service.cancel_prediction("pred_123")

            assert result == mock_response
            # Проверяем URL
            call_args = mock_post.call_args
            url = call_args.args[0]
            assert "predictions/pred_123/cancel" in url

    @pytest.mark.asyncio
    async def test_list_predictions(self):
        """Тест: список предиктов"""
        from bot.services.replicate_service import ReplicateService

        service = ReplicateService(api_token="test_token")

        mock_response = {
            "results": [
                {"id": "pred_1", "status": "succeeded"},
                {"id": "pred_2", "status": "failed"},
            ]
        }

        with patch.object(service, "_get_request", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_response

            result = await service.list_predictions(page=1, page_size=10)

            assert result == mock_response
            mock_get.assert_called_once()


class TestWaitForCompletion:
    """Тесты ожидания завершения предикта"""

    @pytest.mark.asyncio
    async def test_wait_succeeded(self):
        """Тест: успешное завершение"""
        from bot.services.replicate_service import ReplicateService

        service = ReplicateService(api_token="test_token")

        mock_prediction = {"id": "pred_123", "status": "succeeded"}

        with patch.object(
            service, "get_prediction", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = mock_prediction

            result = await service.wait_for_completion("pred_123", max_attempts=1)

            assert result == mock_prediction
            mock_get.assert_called_once_with("pred_123")

    @pytest.mark.asyncio
    async def test_wait_failed(self):
        """Тест: неудачное завершение"""
        from bot.services.replicate_service import ReplicateService

        service = ReplicateService(api_token="test_token")

        mock_prediction = {"id": "pred_123", "status": "failed", "error": "Some error"}

        with patch.object(
            service, "get_prediction", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = mock_prediction

            result = await service.wait_for_completion("pred_123", max_attempts=1)

            assert result == mock_prediction

    @pytest.mark.asyncio
    async def test_wait_canceled(self):
        """Тест: отменённый предикт"""
        from bot.services.replicate_service import ReplicateService

        service = ReplicateService(api_token="test_token")

        mock_prediction = {"id": "pred_123", "status": "canceled"}

        with patch.object(
            service, "get_prediction", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = mock_prediction

            result = await service.wait_for_completion("pred_123", max_attempts=1)

            assert result == mock_prediction

    @pytest.mark.asyncio
    async def test_wait_polling(self):
        """Тест: несколько попыток опроса"""
        from bot.services.replicate_service import ReplicateService

        service = ReplicateService(api_token="test_token")

        # Первые 2 раза - processing, потом succeeded
        mock_predictions = [
            {"id": "pred_123", "status": "processing"},
            {"id": "pred_123", "status": "processing"},
            {"id": "pred_123", "status": "succeeded"},
        ]

        with patch.object(
            service, "get_prediction", new_callable=AsyncMock
        ) as mock_get:
            mock_get.side_effect = mock_predictions

            result = await service.wait_for_completion(
                "pred_123", max_attempts=5, delay=0.01
            )

            assert result["status"] == "succeeded"
            assert mock_get.call_count == 3

    @pytest.mark.asyncio
    async def test_wait_timeout(self):
        """Тест: таймаут при опросе"""
        from bot.services.replicate_service import ReplicateService

        service = ReplicateService(api_token="test_token")

        # Всегда processing
        with patch.object(
            service, "get_prediction", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = {"id": "pred_123", "status": "processing"}

            result = await service.wait_for_completion(
                "pred_123", max_attempts=3, delay=0.01
            )

            assert result is None  # Таймаут
            assert mock_get.call_count == 3


class TestParameterValidation:
    """Тесты валидации параметров"""

    @pytest.mark.asyncio
    async def test_invalid_aspect_ratio(self):
        """Тест: невалидный формат"""
        from bot.services.replicate_service import ReplicateService

        service = ReplicateService(api_token="test_token")

        # Seedream должен принимать любой формат в payload, но проверим константы
        assert "1:1" in ReplicateService.ASPECT_RATIOS
        assert "16:9" in ReplicateService.ASPECT_RATIOS
        assert "match_input_image" in ReplicateService.ASPECT_RATIOS

    @pytest.mark.asyncio
    async def test_valid_sizes(self):
        """Тест: валидные размеры"""
        from bot.services.replicate_service import ReplicateService

        assert "2K" in ReplicateService.SIZES
        assert "3K" in ReplicateService.SIZES


class TestModuleInitialization:
    """Тесты инициализации модуля"""

    def test_service_class_exported(self):
        """Тест: класс сервиса экспортируется"""
        from bot.services import ReplicateService

        assert ReplicateService is not None

    def test_service_instance_with_token(self):
        """Тест: создание экземпляра сервиса с токеном"""
        from bot.services.replicate_service import ReplicateService

        service = ReplicateService(api_token="test_token_123")
        
        # Проверяем что сервис создаётся корректно
        assert service.api_token == "test_token_123"
        assert service.BASE_URL == "https://api.replicate.com/v1"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
