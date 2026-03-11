"""
Tests for Seedream 4.5 Service (Novita AI)
"""

import asyncio
import base64
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bot.services.seedream_service import SeedreamService


@pytest.fixture
def seedream_service():
    """Create a SeedreamService instance for testing"""
    return SeedreamService(api_key="test-api-key")


class TestSeedreamService:
    """Test cases for SeedreamService"""

    def test_initialization(self, seedream_service):
        """Test service initialization"""
        assert seedream_service.api_key == "test-api-key"
        assert seedream_service.headers["Authorization"] == "Bearer test-api-key"
        assert seedream_service.headers["Content-Type"] == "application/json"
        assert seedream_service.API_URL == "https://api.novita.ai/v3/seedream-4.5"

    @pytest.mark.asyncio
    async def test_generate_image_text_to_image(self, seedream_service):
        """Test text-to-image generation"""
        mock_response = {
            "images": [
                "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg=="
            ]
        }

        with patch("aiohttp.ClientSession.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value.__aenter__.return_value.status = 200
            mock_post.return_value.__aenter__.return_value.json.return_value = (
                mock_response
            )

            result = await seedream_service.text_to_image(prompt="A beautiful sunset")

            assert result is not None
            assert isinstance(result[0], bytes)
            assert len(result) == 1

    @pytest.mark.asyncio
    async def test_generate_image_image_to_image(self, seedream_service):
        """Test single image-to-image generation"""
        mock_response = {
            "images": [
                "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg=="
            ]
        }

        with patch("aiohttp.ClientSession.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value.__aenter__.return_value.status = 200
            mock_post.return_value.__aenter__.return_value.json.return_value = (
                mock_response
            )

            result = await seedream_service.image_to_image(
                prompt="Transform this image", image="https://example.com/input.png"
            )

            assert result is not None
            assert len(result) == 1

    @pytest.mark.asyncio
    async def test_generate_image_multi_image(self, seedream_service):
        """Test multi-image-to-image generation"""
        mock_response = {
            "images": [
                "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg==",
                "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg==",
            ]
        }

        with patch("aiohttp.ClientSession.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value.__aenter__.return_value.status = 200
            mock_post.return_value.__aenter__.return_value.json.return_value = (
                mock_response
            )

            images = ["https://example.com/img1.png", "https://example.com/img2.png"]
            result = await seedream_service.multi_image_to_image(
                prompt="Combine these images", images=images
            )

            assert result is not None
            assert len(result) == 2

    @pytest.mark.asyncio
    async def test_generate_image_sequential(self, seedream_service):
        """Test sequential image generation"""
        mock_response = {
            "images": [
                "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg=="
            ]
            * 3
        }

        with patch("aiohttp.ClientSession.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value.__aenter__.return_value.status = 200
            mock_post.return_value.__aenter__.return_value.json.return_value = (
                mock_response
            )

            result = await seedream_service.sequential_image_generation(
                prompt="Sequential story",
                sequential_image_generation_options={"max_images": 3},
            )

            assert result is not None
            assert len(result) == 3

    @pytest.mark.asyncio
    async def test_generate_image_truncation(self, seedream_service):
        """Test image truncation to 14 max"""
        mock_response = {
            "images": [
                "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg=="
            ]
        }

        with patch("aiohttp.ClientSession.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value.__aenter__.return_value.status = 200
            mock_post.return_value.__aenter__.return_value.json.return_value = (
                mock_response
            )

            # 15 images should be truncated to 14
            images = ["https://example.com/img" + str(i) + ".png" for i in range(15)]
            result = await seedream_service.generate_image(
                prompt="Test truncation", images=images
            )

            # Verify the POST was called with 14 images
            payload = mock_post.call_args[0][1]
            assert len(payload["image"]) == 14

    @pytest.mark.asyncio
    async def test_generate_image_url_response(self, seedream_service):
        """Test handling of URL responses (should log warning but continue)"""
        mock_response = {"images": ["https://example.com/generated.png"]}

        with patch("aiohttp.ClientSession.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value.__aenter__.return_value.status = 200
            mock_post.return_value.__aenter__.return_value.json.return_value = (
                mock_response
            )

            with patch("logging.Logger.warning") as mock_warning:
                result = await seedream_service.generate_image(
                    prompt="Test URL response"
                )

                assert result is None  # No bytes extracted
                mock_warning.assert_called_once_with(
                    "Image URL not downloaded: https://example.com/generated.png"
                )

    @pytest.mark.asyncio
    async def test_generate_image_error(self, seedream_service):
        """Test error handling"""
        mock_response = {"error": {"message": "API error"}}

        with patch("aiohttp.ClientSession.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value.__aenter__.return_value.status = 500
            mock_post.return_value.__aenter__.return_value.text.return_value = (
                '{"error": "Server error"}'
            )

            result = await seedream_service.generate_image(prompt="Test error")

            assert result is None

    @pytest.mark.asyncio
    async def test_optimize_prompt_default(self, seedream_service):
        """Test default optimize_prompt_options"""
        mock_response = {
            "images": [
                "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg=="
            ]
        }

        with patch("aiohttp.ClientSession.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value.__aenter__.return_value.status = 200
            mock_post.return_value.__aenter__.return_value.json.return_value = (
                mock_response
            )

            result = await seedream_service.generate_image(
                prompt="Test default optimize"
            )

            payload = mock_post.call_args[0][1]
            assert payload["optimize_prompt_options"]["mode"] == "standard"

    @pytest.mark.asyncio
    async def test_sequential_max_images_validation(self, seedream_service):
        """Test validation of max_images with input images"""
        mock_response = {"images": []}

        with patch("aiohttp.ClientSession.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value.__aenter__.return_value.status = 200
            mock_post.return_value.__aenter__.return_value.json.return_value = (
                mock_response
            )

            # 10 input images + max 5 generated = 15 total
            images = ["https://example.com/img" + str(i) + ".png" for i in range(10)]
            result = await seedream_service.generate_image(
                prompt="Test validation",
                images=images,
                sequential_image_generation_options={
                    "max_images": 10
                },  # Should be clamped to 5
            )

            payload = mock_post.call_args[0][1]
            assert payload["sequential_image_generation_options"]["max_images"] == 5


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
