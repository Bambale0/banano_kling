"""
Seedream 5.0 Lite Service - Интеграция с Novita AI Seedream 5.0 Lite API

Документация: https://api.novita.ai/v3/seedream-5.0-lite

Поддерживаемые функции:
- Text-to-image (T2I)
- Single image-to-image (I2I)
- Multi-image-to-image (до 14 референсных изображений)
- Sequential image generation (генерация серии изображений)

Особенности:
- Поддержка китайского и английского языков в промптах
- Оптимизация промптов (standard mode)
- Настраиваемый размер изображения (2K, 3K или произвольное разрешение)
- Водяной знак (включен по умолчанию)
- Aspect ratio range: [1/16, 16]
- Total pixel range: [3,686,400 (2560x1440), 10,404,496 (3072x3072*1.1025)]
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional

import aiohttp

logger = logging.getLogger(__name__)


class SeedreamService:
    """Сервис для работы с Novita AI Seedream 5.0 Lite API"""

    # API Endpoint
    API_URL = "https://api.novita.ai/v3/seedream-5.0-lite"

    # Valid size presets
    SIZES_2K = "2048x2048"  # 2K resolution
    SIZES_3K = "3072x3072"  # 3K resolution

    # Common resolutions within valid pixel range [3,686,400, 10,404,496]
    VALID_RESOLUTIONS = [
        # 16:9 variants
        "2560x1440",  # 3,686,400 pixels (min)
        "3072x1728",  # 5,308,416 pixels
        "3456x1944",  # 6,718,464 pixels
        "3840x2160",  # 8,294,400 pixels
        # 9:16 variants
        "1440x2560",  # 3,686,400 pixels
        "1728x3072",  # 5,308,416 pixels
        "1944x3456",  # 6,718,464 pixels
        "2160x3840",  # 8,294,400 pixels
        # 1:1 variants
        "2048x2048",  # 4,194,304 pixels (default)
        "2560x2560",  # 6,553,600 pixels
        "3072x3072",  # 9,437,184 pixels
        # 4:3 variants
        "2048x1536",  # 3,145,728 pixels (below min, will be scaled)
        "2560x1920",  # 4,915,200 pixels
        "3072x2304",  # 7,077,888 pixels
        # 3:4 variants
        "1536x2048",  # 3,145,728 pixels (below min, will be scaled)
        "1920x2560",  # 4,915,200 pixels
        "2304x3072",  # 7,077,888 pixels
        # 21:9 variants
        "2560x1097",  # 2,808,320 pixels (below min, will be scaled)
        "3072x1316",  # 4,042,752 pixels
        "3440x1474",  # 5,070,560 pixels
        "3840x1646",  # 6,320,640 pixels
    ]

    # Sequential generation modes
    SEQUENTIAL_MODES = ["auto", "disabled"]

    # Prompt optimization modes (currently only standard is supported)
    OPTIMIZE_MODES = ["standard"]

    # Constraints
    MAX_REFERENCE_IMAGES = 14
    MAX_TOTAL_IMAGES = 15  # input images + generated images ≤ 15
    MIN_PIXELS = 2560 * 1440  # 3,686,400
    MAX_PIXELS = int(3072 * 3072 * 1.1025)  # 10,404,496

    # Prompt length recommendations
    MAX_CHINESE_CHARS = 300
    MAX_ENGLISH_WORDS = 600

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    async def generate_image(
        self,
        prompt: str,
        size: str = "2048x2048",
        images: Optional[List[str]] = None,
        watermark: bool = True,
        optimize_prompt: bool = False,
        optimize_mode: str = "standard",
        sequential_generation: str = "disabled",
        max_images: int = 15,
    ) -> Optional[Dict[str, Any]]:
        """
        Generate image using Seedream 5.0 Lite API

        API: POST https://api.novita.ai/v3/seedream-5.0-lite

        Args:
            prompt: Text prompt for image generation (required).
                   Supports Chinese (max 300 chars) and English (max 600 words).
            size: Image size. Options:
                  - "2K" or "2048x2048" for 2K resolution
                  - "3K" or "3072x3072" for 3K resolution
                  - Custom "WIDTHxHEIGHT" (e.g., "2560x1440", "3840x2160")
                  Valid pixel range: 3,686,400 to 10,404,496 pixels
                  Aspect ratio range: 1/16 to 16
            images: List of input images for image-to-image generation.
                   Supports URL or Base64 encoding. Max 14 images.
                   Supported formats: jpeg, png, webp, bmp, tiff, gif
            watermark: Whether to add watermark to generated images. Default: True
            optimize_prompt: Enable prompt optimization. Default: False
            optimize_mode: Optimization mode. Currently only "standard" is supported.
            sequential_generation: Sequential generation mode:
                   - "disabled": Generate single image only (default)
                   - "auto": Model decides based on prompt
            max_images: Maximum number of images to generate (1-15).
                       Only effective when sequential_generation is "auto".
                       Note: input images + generated images ≤ 15

        Returns:
            Dict with API response containing task info, or None on error

        Response format:
            {
                "images": ["url1", "url2", ...]  # Array of generated image URLs
            }
        """
        # Build payload according to API spec
        payload: Dict[str, Any] = {
            "prompt": prompt,
            "size": self._normalize_size(size),
            "watermark": watermark,
        }

        # Add reference images for image-to-image generation
        if images:
            if len(images) > self.MAX_REFERENCE_IMAGES:
                logger.warning(
                    f"Too many images ({len(images)}), truncating to {self.MAX_REFERENCE_IMAGES}"
                )
                images = images[: self.MAX_REFERENCE_IMAGES]

            # Format images - API accepts array of objects with url field
            # or direct URL strings depending on implementation
            formatted_images = []
            for img in images:
                if isinstance(img, str):
                    if img.startswith("http://") or img.startswith("https://"):
                        formatted_images.append({"url": img})
                    else:
                        # Assume Base64 - wrap in data URI format
                        formatted_images.append(
                            {"url": f"data:image/jpeg;base64,{img}"}
                        )
                elif isinstance(img, dict) and "url" in img:
                    formatted_images.append(img)

            if formatted_images:
                payload["image"] = formatted_images

        # Add prompt optimization options
        if optimize_prompt:
            mode = optimize_mode if optimize_mode in self.OPTIMIZE_MODES else "standard"
            payload["optimize_prompt_options"] = {"mode": mode}

        # Add sequential image generation settings
        if sequential_generation in self.SEQUENTIAL_MODES:
            payload["sequential_image_generation"] = sequential_generation

            # Add sequential generation options only when mode is "auto"
            if sequential_generation == "auto":
                clamped_max = max(1, min(max_images, self.MAX_TOTAL_IMAGES))
                payload["sequential_image_generation_options"] = {
                    "max_images": clamped_max
                }

        logger.info(
            f"Seedream 5.0 Lite request: prompt='{prompt[:50]}...', "
            f"size={payload['size']}, images={len(images) if images else 0}, "
            f"watermark={watermark}, sequential={sequential_generation}"
        )

        return await self._post_request(self.API_URL, payload)

    async def text_to_image(
        self,
        prompt: str,
        size: str = "2048x2048",
        watermark: bool = True,
        optimize_prompt: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """
        Text-to-image generation (T2I)

        Args:
            prompt: Text prompt describing the desired image
            size: Output image size (default: "2048x2048")
            watermark: Add watermark to generated image (default: True)
            optimize_prompt: Enable prompt optimization (default: False)

        Returns:
            API response dict or None on error
        """
        return await self.generate_image(
            prompt=prompt,
            size=size,
            images=None,
            watermark=watermark,
            optimize_prompt=optimize_prompt,
            sequential_generation="disabled",
        )

    async def image_to_image(
        self,
        prompt: str,
        image: str,
        size: str = "2048x2048",
        watermark: bool = True,
        optimize_prompt: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """
        Single image-to-image generation (I2I)

        Args:
            prompt: Text prompt describing the desired transformation
            image: Input image URL or Base64 encoded image
            size: Output image size (default: "2048x2048")
            watermark: Add watermark to generated image (default: True)
            optimize_prompt: Enable prompt optimization (default: False)

        Returns:
            API response dict or None on error
        """
        return await self.generate_image(
            prompt=prompt,
            size=size,
            images=[image],
            watermark=watermark,
            optimize_prompt=optimize_prompt,
            sequential_generation="disabled",
        )

    async def multi_image_to_image(
        self,
        prompt: str,
        images: List[str],
        size: str = "2048x2048",
        watermark: bool = True,
        optimize_prompt: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """
        Multi-image-to-image generation (up to 14 reference images)

        Args:
            prompt: Text prompt describing the desired output
            images: List of input images (URLs or Base64), max 14
            size: Output image size (default: "2048x2048")
            watermark: Add watermark to generated image (default: True)
            optimize_prompt: Enable prompt optimization (default: False)

        Returns:
            API response dict or None on error
        """
        if len(images) > self.MAX_REFERENCE_IMAGES:
            logger.warning(
                f"Too many images ({len(images)}), truncating to {self.MAX_REFERENCE_IMAGES}"
            )
            images = images[: self.MAX_REFERENCE_IMAGES]

        return await self.generate_image(
            prompt=prompt,
            size=size,
            images=images,
            watermark=watermark,
            optimize_prompt=optimize_prompt,
            sequential_generation="disabled",
        )

    async def generate_sequential(
        self,
        prompt: str,
        size: str = "2048x2048",
        images: Optional[List[str]] = None,
        watermark: bool = True,
        optimize_prompt: bool = False,
        max_images: int = 15,
    ) -> Optional[Dict[str, Any]]:
        """
        Sequential image generation - generates multiple images based on prompt

        The model automatically determines whether to return sequential images
        based on the prompt content when mode is set to "auto".

        Args:
            prompt: Text prompt describing the desired sequence/story
            size: Output image size (default: "2048x2048")
            images: Optional reference images (URLs or Base64), max 14
            watermark: Add watermark to generated images (default: True)
            optimize_prompt: Enable prompt optimization (default: False)
            max_images: Maximum images to generate (1-15, default: 15)
                     Note: input images count + max_images ≤ 15

        Returns:
            API response dict with multiple image URLs or None on error
        """
        input_count = len(images) if images else 0
        available_slots = self.MAX_TOTAL_IMAGES - input_count
        actual_max = min(max_images, available_slots)

        if actual_max < 1:
            logger.error(
                f"Cannot generate sequential images: input count ({input_count}) "
                f"exceeds maximum allowed ({self.MAX_TOTAL_IMAGES})"
            )
            return None

        return await self.generate_image(
            prompt=prompt,
            size=size,
            images=images,
            watermark=watermark,
            optimize_prompt=optimize_prompt,
            sequential_generation="auto",
            max_images=actual_max,
        )

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def _normalize_size(self, size: str) -> str:
        """
        Normalize size string to valid resolution format

        Args:
            size: Size string like "2K", "3K", "2048x2048", "2560x1440"

        Returns:
            Normalized size string in "WIDTHxHEIGHT" format
        """
        size_lower = size.lower().strip()

        # Handle preset sizes
        if size_lower in ["2k", "2k resolution"]:
            return self.SIZES_2K
        elif size_lower in ["3k", "3k resolution"]:
            return self.SIZES_3K

        # Try to parse as "WIDTHxHEIGHT" format
        if "x" in size_lower:
            try:
                parts = size_lower.split("x")
                width = int(parts[0].strip())
                height = int(parts[1].strip())

                # Validate pixel count
                pixels = width * height
                if pixels < self.MIN_PIXELS:
                    logger.warning(
                        f"Resolution {width}x{height} ({pixels} pixels) is below minimum "
                        f"({self.MIN_PIXELS} pixels). API may reject or auto-adjust."
                    )
                elif pixels > self.MAX_PIXELS:
                    logger.warning(
                        f"Resolution {width}x{height} ({pixels} pixels) exceeds maximum "
                        f"({self.MAX_PIXELS} pixels). API may reject or auto-adjust."
                    )

                return f"{width}x{height}"
            except (ValueError, IndexError):
                logger.warning(
                    f"Invalid size format: {size}, using default {self.SIZES_2K}"
                )
                return self.SIZES_2K

        logger.warning(f"Unknown size format: {size}, using default {self.SIZES_2K}")
        return self.SIZES_2K

    def validate_prompt(self, prompt: str) -> Dict[str, Any]:
        """
        Validate prompt length and provide warnings

        Args:
            prompt: The prompt string to validate

        Returns:
            Dict with validation results
        """
        # Simple heuristic: if more than 30% non-ASCII, treat as Chinese
        non_ascii_count = sum(1 for c in prompt if ord(c) > 127)
        is_chinese = (non_ascii_count / len(prompt)) > 0.3 if prompt else False

        warnings = []

        if is_chinese:
            char_count = len(prompt)
            if char_count > self.MAX_CHINESE_CHARS:
                warnings.append(
                    f"Chinese prompt exceeds {self.MAX_CHINESE_CHARS} characters "
                    f"({char_count} chars). Quality may be reduced."
                )
        else:
            word_count = len(prompt.split())
            if word_count > self.MAX_ENGLISH_WORDS:
                warnings.append(
                    f"English prompt exceeds {self.MAX_ENGLISH_WORDS} words "
                    f"({word_count} words). Quality may be reduced."
                )

        return {
            "is_chinese": is_chinese,
            "length": len(prompt),
            "warnings": warnings,
            "is_valid": len(warnings) == 0,
        }

    # =========================================================================
    # Private HTTP Methods
    # =========================================================================

    async def _post_request(
        self,
        url: str,
        payload: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """
        Execute POST request to Seedream 5.0 Lite API

        Args:
            url: API endpoint URL
            payload: Request payload dict

        Returns:
            API response dict or None on error
        """
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(
                    url,
                    json=payload,
                    headers=self.headers,
                    timeout=aiohttp.ClientTimeout(total=60),
                ) as response:
                    data = await response.json()

                    if response.status in [200, 201]:
                        logger.info(
                            f"Seedream API request successful: status={response.status}, "
                            f"images_count={len(data.get('images', []))}"
                        )
                        return data
                    else:
                        logger.error(f"Seedream API error {response.status}: {data}")
                        return None

            except asyncio.TimeoutError:
                logger.error(f"Seedream API request timeout: {url}")
                return None
            except aiohttp.ClientError as e:
                logger.error(f"Seedream API request failed: {e}")
                return None
            except Exception as e:
                logger.exception(f"Unexpected error in Seedream API request: {e}")
                return None


# =============================================================================
# Module initialization
# =============================================================================

from bot.config import config

# Initialize service with API key from config
seedream_service: Optional[SeedreamService] = None
if config.NOVITA_API_KEY:
    seedream_service = SeedreamService(api_key=config.NOVITA_API_KEY)
    logger.info("Seedream 5.0 Lite service initialized")
else:
    logger.warning("NOVITA_API_KEY not set, Seedream service not available")
