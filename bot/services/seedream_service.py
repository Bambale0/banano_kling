"""
Seedream 5.0 Lite Service - Интеграция с Novita AI Seedream 5.0 Lite API

Документация: https://novita.ai/

Поддерживаемые функции:
- Text-to-image (T2I)
- Single image-to-image (I2I)
- Multi-image-to-image (до 14 референсных изображений)
- Sequential image generation (генерация серии изображений)

Особенности:
- Поддержка китайского и английского языков в промптах
- Оптимизация промптов (standard/fast mode)
- Настраиваемый размер изображения
- Водяной знак (включен по умолчанию)
"""

import asyncio
import logging
import base64
from typing import Any, Dict, List, Optional

import aiohttp

logger = logging.getLogger(__name__)


class SeedreamService:
    """Сервис для работы с Novita AI Seedream 5.0 Lite API"""

    # API Endpoints
    BASE_URL = "https://api.novita.ai"
    
    # Model name
    MODEL_SEEDREAM_LITE = "ByteDance/seedream-5-lite"

    # Valid parameters
    ASPECT_RATIOS = ["1:1", "4:3", "3:4", "16:9", "9:16", "3:2", "2:3", "21:9", "match_input_image"]
    SIZES = ["2K", "3K"]  # 2K = 2048px, 3K = 3072px
    RESOLUTIONS = [
        "2560x1440", "3072x1728", "3456x1944", "3840x2160",  # 16:9 variants
        "1440x2560", "1728x3072", "1944x3456", "2160x3840",  # 9:16 variants
        "2048x2048", "2560x2560", "3072x3072",  # 1:1 variants
    ]
    SEQUENTIAL_MODES = ["disabled", "auto"]
    OPTIMIZE_MODES = ["standard"]  # Currently only standard is supported
    
    # Pixel range constraints
    MIN_PIXELS = 2560 * 1440  # 3686400
    MAX_PIXELS = 3072 * 3072 * 1.1025  # ~10404496

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
        max_images: int = 1,
    ) -> Optional[Dict]:
        """
        Generate image using Seedream 5.0 Lite
        
        Args:
            prompt: Text prompt for image generation (supports Chinese and English)
            size: Image size - "2K", "3K" or "WIDTHxHEIGHT" (e.g., "2048x2048")
            images: List of input images (URL or Base64) for image-to-image generation
            watermark: Whether to add watermark to generated images (default: True)
            optimize_prompt: Enable prompt optimization
            optimize_mode: Optimization mode - "standard" (only supported)
            sequential_generation: "disabled" or "auto" for sequential image generation
            max_images: Maximum number of images (1-15) when sequential_generation is "auto"
            
        Returns:
            Dict with generation result or None on error
        """
        url = f"{self.BASE_URL}/v3/extra/image/generation"
        
        # Build input payload
        input_data = {
            "prompt": prompt,
            "size": size,
            "watermark": watermark,
        }
        
        # Add images for image-to-image generation
        if images:
            image_list = []
            for img in images[:14]:  # Max 14 images
                if img.startswith("http://") or img.startswith("https://"):
                    image_list.append({"url": img})
                else:
                    # Assume Base64
                    image_list.append({"url": f"data:image/jpeg;base64,{img}"})
            input_data["image"] = image_list
        
        # Add prompt optimization
        if optimize_prompt:
            input_data["optimize_prompt_options"] = {
                "mode": optimize_mode if optimize_mode in self.OPTIMIZE_MODES else "standard"
            }
        
        # Add sequential image generation
        if sequential_generation == "auto":
            input_data["sequential_image_generation"] = "auto"
            input_data["sequential_image_generation_options"] = {
                "max_images": min(max(max_images, 1), 15)
            }
        
        payload = {
            "model": self.MODEL_SEEDREAM_LITE,
            "input": input_data,
        }
        
        logger.info(
            f"Seedream request: prompt={prompt[:50]}..., "
            f"size={size}, images={len(images) if images else 0}, "
            f"sequential={sequential_generation}"
        )
        
        return await self._post_request(url, payload)

    async def text_to_image(
        self,
        prompt: str,
        size: str = "2048x2048",
        watermark: bool = True,
        optimize_prompt: bool = False,
    ) -> Optional[Dict]:
        """
        Text-to-image generation
        
        Args:
            prompt: Text prompt
            size: Image size
            watermark: Add watermark
            optimize_prompt: Optimize prompt
            
        Returns:
            Dict with result
        """
        return await self.generate_image(
            prompt=prompt,
            size=size,
            images=None,
            watermark=watermark,
            optimize_prompt=optimize_prompt,
        )

    async def image_to_image(
        self,
        prompt: str,
        image: str,
        size: str = "2048x2048",
        watermark: bool = True,
        optimize_prompt: bool = False,
    ) -> Optional[Dict]:
        """
        Single image-to-image generation
        
        Args:
            prompt: Text prompt
            image: Input image URL or Base64
            size: Image size
            watermark: Add watermark
            optimize_prompt: Optimize prompt
            
        Returns:
            Dict with result
        """
        return await self.generate_image(
            prompt=prompt,
            size=size,
            images=[image],
            watermark=watermark,
            optimize_prompt=optimize_prompt,
        )

    async def multi_image_to_image(
        self,
        prompt: str,
        images: List[str],
        size: str = "2048x2048",
        watermark: bool = True,
        optimize_prompt: bool = False,
    ) -> Optional[Dict]:
        """
        Multi-image-to-image generation (up to 14 reference images)
        
        Args:
            prompt: Text prompt
            images: List of input images (URL or Base64), max 14
            size: Image size
            watermark: Add watermark
            optimize_prompt: Optimize prompt
            
        Returns:
            Dict with result
        """
        if len(images) > 14:
            logger.warning(f"Too many images ({len(images)}), truncating to 14")
            images = images[:14]
            
        return await self.generate_image(
            prompt=prompt,
            size=size,
            images=images,
            watermark=watermark,
            optimize_prompt=optimize_prompt,
        )

    async def sequential_generation(
        self,
        prompt: str,
        size: str = "2048x2048",
        images: Optional[List[str]] = None,
        watermark: bool = True,
        optimize_prompt: bool = False,
        max_images: int = 15,
    ) -> Optional[Dict]:
        """
        Sequential image generation - generates multiple images based on prompt
        
        Args:
            prompt: Text prompt
            size: Image size
            images: Optional reference images
            watermark: Add watermark
            optimize_prompt: Optimize prompt
            max_images: Maximum images to generate (1-15)
            
        Returns:
            Dict with multiple generated images
        """
        return await self.generate_image(
            prompt=prompt,
            size=size,
            images=images,
            watermark=watermark,
            optimize_prompt=optimize_prompt,
            sequential_generation="auto",
            max_images=max_images,
        )

    async def get_task_status(self, task_id: str) -> Optional[Dict]:
        """
        Get task status and result
        
        Args:
            task_id: ID of the task
            
        Returns:
            Dict with task status
        """
        url = f"{self.BASE_URL}/v3/extra/image/generation/{task_id}"
        logger.info(f"Seedream get task status: {task_id}")
        return await self._get_request(url)

    async def wait_for_completion(
        self,
        task_id: str,
        max_attempts: int = 60,
        delay: int = 5,
    ) -> Optional[Dict]:
        """
        Poll task until completion
        
        Args:
            task_id: ID of the task
            max_attempts: Maximum polling attempts
            delay: Delay between polls in seconds
            
        Returns:
            Dict with final result
        """
        for attempt in range(max_attempts):
            result = await self.get_task_status(task_id)
            
            if not result:
                await asyncio.sleep(delay)
                continue
            
            status = result.get("status")
            
            if status == "completed":
                logger.info(f"Task {task_id} completed successfully")
                return result
            elif status in ["failed", "error"]:
                logger.error(f"Task {task_id} {status}")
                return result
                
            logger.debug(
                f"Task {task_id} status: {status}, "
                f"attempt {attempt + 1}/{max_attempts}"
            )
            await asyncio.sleep(delay)
            
        logger.warning(f"Task {task_id} timeout after {max_attempts} attempts")
        return None

    # =========================================================================
    # Private HTTP Methods
    # =========================================================================

    async def _post_request(
        self,
        url: str,
        payload: Dict,
    ) -> Optional[Dict]:
        """Execute POST request to Novita AI API"""
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
                        task_id = data.get("task_id")
                        logger.info(
                            f"Seedream task created: {task_id}, "
                            f"status: {data.get('status')}"
                        )
                        return data
                    else:
                        logger.error(
                            f"Seedream API error {response.status}: {data}"
                        )
                        return None
                        
            except asyncio.TimeoutError:
                logger.error(f"Seedream request timeout: {url}")
                return None
            except aiohttp.ClientError as e:
                logger.error(f"Seedream request failed: {e}")
                return None
            except Exception as e:
                logger.exception(f"Unexpected error in Seedream request: {e}")
                return None

    async def _get_request(
        self,
        url: str,
        params: Optional[Dict] = None,
    ) -> Optional[Dict]:
        """Execute GET request to Novita AI API"""
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(
                    url,
                    params=params,
                    headers=self.headers,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as response:
                    if response.status == 200:
                        content_type = response.headers.get("Content-Type", "")
                        
                        if "application/json" in content_type:
                            return await response.json()
                        else:
                            text = await response.text()
                            logger.error(
                                f"Seedream API returned HTML: {text[:500]}"
                            )
                            return None
                    else:
                        try:
                            data = await response.json()
                            logger.error(f"Seedream API error {response.status}: {data}")
                        except:
                            text = await response.text()
                            logger.error(f"Seedream API error {response.status}: {text[:500]}")
                        return None
                        
            except asyncio.TimeoutError:
                logger.error(f"Seedream request timeout: {url}")
                return None
            except aiohttp.ClientError as e:
                logger.error(f"Seedream request failed: {e}")
                return None
            except Exception as e:
                logger.exception(f"Unexpected error in Seedream request: {e}")
                return None


# =============================================================================
# Module initialization
# =============================================================================

from bot.config import config

# Initialize service with API key from config
seedream_service = SeedreamService(
    api_key=config.NOVITA_API_KEY,
) if config.NOVITA_API_KEY else None
