"""Tests for kling_service.py - PiAPI Kling 3.0"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest


class TestKlingService:
    def setup_method(self):
        from bot.services.kling_service import KlingService

        self.service = KlingService(
            api_key="test_key", base_url="https://test.piapi.ai"
        )

    def test_init(self):
        assert self.service.api_key == "test_key"
        assert self.service.base_url == "https://test.piapi.ai"
        assert self.service.headers["x-api-key"] == "test_key"

    @pytest.mark.asyncio
    async def test_create_task(self):
        with patch.object(self.service, "_post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = {"task_id": "test_task", "status": "pending"}
            result = await self.service.create_task(
                "video_generation", {"prompt": "test"}
            )
            assert result["task_id"] == "test_task"

    @pytest.mark.asyncio
    async def test_get_task_status(self):
        with patch.object(self.service, "_get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {
                "data": {"status": "completed", "output": {"video": "url.mp4"}}
            }
            result = await self.service.get_task_status("test_task")
            assert result["data"]["status"] == "completed"

    @pytest.mark.asyncio
    async def test_generate_video_generation(self):
        with patch.object(
            self.service, "create_task", new_callable=AsyncMock
        ) as mock_create:
            mock_create.return_value = {"task_id": "vg_task"}
            result = await self.service.generate_video_generation(
                "test prompt", mode="std"
            )
            assert result["task_id"] == "vg_task"
            mock_create.assert_called_once()

    @pytest.mark.asyncio
    async def test_generate_motion_control(self):
        with patch.object(
            self.service, "create_task", new_callable=AsyncMock
        ) as mock_create:
            mock_create.return_value = {"task_id": "mc_task"}
            result = await self.service.generate_motion_control(
                "image_url", preset_motion="Heart Gesture Dance"
            )
            assert result["task_id"] == "mc_task"

    @pytest.mark.asyncio
    async def test_generate_omni_video_generation(self):
        with patch.object(
            self.service, "create_task", new_callable=AsyncMock
        ) as mock_create:
            mock_create.return_value = {"task_id": "omni_task"}
            result = await self.service.generate_omni_video_generation("test prompt")
            assert result["task_id"] == "omni_task"

    @pytest.mark.asyncio
    async def test_generate_video_dispatcher(self):
        with patch.object(
            self.service, "generate_video_generation", new_callable=AsyncMock
        ) as mock_vg:
            mock_vg.return_value = {"task_id": "dispatched"}
            result = await self.service.generate_video("prompt", model="v3_std")
            assert result["task_id"] == "dispatched"

        with patch.object(
            self.service, "generate_motion_control", new_callable=AsyncMock
        ) as mock_mc:
            mock_mc.return_value = {"task_id": "motion"}
            result = await self.service.generate_video(
                "prompt", model="motion_pro", image_url="img", video_url="vid"
            )
            assert result["task_id"] == "motion"

    @pytest.mark.asyncio
    async def test_wait_for_completion(self):
        with patch.object(
            self.service, "get_task_status", new_callable=AsyncMock
        ) as mock_status:
            mock_status.side_effect = [
                {"data": {"status": "pending"}},
                {"data": {"status": "Completed"}},
            ]
            result = await self.service.wait_for_completion("test_task", max_attempts=2)
            assert result["data"]["status"] == "Completed"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
