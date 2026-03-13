"""
Seedream 4.5 Service - Integration with Novita AI Seedream 4.5 API

Documentation: Based on provided spec for POST /v3/seedream-4.5

Supported features:
- Text-to-image (T2I)
- Single image-to-image (I2I)
- Multi-image-to-image (up to 14 reference images)
- Sequential image generation (up to 15 total images)

Features:
- Supports URL or Base64 encoded input images (jpeg, png, webp, bmp, tiff, gif)
- Prompt optimization (standard mode)
- Watermark option
- Size specification: 2K, 4K or WIDTHxHEIGHT (pixel range: 3686400-16777216, aspect 1/16-16)
- Returns list of base64 decoded image bytes

"""

import asyncio
import base64
import logging
from typing import Dict, List, Optional

import aiohttp

from bot.config import config

logger = logging.getLogger(__name__)


class SeedreamService:
    """Service for Novita AI Seedream 4.5 image generation"""

    API_URL = "https://api.novita.ai/v3/seedream-4.5"

    # Default configurations
    DEFAULT_SIZE = "2048x2048"
    DEFAULT_WATERMARK = True
    DEFAULT_OPTIMIZE_MODE = "standard"
    DEFAULT_SEQUENTIAL_MODE = "disabled"
    DEFAULT_MAX_IMAGES = 15

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    async def generate_image(
        self,
        prompt: str,
        size: str = DEFAULT_SIZE,
        images: Optional[List[str]] = None,  # List of URLs or Base64 strings
        watermark: bool = DEFAULT_WATERMARK,
        optimize_prompt_options: Optional[Dict[str, str]] = None,
        sequential_image_generation: str = DEFAULT_SEQUENTIAL_MODE,
        sequential_image_generation_options: Optional[Dict[str, int]] = None,
    ) -> Optional[List[bytes]]:
        """
        Generate images using Seedream 4.5 API

        Args:
            prompt: Text prompt (Chinese/English, <=300 chars/600 words)
            size: Image size ("2048x2048", "2K", "4K") or pixel dimensions
            images: Optional list of input images (URLs or Base64, 1-14)
            watermark: Add watermark to generated images
            optimize_prompt_options: {"mode": "standard"}
            sequential_image_generation: "auto" or "disabled"
            sequential_image_generation_options: {"max_images": int} (1-15, when auto)

        Returns:
            List of image bytes or None on error
        """
        if not prompt:
            logger.error("Prompt is required")
            return None

        # Enhance prompt
        enhanced_prompt = prompt

        # Enhance with face preservation if references
        if images:
            ref_count = len(images)
            enhanced_prompt += f"\n\n{self.FACE_PRESERVATION_PROMPT}\n{self.CHARACTER_CONSISTENCY_PROMPT}\nUse the {ref_count} reference images to maintain character consistency and preserve all facial features with high fidelity."

        # Always add detail boost and no restrictions
        enhanced_prompt += (
            f"\n\n{self.DETAIL_ENHANCER_PROMPT}\n\n{self.NO_RESTRICTIONS_PROMPT}"
        )

        # Validate images
        if images:
            if len(images) > 14:
                logger.warning(f"Truncating images to 14: {len(images)} -> 14")
                images = images[:14]
            # Assume strings are URLs or Base64; no further validation here

        # Default optimize options
        if optimize_prompt_options is None:
            optimize_prompt_options = {"mode": self.DEFAULT_OPTIMIZE_MODE}

        # Default sequential options if auto
        if (
            sequential_image_generation == "auto"
            and sequential_image_generation_options is None
        ):
            total_images = len(images or []) + self.DEFAULT_MAX_IMAGES
            max_gen = min(self.DEFAULT_MAX_IMAGES, 15 - len(images or []))
            sequential_image_generation_options = {"max_images": max_gen}

        # Validate sequential max_images
        if sequential_image_generation_options:
            max_img = sequential_image_generation_options.get(
                "max_images", self.DEFAULT_MAX_IMAGES
            )
            max_img = min(max_img, 15 - len(images or []))
            sequential_image_generation_options["max_images"] = max_img

        # Build payload
        payload = {
            "prompt": enhanced_prompt,
            "size": size,
            "watermark": watermark,
            "optimize_prompt_options": optimize_prompt_options,
            "sequential_image_generation": sequential_image_generation,
        }

        if images:
            payload["image"] = images

        if (
            sequential_image_generation == "auto"
            and sequential_image_generation_options
        ):
            payload[
                "sequential_image_generation_options"
            ] = sequential_image_generation_options

        logger.info(
            f"Seedream 4.5 request: prompt='{prompt[:50]}...', "
            f"size={size}, images={len(images or [])}, "
            f"watermark={watermark}, sequential={sequential_image_generation}, "
            f"max_images={sequential_image_generation_options.get('max_images') if sequential_image_generation_options else 'N/A'}"
        )

        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=120)
        ) as session:
            try:
                async with session.post(
                    self.API_URL, json=payload, headers=self.headers
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        images_result = await self._process_images_response(data)
                        logger.info(
                            f"Generated result: {len(images_result or [])} items ({type(images_result[0]) if images_result else None})"
                        )
                        return images_result
                    else:
                        error_text = await response.text()
                        logger.error(
                            f"Seedream API error {response.status}: {error_text}"
                        )
                        return None
            except Exception as e:
                logger.error(f"Exception in Seedream request: {e}")
                return None

    async def _process_images_response(self, data: Dict) -> Optional[List]:
        """Process API response: extract base64 or download images; return bytes list or URLs list if download failed"""
        try:
            images = data.get("images", [])
            if not images:
                logger.warning("No images found in response")
                return None

            successful_images = []
            failed_urls = []
            timeout = aiohttp.ClientTimeout(total=60)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                for img_str in images:
                    if isinstance(img_str, str):
                        if img_str.startswith("data:image"):
                            # Data URL: decode base64
                            try:
                                b64_data = img_str.split(",", 1)[1]
                                img_bytes = base64.b64decode(b64_data)
                                successful_images.append(img_bytes)
                                logger.debug("Decoded base64 image")
                            except Exception as e:
                                logger.error(f"Failed to decode base64 image: {e}")
                                failed_urls.append(img_str)
                        else:
                            # URL: try download
                            try:
                                logger.info(
                                    f"Downloading image from URL: {img_str[:100]}..."
                                )
                                async with session.get(img_str) as resp:
                                    resp.raise_for_status()
                                    img_bytes = await resp.read()
                                    successful_images.append(img_bytes)
                                    logger.info(
                                        f"Downloaded image ({len(img_bytes)} bytes)"
                                    )
                            except Exception as e:
                                logger.warning(
                                    f"Failed to download image URL {img_str[:100]}...: {e}"
                                )
                                failed_urls.append(img_str)
                    else:
                        logger.warning(f"Unexpected image format: {type(img_str)}")
                        continue

            if successful_images:
                logger.info(f"Successfully processed {len(successful_images)} images")
                return successful_images
            elif failed_urls:
                logger.warning(
                    f"No images downloaded ({len(failed_urls)} failed URLs), returning URLs"
                )
                return failed_urls
            else:
                logger.warning("No valid images extracted or downloaded")
                return None
        except Exception as e:
            logger.error(f"Error processing images response: {e}")
            return None

    # Convenience methods
    async def text_to_image(
        self, prompt: str, size: str = DEFAULT_SIZE, **kwargs
    ) -> Optional[List[bytes]]:
        """Text-to-image generation"""
        return await self.generate_image(
            prompt=prompt, images=None, size=size, **kwargs
        )

    async def image_to_image(
        self, prompt: str, image: str, size: str = DEFAULT_SIZE, **kwargs
    ) -> Optional[List[bytes]]:
        """Single image-to-image generation"""
        return await self.generate_image(
            prompt=prompt, images=[image], size=size, **kwargs
        )

    async def multi_image_to_image(
        self, prompt: str, images: List[str], size: str = DEFAULT_SIZE, **kwargs
    ) -> Optional[List[bytes]]:
        """Multi-image-to-image generation"""
        return await self.generate_image(
            prompt=prompt, images=images, size=size, **kwargs
        )

    async def sequential_image_generation(
        self,
        prompt: str,
        size: str = DEFAULT_SIZE,
        images: Optional[List[str]] = None,
        **kwargs,
    ) -> Optional[List[bytes]]:
        """Generate sequential images (auto mode)"""
        return await self.generate_image(
            prompt=prompt,
            size=size,
            images=images,
            sequential_image_generation="auto",
            **kwargs,
        )


# Global instance
seedream_service: Optional[SeedreamService] = None
if config.NOVITA_API_KEY:
    seedream_service = SeedreamService(api_key=config.NOVITA_API_KEY)
    logger.info("Seedream 4.5 (Novita AI) service initialized")
else:
    logger.warning("NOVITA_API_KEY not set, Seedream 4.5 service not available")
