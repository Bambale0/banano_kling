"""Tests for kling_service.py - Kei Kling 3.0 + legacy PiAPI"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.services.kie_service import kie_service


class TestKlingService:
    def setup_method(self):
        from bot.services.kling_service import KlingService

        self.service = KlingService(
            api_key="test_key", base_url="https://test.piapi.ai"
        )

    def test_init(self):
        assert self.service.api_key == "test_key"
        assert self.service.base_url == "https://test.piapi.ai"

    def test_elements_to_kling_elements(self):
        elements = [
            {
                "reference_image_urls": ["url1.jpg", "url2.jpg"],
                "frontal_image_url": "url3.jpg",
                "description": "main character",
            },
            {"reference_image_urls": ["url4.jpg"]},
        ]
        kling_els = self.service._elements_to_kling_elements(elements)
        assert len(kling_els) == 1
        assert kling_els[0]["name"] == "element_0"
        assert kling_els[0]["description"] == "main character"
        assert len(kling_els[0]["element_input_urls"]) == 3

    @pytest.mark.asyncio
    async def test_generate_video_generation_kie(self):
        with patch.object(
            kie_service, "generate_kling_3_0", new_callable=AsyncMock
        ) as mock_kie:
            mock_kie.return_value = {"task_id": "kie_task"}
            result = await self.service.generate_video_generation(
                prompt="test", mode="std", kling_elements=[{"name": "test_el"}]
            )
            assert result["task_id"] == "kie_task"
            mock_kie.assert_called_once()

    @pytest.mark.asyncio
    async def test_generate_video_kling3(self):
        kling_els = [{"name": "el0", "element_input_urls": ["url1"]}]
        with patch.object(
            self.service, "generate_video_generation", new_callable=AsyncMock
        ) as mock_gen:
            mock_gen.return_value = {"task_id": "kling3_task"}
            result = await self.service.generate_video(
                prompt="test", model="v3_pro", kling_elements=kling_els
            )
            assert result["task_id"] == "kling3_task"

    @pytest.mark.asyncio
    async def test_generate_video_motion(self):
        with patch.object(
            self.service, "generate_motion_control", new_callable=AsyncMock
        ) as mock_motion:
            mock_motion.return_value = {"task_id": "motion_task"}
            result = await self.service.generate_video(
                prompt="test", model="motion", image_url="img", video_url="vid"
            )
            assert result["task_id"] == "motion_task"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
