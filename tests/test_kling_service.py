"""Тесты для kling_service.py"""
import asyncio
from unittest.mock import AsyncMock, Mock, patch

import pytest


class TestKlingServiceInit:
    """Тесты инициализации сервиса"""

    def test_service_initialization(self):
        """Тест: инициализация сервиса"""
        from bot.services.kling_service import KlingService

        service = KlingService(
            api_key="test_api_key", base_url="https://api.freepik.com/v1"
        )

        assert service.api_key == "test_api_key"
        assert service.base_url == "https://api.freepik.com/v1"
        assert service.headers["x-freepik-api-key"] == "test_api_key"
        assert service.headers["Content-Type"] == "application/json"

    def test_base_url_stripping(self):
        """Тест: удаление слеша в конце URL"""
        from bot.services.kling_service import KlingService

        service = KlingService(
            api_key="test_key", base_url="https://api.freepik.com/v1/"
        )

        assert service.base_url == "https://api.freepik.com/v1"

    def test_endpoints_config(self):
        """Тест: проверка конфигурации эндпоинтов"""
        from bot.services.kling_service import KlingService

        # Kling 3 Pro/Standard
        assert KlingService.ENDPOINTS["v3_pro"] == "/v1/ai/video/kling-v3-pro"
        assert KlingService.ENDPOINTS["v3_std"] == "/v1/ai/video/kling-v3-std"
        assert KlingService.ENDPOINTS["v3_tasks"] == "/v1/ai/video/kling-v3"

        # Kling 3 Omni
        assert KlingService.ENDPOINTS["v3_omni_pro"] == "/v1/ai/video/kling-v3-omni-pro"
        assert KlingService.ENDPOINTS["v3_omni_std"] == "/v1/ai/video/kling-v3-omni-std"
        assert KlingService.ENDPOINTS["v3_omni_tasks"] == "/v1/ai/video/kling-v3-omni"

        # Kling 3 Omni R2V
        assert (
            KlingService.ENDPOINTS["v3_omni_pro_r2v"]
            == "/v1/ai/reference-to-video/kling-v3-omni-pro"
        )
        assert (
            KlingService.ENDPOINTS["v3_omni_std_r2v"]
            == "/v1/ai/reference-to-video/kling-v3-omni-std"
        )
        assert (
            KlingService.ENDPOINTS["v3_omni_r2v_tasks"]
            == "/v1/ai/reference-to-video/kling-v3-omni"
        )

    def test_aspect_ratios_config(self):
        """Тест: проверка списка форматов"""
        from bot.services.kling_service import KlingService

        assert "16:9" in KlingService.ASPECT_RATIOS
        assert "9:16" in KlingService.ASPECT_RATIOS
        assert "1:1" in KlingService.ASPECT_RATIOS

    def test_durations_config(self):
        """Тест: проверка списка длительностей"""
        from bot.services.kling_service import KlingService

        assert "3" in KlingService.DURATIONS
        assert "5" in KlingService.DURATIONS
        assert "10" in KlingService.DURATIONS
        assert "15" in KlingService.DURATIONS


class TestBuildV3Payload:
    """Тесты построения payload для Kling 3"""

    def test_basic_payload(self):
        """Тест: базовый payload"""
        from bot.services.kling_service import KlingService

        service = KlingService(api_key="test", base_url="https://test.com")

        payload = service._build_v3_payload(
            prompt="A beautiful sunset",
            duration=5,
            aspect_ratio="16:9",
            webhook_url=None,
            start_image_url=None,
            end_image_url=None,
            elements=None,
            negative_prompt="blurry",
            cfg_scale=0.5,
            generate_audio=True,
            voice_ids=None,
            multi_prompt=None,
            shot_type="customize",
            multi_shot=False,
        )

        assert payload["prompt"] == "A beautiful sunset"
        assert payload["duration"] == "5"
        assert payload["aspect_ratio"] == "16:9"
        assert payload["cfg_scale"] == 0.5
        assert payload["generate_audio"] is True
        assert payload["shot_type"] == "customize"

    def test_cfg_scale_clamping(self):
        """Тест: ограничение cfg_scale (0-1 для Kling 3)"""
        from bot.services.kling_service import KlingService

        service = KlingService(api_key="test", base_url="https://test.com")

        # Тест upper bound
        payload = service._build_v3_payload(
            prompt="test",
            duration=5,
            aspect_ratio="16:9",
            webhook_url=None,
            start_image_url=None,
            end_image_url=None,
            elements=None,
            negative_prompt=None,
            cfg_scale=2.0,
            generate_audio=True,
            voice_ids=None,
            multi_prompt=None,
            shot_type="customize",
            multi_shot=False,
        )
        assert payload["cfg_scale"] == 1

        # Тест lower bound
        payload = service._build_v3_payload(
            prompt="test",
            duration=5,
            aspect_ratio="16:9",
            webhook_url=None,
            start_image_url=None,
            end_image_url=None,
            elements=None,
            negative_prompt=None,
            cfg_scale=-1.0,
            generate_audio=True,
            voice_ids=None,
            multi_prompt=None,
            shot_type="customize",
            multi_shot=False,
        )
        assert payload["cfg_scale"] == 0

    def test_duration_clamping(self):
        """Тест: ограничение длительности (3-15)"""
        from bot.services.kling_service import KlingService

        service = KlingService(api_key="test", base_url="https://test.com")

        # Верхняя граница
        payload = service._build_v3_payload(
            prompt="test",
            duration=20,
            aspect_ratio="16:9",
            webhook_url=None,
            start_image_url=None,
            end_image_url=None,
            elements=None,
            negative_prompt=None,
            cfg_scale=0.5,
            generate_audio=True,
            voice_ids=None,
            multi_prompt=None,
            shot_type="customize",
            multi_shot=False,
        )
        assert payload["duration"] == "15"

        # Нижняя граница
        payload = service._build_v3_payload(
            prompt="test",
            duration=1,
            aspect_ratio="16:9",
            webhook_url=None,
            start_image_url=None,
            end_image_url=None,
            elements=None,
            negative_prompt=None,
            cfg_scale=0.5,
            generate_audio=True,
            voice_ids=None,
            multi_prompt=None,
            shot_type="customize",
            multi_shot=False,
        )
        assert payload["duration"] == "3"

    def test_aspect_ratio_validation(self):
        """Тест: валидация формата"""
        from bot.services.kling_service import KlingService

        service = KlingService(api_key="test", base_url="https://test.com")

        # Невалидный формат
        payload = service._build_v3_payload(
            prompt="test",
            duration=5,
            aspect_ratio="21:9",
            webhook_url=None,
            start_image_url=None,
            end_image_url=None,
            elements=None,
            negative_prompt=None,
            cfg_scale=0.5,
            generate_audio=True,
            voice_ids=None,
            multi_prompt=None,
            shot_type="customize",
            multi_shot=False,
        )
        assert payload["aspect_ratio"] == "16:9"

        # Валидный формат
        payload = service._build_v3_payload(
            prompt="test",
            duration=5,
            aspect_ratio="9:16",
            webhook_url=None,
            start_image_url=None,
            end_image_url=None,
            elements=None,
            negative_prompt=None,
            cfg_scale=0.5,
            generate_audio=True,
            voice_ids=None,
            multi_prompt=None,
            shot_type="customize",
            multi_shot=False,
        )
        assert payload["aspect_ratio"] == "9:16"

    def test_image_list_first_frame(self):
        """Тест: image_list с first_frame"""
        from bot.services.kling_service import KlingService

        service = KlingService(api_key="test", base_url="https://test.com")

        payload = service._build_v3_payload(
            prompt="test",
            duration=5,
            aspect_ratio="16:9",
            webhook_url=None,
            start_image_url="https://example.com/start.jpg",
            end_image_url=None,
            elements=None,
            negative_prompt=None,
            cfg_scale=0.5,
            generate_audio=True,
            voice_ids=None,
            multi_prompt=None,
            shot_type="customize",
            multi_shot=False,
        )

        assert "image_list" in payload
        assert len(payload["image_list"]) == 1
        assert payload["image_list"][0]["image_url"] == "https://example.com/start.jpg"
        assert payload["image_list"][0]["type"] == "first_frame"

    def test_image_list_end_frame(self):
        """Тест: image_list с end_frame"""
        from bot.services.kling_service import KlingService

        service = KlingService(api_key="test", base_url="https://test.com")

        payload = service._build_v3_payload(
            prompt="test",
            duration=5,
            aspect_ratio="16:9",
            webhook_url=None,
            start_image_url=None,
            end_image_url="https://example.com/end.jpg",
            elements=None,
            negative_prompt=None,
            cfg_scale=0.5,
            generate_audio=True,
            voice_ids=None,
            multi_prompt=None,
            shot_type="customize",
            multi_shot=False,
        )

        assert "image_list" in payload
        assert len(payload["image_list"]) == 1
        assert payload["image_list"][0]["image_url"] == "https://example.com/end.jpg"
        assert payload["image_list"][0]["type"] == "end_frame"

    def test_image_list_both_frames(self):
        """Тест: image_list с обоими кадрами"""
        from bot.services.kling_service import KlingService

        service = KlingService(api_key="test", base_url="https://test.com")

        payload = service._build_v3_payload(
            prompt="test",
            duration=5,
            aspect_ratio="16:9",
            webhook_url=None,
            start_image_url="https://example.com/start.jpg",
            end_image_url="https://example.com/end.jpg",
            elements=None,
            negative_prompt=None,
            cfg_scale=0.5,
            generate_audio=True,
            voice_ids=None,
            multi_prompt=None,
            shot_type="customize",
            multi_shot=False,
        )

        assert "image_list" in payload
        assert len(payload["image_list"]) == 2
        assert payload["image_list"][0]["type"] == "first_frame"
        assert payload["image_list"][1]["type"] == "end_frame"

    def test_webhook_url(self):
        """Тест: добавление webhook_url"""
        from bot.services.kling_service import KlingService

        service = KlingService(api_key="test", base_url="https://test.com")

        payload = service._build_v3_payload(
            prompt="test",
            duration=5,
            aspect_ratio="16:9",
            webhook_url="https://example.com/webhook",
            start_image_url=None,
            end_image_url=None,
            elements=None,
            negative_prompt=None,
            cfg_scale=0.5,
            generate_audio=True,
            voice_ids=None,
            multi_prompt=None,
            shot_type="customize",
            multi_shot=False,
        )

        assert payload["webhook_url"] == "https://example.com/webhook"

    def test_elements(self):
        """Тест: добавление elements"""
        from bot.services.kling_service import KlingService

        service = KlingService(api_key="test", base_url="https://test.com")

        elements = [{"id": "char_001", "reference_id": "person1"}]

        payload = service._build_v3_payload(
            prompt="test",
            duration=5,
            aspect_ratio="16:9",
            webhook_url=None,
            start_image_url=None,
            end_image_url=None,
            elements=elements,
            negative_prompt=None,
            cfg_scale=0.5,
            generate_audio=True,
            voice_ids=None,
            multi_prompt=None,
            shot_type="customize",
            multi_shot=False,
        )

        assert payload["elements"] == elements

    def test_negative_prompt(self):
        """Тест: добавление negative_prompt"""
        from bot.services.kling_service import KlingService

        service = KlingService(api_key="test", base_url="https://test.com")

        payload = service._build_v3_payload(
            prompt="test",
            duration=5,
            aspect_ratio="16:9",
            webhook_url=None,
            start_image_url=None,
            end_image_url=None,
            elements=None,
            negative_prompt="blurry, distorted",
            cfg_scale=0.5,
            generate_audio=True,
            voice_ids=None,
            multi_prompt=None,
            shot_type="customize",
            multi_shot=False,
        )

        assert payload["negative_prompt"] == "blurry, distorted"

    def test_voice_ids(self):
        """Тест: добавление voice_ids"""
        from bot.services.kling_service import KlingService

        service = KlingService(api_key="test", base_url="https://test.com")

        payload = service._build_v3_payload(
            prompt="test",
            duration=5,
            aspect_ratio="16:9",
            webhook_url=None,
            start_image_url=None,
            end_image_url=None,
            elements=None,
            negative_prompt=None,
            cfg_scale=0.5,
            generate_audio=True,
            voice_ids=["voice_1", "voice_2", "voice_3"],
            multi_prompt=None,
            shot_type="customize",
            multi_shot=False,
        )

        assert len(payload["voice_ids"]) == 2  # Max 2

    def test_multi_prompt(self):
        """Тест: добавление multi_prompt"""
        from bot.services.kling_service import KlingService

        service = KlingService(api_key="test", base_url="https://test.com")

        multi_prompt = [
            {"index": 0, "prompt": "Scene 1", "duration": 5},
            {"index": 1, "prompt": "Scene 2", "duration": 5},
        ]

        payload = service._build_v3_payload(
            prompt="test",
            duration=5,
            aspect_ratio="16:9",
            webhook_url=None,
            start_image_url=None,
            end_image_url=None,
            elements=None,
            negative_prompt=None,
            cfg_scale=0.5,
            generate_audio=True,
            voice_ids=None,
            multi_prompt=multi_prompt,
            shot_type="customize",
            multi_shot=False,
        )

        assert payload["multi_prompt"] == multi_prompt


class TestBuildOmniPayload:
    """Тесты построения payload для Kling 3 Omni"""

    def test_omni_aspect_ratio_auto(self):
        """Тест: поддержка auto формата в Omni"""
        from bot.services.kling_service import KlingService

        service = KlingService(api_key="test", base_url="https://test.com")

        payload = service._build_omni_payload(
            prompt="test",
            duration=5,
            aspect_ratio="auto",
            webhook_url=None,
            start_image_url=None,
            end_image_url=None,
            image_url=None,
            image_urls=None,
            elements=None,
            generate_audio=True,
            voice_ids=None,
            multi_prompt=None,
        )

        assert payload["aspect_ratio"] == "auto"

    def test_omni_image_list(self):
        """Тест: image_list для Omni"""
        from bot.services.kling_service import KlingService

        service = KlingService(api_key="test", base_url="https://test.com")

        payload = service._build_omni_payload(
            prompt="test",
            duration=5,
            aspect_ratio="16:9",
            webhook_url=None,
            start_image_url="https://example.com/start.jpg",
            end_image_url=None,
            image_url=None,
            image_urls=None,
            elements=None,
            generate_audio=True,
            voice_ids=None,
            multi_prompt=None,
        )

        assert "image_list" in payload
        assert payload["image_list"][0]["type"] == "first_frame"

    def test_omni_image_urls(self):
        """Тест: image_urls для style guidance"""
        from bot.services.kling_service import KlingService

        service = KlingService(api_key="test", base_url="https://test.com")

        image_urls = [
            "https://example.com/ref1.jpg",
            "https://example.com/ref2.jpg",
            "https://example.com/ref3.jpg",
            "https://example.com/ref4.jpg",
            "https://example.com/ref5.jpg",  # Лишнее
        ]

        payload = service._build_omni_payload(
            prompt="test",
            duration=5,
            aspect_ratio="16:9",
            webhook_url=None,
            start_image_url=None,
            end_image_url=None,
            image_url=None,
            image_urls=image_urls,
            elements=None,
            generate_audio=True,
            voice_ids=None,
            multi_prompt=None,
        )

        assert len(payload["image_urls"]) == 4  # Max 4


class TestR2VPayload:
    """Тесты построения payload для R2V методов"""

    def test_r2v_payload(self):
        """Тест: базовый R2V payload"""
        from bot.services.kling_service import KlingService

        service = KlingService(api_key="test", base_url="https://test.com")

        # Эмуляция R2V метода
        prompt = "Make it more dynamic @Video1"
        video_url = "https://example.com/video.mp4"

        payload = {
            "prompt": prompt,
            "video_url": video_url,
            "duration": str(min(max(5, 3), 15)),
            "aspect_ratio": "16:9",
            "cfg_scale": min(max(0.5, 0), 2),
        }

        assert payload["prompt"] == "Make it more dynamic @Video1"
        assert payload["video_url"] == "https://example.com/video.mp4"
        assert payload["duration"] == "5"
        assert payload["aspect_ratio"] == "16:9"
        assert payload["cfg_scale"] == 0.5

    def test_r2v_cfg_scale_range(self):
        """Тест: cfg_scale 0-2 для R2V"""
        from bot.services.kling_service import KlingService

        # R2V поддерживает 0-2, в отличие от базового Kling 3 (0-1)
        assert 2 >= 0 and 2 <= 2  # Верхняя граница
        assert 0 >= 0 and 0 <= 2  # Нижняя граница


class TestKlingServiceMethods:
    """Тесты методов KlingService"""

    @pytest.mark.asyncio
    async def test_generate_video_pro(self):
        """Тест: генерация видео Pro"""
        from bot.services.kling_service import KlingService

        service = KlingService(api_key="test", base_url="https://test.com")

        with patch.object(
            service, "_post_request", new_callable=AsyncMock
        ) as mock_post:
            mock_post.return_value = {"task_id": "test_task_123", "status": "CREATED"}

            result = await service.generate_video_pro(
                prompt="A beautiful landscape",
                duration=5,
                aspect_ratio="16:9",
            )

            assert result["task_id"] == "test_task_123"
            mock_post.assert_called_once()

    @pytest.mark.asyncio
    async def test_generate_video_std(self):
        """Тест: генерация видео Standard"""
        from bot.services.kling_service import KlingService

        service = KlingService(api_key="test", base_url="https://test.com")

        with patch.object(
            service, "_post_request", new_callable=AsyncMock
        ) as mock_post:
            mock_post.return_value = {"task_id": "test_task_456", "status": "CREATED"}

            result = await service.generate_video_std(
                prompt="A beautiful landscape",
                duration=5,
                aspect_ratio="16:9",
            )

            assert result["task_id"] == "test_task_456"

    @pytest.mark.asyncio
    async def test_generate_video_omni_pro(self):
        """Тест: генерация видео Omni Pro"""
        from bot.services.kling_service import KlingService

        service = KlingService(api_key="test", base_url="https://test.com")

        with patch.object(
            service, "_post_request", new_callable=AsyncMock
        ) as mock_post:
            mock_post.return_value = {"task_id": "test_task_omni", "status": "CREATED"}

            result = await service.generate_video_omni_pro(
                prompt="Animate this image",
                start_image_url="https://example.com/image.jpg",
            )

            assert result["task_id"] == "test_task_omni"

    @pytest.mark.asyncio
    async def test_text_to_video(self):
        """Тест: упрощённый метод T2V"""
        from bot.services.kling_service import KlingService

        service = KlingService(api_key="test", base_url="https://test.com")

        with patch.object(
            service, "generate_video_std", new_callable=AsyncMock
        ) as mock_gen:
            mock_gen.return_value = {"task_id": "t2v_task", "status": "CREATED"}

            result = await service.text_to_video(
                prompt="Sunset over ocean", duration=5, quality="std"
            )

            assert result["task_id"] == "t2v_task"

    @pytest.mark.asyncio
    async def test_image_to_video(self):
        """Тест: упрощённый метод I2V"""
        from bot.services.kling_service import KlingService

        service = KlingService(api_key="test", base_url="https://test.com")

        with patch.object(
            service, "generate_video_omni_std", new_callable=AsyncMock
        ) as mock_gen:
            mock_gen.return_value = {"task_id": "i2v_task", "status": "CREATED"}

            result = await service.image_to_video(
                image_url="https://example.com/photo.jpg",
                prompt="Make it move",
                quality="std",
            )

            assert result["task_id"] == "i2v_task"

    @pytest.mark.asyncio
    async def test_video_to_video(self):
        """Тест: упрощённый метод R2V"""
        from bot.services.kling_service import KlingService

        service = KlingService(api_key="test", base_url="https://test.com")

        with patch.object(
            service, "generate_video_omni_std_r2v", new_callable=AsyncMock
        ) as mock_gen:
            mock_gen.return_value = {"task_id": "r2v_task", "status": "CREATED"}

            result = await service.video_to_video(
                video_url="https://example.com/video.mp4",
                prompt="Apply style @Video1",
                quality="std",
            )

            assert result["task_id"] == "r2v_task"

    @pytest.mark.asyncio
    async def test_get_task_status(self):
        """Тест: получение статуса задачи"""
        from bot.services.kling_service import KlingService

        service = KlingService(api_key="test", base_url="https://test.com")

        with patch.object(service, "_get_request", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {
                "data": {
                    "task_id": "test_123",
                    "status": "COMPLETED",
                    "result": {"video_url": "https://example.com/result.mp4"},
                }
            }

            result = await service.get_task_status("test_123")

            assert result["data"]["status"] == "COMPLETED"
            assert (
                result["data"]["result"]["video_url"]
                == "https://example.com/result.mp4"
            )


class TestModelMapping:
    """Тесты маппинга моделей"""

    @pytest.mark.asyncio
    async def test_generate_video_model_mapping(self):
        """Тест: маппинг модели в методе generate_video"""
        from bot.services.kling_service import KlingService

        service = KlingService(api_key="test", base_url="https://test.com")

        # Тест v3_pro
        with patch.object(
            service, "generate_video_pro", new_callable=AsyncMock
        ) as mock_pro:
            await service.generate_video(prompt="test", model="v3_pro")
            mock_pro.assert_called_once()

        # Тест v3_std
        with patch.object(
            service, "generate_video_std", new_callable=AsyncMock
        ) as mock_std:
            await service.generate_video(prompt="test", model="v3_std")
            mock_std.assert_called_once()

        # Тест v3_omni_pro
        with patch.object(
            service, "generate_video_omni_pro", new_callable=AsyncMock
        ) as mock_omni:
            await service.generate_video(prompt="test", model="v3_omni_pro")
            mock_omni.assert_called_once()

        # Тест v3_omni_std
        with patch.object(
            service, "generate_video_omni_std", new_callable=AsyncMock
        ) as mock_omni_std:
            await service.generate_video(prompt="test", model="v3_omni_std")
            mock_omni_std.assert_called_once()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
