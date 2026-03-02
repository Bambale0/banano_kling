"""
Tests for Seedream 5.0 Lite Service
"""

import asyncio
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
        assert seedream_service.API_URL == "https://api.novita.ai/v3/seedream-5.0-lite"

    def test_normalize_size_presets(self, seedream_service):
        """Test size normalization for preset values"""
        assert seedream_service._normalize_size("2K") == "2048x2048"
        assert seedream_service._normalize_size("2k") == "2048x2048"
        assert seedream_service._normalize_size("3K") == "3072x3072"
        assert seedream_service._normalize_size("3k") == "3072x3072"

    def test_normalize_size_custom(self, seedream_service):
        """Test size normalization for custom resolutions"""
        assert seedream_service._normalize_size("2560x1440") == "2560x1440"
        assert seedream_service._normalize_size("3840x2160") == "3840x2160"
        assert seedream_service._normalize_size("1920x2560") == "1920x2560"

    def test_normalize_size_invalid(self, seedream_service):
        """Test size normalization for invalid values"""
        # Invalid formats should default to 2048x2048
        assert seedream_service._normalize_size("invalid") == "2048x2048"
        assert seedream_service._normalize_size("") == "2048x2048"
        assert seedream_service._normalize_size("abc") == "2048x2048"

    def test_validate_prompt_english(self, seedream_service):
        """Test prompt validation for English text"""
        short_prompt = "A beautiful landscape"
        result = seedream_service.validate_prompt(short_prompt)
        assert result["is_chinese"] is False
        assert result["length"] == 21
        assert result["is_valid"] is True
        assert len(result["warnings"]) == 0

    def test_validate_prompt_chinese(self, seedream_service):
        """Test prompt validation for Chinese text"""
        chinese_prompt = "美丽的风景画"
        result = seedream_service.validate_prompt(chinese_prompt)
        assert result["is_chinese"] is True
        assert result["length"] == 6
        assert result["is_valid"] is True

    def test_validate_prompt_long_english(self, seedream_service):
        """Test prompt validation warning for long English prompt"""
        # Create a prompt with more than 600 words
        long_prompt = "word " * 650
        result = seedream_service.validate_prompt(long_prompt)
        assert result["is_valid"] is False
        assert len(result["warnings"]) > 0
        assert "600 words" in result["warnings"][0]

    @pytest.mark.asyncio
    async def test_generate_image_payload(self, seedream_service):
        """Test that generate_image builds correct payload"""
        with patch.object(
            seedream_service, "_post_request", new_callable=AsyncMock
        ) as mock_post:
            mock_post.return_value = {"images": ["https://example.com/image.png"]}

            result = await seedream_service.generate_image(
                prompt="A beautiful sunset",
                size="2048x2048",
                watermark=False,
            )

            # Verify the call was made
            assert mock_post.called

            # Get the payload passed to _post_request
            call_args = mock_post.call_args
            url = call_args[0][0]
            payload = call_args[0][1]

            # Verify URL
            assert url == "https://api.novita.ai/v3/seedream-5.0-lite"

            # Verify payload structure
            assert payload["prompt"] == "A beautiful sunset"
            assert payload["size"] == "2048x2048"
            assert payload["watermark"] is False
            assert "image" not in payload  # No images provided
            assert "optimize_prompt_options" not in payload  # Not enabled
            assert payload.get("sequential_image_generation") == "disabled"

    @pytest.mark.asyncio
    async def test_generate_image_with_images(self, seedream_service):
        """Test generate_image with reference images"""
        with patch.object(
            seedream_service, "_post_request", new_callable=AsyncMock
        ) as mock_post:
            mock_post.return_value = {"images": ["https://example.com/output.png"]}

            await seedream_service.generate_image(
                prompt="Transform this image",
                images=["https://example.com/input.png"],
                sequential_generation="disabled",
            )

            payload = mock_post.call_args[0][1]
            assert "image" in payload
            assert len(payload["image"]) == 1
            assert payload["image"][0]["url"] == "https://example.com/input.png"

    @pytest.mark.asyncio
    async def test_generate_image_with_base64(self, seedream_service):
        """Test generate_image with Base64 encoded image"""
        with patch.object(
            seedream_service, "_post_request", new_callable=AsyncMock
        ) as mock_post:
            mock_post.return_value = {"images": ["https://example.com/output.png"]}

            base64_data = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
            await seedream_service.generate_image(
                prompt="Transform this image",
                images=[base64_data],
            )

            payload = mock_post.call_args[0][1]
            assert "image" in payload
            assert payload["image"][0]["url"].startswith("data:image/jpeg;base64,")
            assert base64_data in payload["image"][0]["url"]

    @pytest.mark.asyncio
    async def test_generate_image_with_optimization(self, seedream_service):
        """Test generate_image with prompt optimization"""
        with patch.object(
            seedream_service, "_post_request", new_callable=AsyncMock
        ) as mock_post:
            mock_post.return_value = {"images": ["https://example.com/output.png"]}

            await seedream_service.generate_image(
                prompt="A beautiful landscape",
                optimize_prompt=True,
                optimize_mode="standard",
            )

            payload = mock_post.call_args[0][1]
            assert "optimize_prompt_options" in payload
            assert payload["optimize_prompt_options"]["mode"] == "standard"

    @pytest.mark.asyncio
    async def test_generate_sequential(self, seedream_service):
        """Test sequential image generation"""
        with patch.object(
            seedream_service, "_post_request", new_callable=AsyncMock
        ) as mock_post:
            mock_post.return_value = {
                "images": [
                    "https://example.com/frame1.png",
                    "https://example.com/frame2.png",
                    "https://example.com/frame3.png",
                ]
            }

            result = await seedream_service.generate_sequential(
                prompt="A story sequence",
                max_images=5,
            )

            payload = mock_post.call_args[0][1]
            assert payload["sequential_image_generation"] == "auto"
            assert payload["sequential_image_generation_options"]["max_images"] == 5

    @pytest.mark.asyncio
    async def test_text_to_image(self, seedream_service):
        """Test text-to-image convenience method"""
        with patch.object(
            seedream_service, "_post_request", new_callable=AsyncMock
        ) as mock_post:
            mock_post.return_value = {"images": ["https://example.com/output.png"]}

            await seedream_service.text_to_image(
                prompt="A beautiful sunset",
                size="3072x3072",
            )

            payload = mock_post.call_args[0][1]
            assert payload["prompt"] == "A beautiful sunset"
            assert payload["size"] == "3072x3072"
            assert "image" not in payload
            assert payload.get("sequential_image_generation") == "disabled"

    @pytest.mark.asyncio
    async def test_image_to_image(self, seedream_service):
        """Test image-to-image convenience method"""
        with patch.object(
            seedream_service, "_post_request", new_callable=AsyncMock
        ) as mock_post:
            mock_post.return_value = {"images": ["https://example.com/output.png"]}

            await seedream_service.image_to_image(
                prompt="Transform this",
                image="https://example.com/input.png",
            )

            payload = mock_post.call_args[0][1]
            assert "image" in payload
            assert len(payload["image"]) == 1

    @pytest.mark.asyncio
    async def test_multi_image_to_image(self, seedream_service):
        """Test multi-image-to-image convenience method"""
        with patch.object(
            seedream_service, "_post_request", new_callable=AsyncMock
        ) as mock_post:
            mock_post.return_value = {"images": ["https://example.com/output.png"]}

            images = [f"https://example.com/img{i}.png" for i in range(5)]
            await seedream_service.multi_image_to_image(
                prompt="Combine these images",
                images=images,
            )

            payload = mock_post.call_args[0][1]
            assert "image" in payload
            assert len(payload["image"]) == 5

    @pytest.mark.asyncio
    async def test_multi_image_truncation(self, seedream_service):
        """Test that too many images are truncated to 14"""
        with patch.object(
            seedream_service, "_post_request", new_callable=AsyncMock
        ) as mock_post:
            mock_post.return_value = {"images": ["https://example.com/output.png"]}

            # Try to send 20 images
            images = [f"https://example.com/img{i}.png" for i in range(20)]
            await seedream_service.multi_image_to_image(
                prompt="Combine these images",
                images=images,
            )

            payload = mock_post.call_args[0][1]
            assert len(payload["image"]) == 14  # Should be truncated


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
