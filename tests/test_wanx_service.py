"""Tests for bot.services.wanx_service."""

import asyncio
from unittest.mock import AsyncMock, patch


class TestWanXService:
    def setup_method(self):
        from bot.services.wanx_service import WanXService

        self.service = WanXService(api_key="test_key", base_url="https://test.piapi.ai")

    def test_init(self):
        assert self.service.api_key == "test_key"
        assert self.service.base_url == "https://test.piapi.ai"
        assert self.service.headers["x-api-key"] == "test_key"

    def test_create_task(self):
        async def run():
            with patch.object(
                self.service, "_post", new_callable=AsyncMock
            ) as mock_post:
                mock_post.return_value = {"task_id": "wanx_task_1", "status": "pending"}
                result = await self.service.create_task(
                    "txt2video-14b-lora",
                    {"prompt": "hello", "lora_settings": []},
                )
                assert result["task_id"] == "wanx_task_1"

        asyncio.run(run())

    def test_generate_txt2video_lora(self):
        async def run():
            with patch.object(
                self.service, "create_task", new_callable=AsyncMock
            ) as mock_create:
                mock_create.return_value = {
                    "task_id": "wanx_task_2",
                    "status": "pending",
                }
                result = await self.service.generate_txt2video_lora(
                    prompt="A cinematic scene",
                    lora_settings=[{"lora_type": "ghibli", "lora_strength": 1.5}],
                )
                assert result["task_id"] == "wanx_task_2"
                payload = mock_create.call_args.args[1]
                assert payload["prompt"] == "A cinematic scene"
                assert payload["lora_settings"][0]["lora_type"] == "ghibli"
                assert payload["lora_settings"][0]["lora_strength"] == 1.0

        asyncio.run(run())

    def test_invalid_aspect_ratio_defaults(self):
        async def run():
            with patch.object(
                self.service, "create_task", new_callable=AsyncMock
            ) as mock_create:
                mock_create.return_value = {
                    "task_id": "wanx_task_3",
                    "status": "pending",
                }
                await self.service.generate_txt2video_lora(
                    prompt="test", aspect_ratio="bad"
                )
                payload = mock_create.call_args.args[1]
                assert payload["aspect_ratio"] == "16:9"

        asyncio.run(run())

    def test_generate_txt2video_lora_custom_task_type(self):
        async def run():
            with patch.object(
                self.service, "create_task", new_callable=AsyncMock
            ) as mock_create:
                mock_create.return_value = {
                    "task_id": "wanx_task_6",
                    "status": "pending",
                }
                await self.service.generate_txt2video_lora(
                    prompt="test",
                    task_type="img2video-14b-lora",
                    lora_settings=[{"lora_type": "nsfw-general", "lora_strength": 0.8}],
                )
                assert mock_create.call_args.args[0] == "img2video-14b-lora"
                payload = mock_create.call_args.args[1]
                assert payload["lora_settings"][0]["lora_type"] == "nsfw-general"

        asyncio.run(run())

    def test_get_task_status_normalizes_piapi_response(self):
        async def run():
            raw = {
                "data": {
                    "task_id": "wanx_task_4",
                    "status": "completed",
                    "output": {"video_url": "https://example.com/video.mp4"},
                }
            }
            with patch.object(self.service, "_get", new_callable=AsyncMock) as mock_get:
                mock_get.return_value = raw
                result = await self.service.get_task_status("wanx_task_4")
                assert result["task_id"] == "wanx_task_4"
                assert result["status"] == "completed"
                assert result["output"]["video_url"] == "https://example.com/video.mp4"

        asyncio.run(run())

    def test_wait_for_completion_returns_finished_task(self):
        async def run():
            finished = {
                "task_id": "wanx_task_5",
                "status": "completed",
                "output": {"video_url": "https://example.com/result.mp4"},
            }
            with patch.object(
                self.service, "get_task_status", new_callable=AsyncMock
            ) as mock_status:
                mock_status.return_value = finished
                result = await self.service.wait_for_completion(
                    "wanx_task_5", max_attempts=1, delay=0
                )
                assert result["task_id"] == "wanx_task_5"
                assert result["output"]["video_url"] == "https://example.com/result.mp4"

        asyncio.run(run())
