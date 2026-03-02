"""
Novita AI FLUX.2 Pro Service - Интеграция с Novita AI для генерации изображений

Документация: https://novita.ai/

Поддерживаемые модели:
- FLUX.2 [pro] - Production-grade text-to-image generation with enhanced realism,
  sharper text rendering, and native editing for reliable, repeatable results.

Endpoints:
- POST /v3/flux/flux-pro - Generate image using FLUX.2 Pro
- POST /v3/flux/flux-pro/edit - Edit image using FLUX.2 Pro
- GET /v3/task/{task_id} - Get task result

Особенности:
- Асинхронный API (возвращает task_id)
- Поддержка seed для воспроизводимых результатов
- Image-to-image редактирование (до 3 изображений)
- Размеры от 256 до 1536 пикселей
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional

import aiohttp

logger = logging.getLogger(__name__)


class NovitaService:
    """Сервис для работы с Novita AI FLUX.2 Pro API"""

    # API Endpoints
    BASE_URL = "https://api.novita.ai"
    
    # Valid parameters
    MIN_SIZE = 256
    MAX_SIZE = 1536
    MAX_IMAGES = 3
    
    # Valid duration range (for video generation)
    MIN_DURATION = 3
    MAX_DURATION = 15
    
    # Valid size presets - MAX quality (1536px)
    SIZE_PRESETS = {
        # Standard quality (1024px)
        "1:1": (1024, 1024),
        "16:9": (1280, 720),
        "9:16": (720, 1280),
        "4:3": (1024, 768),
        "3:4": (768, 1024),
        "21:9": (1280, 548),
        # High quality (1536px - MAX)
        "1:1_hq": (1536, 1536),
        "16:9_hq": (1536, 864),
        "9:16_hq": (864, 1536),
        "4:3_hq": (1536, 1152),
        "3:4_hq": (1152, 1536),
        "21:9_hq": (1536, 656),
    }
    
    # Aspect ratios for video
    ASPECT_RATIOS = ["1:1", "16:9", "9:16", "4:3", "3:4", "21:9"]
    
    # Duration options for video
    DURATIONS = ["3", "4", "5", "6", "7", "8", "9", "10", "11", "12", "13", "14", "15"]

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    async def generate_image(
        self,
        prompt: str,
        size: str = "1:1_hq",
        seed: int = -1,
        webhook_url: Optional[str] = None,
    ) -> Optional[Dict]:
        """
        Generate image using FLUX.2 Pro
        
        Args:
            prompt: Text prompt describing the expected image
            size: Size preset like "1:1", "16:9", "9:16", "1:1_hq", "16:9_hq", etc.
                  Use "_hq" suffix for maximum quality (1536px)
            seed: Random seed for generation (-1 for random). Range: -1 to 2147483647
            webhook_url: Optional callback URL for async notifications
            
        Returns:
            Dict with task_id or None on error
        """
        # Parse size
        width, height = self._parse_size(size)
        
        payload = {
            "prompt": prompt,
            "width": width,
            "height": height,
            "seed": seed if seed >= 0 else -1,
            "response_format": "url",  # Get URL in response
        }
        
        if webhook_url:
            payload["webhook_url"] = webhook_url
            
        url = f"{self.BASE_URL}/v3/flux/flux-pro"
        
        logger.info(
            f"Novita FLUX.2 Pro request: prompt={prompt[:50]}..., "
            f"size={width}x{height}, seed={seed}"
        )
        
        return await self._post_request(url, payload)

    async def edit_image(
        self,
        prompt: str,
        images: List[str],
        size: str = "1:1_hq",
        seed: int = -1,
        webhook_url: Optional[str] = None,
    ) -> Optional[Dict]:
        """
        Edit image(s) using FLUX.2 Pro
        
        Args:
            prompt: Text prompt describing the expected editing effect
            images: List of input image URLs for editing (up to 3)
            size: Size preset like "1:1", "16:9", "9:16", "1:1_hq", etc.
            seed: Random seed for generation (-1 for random). Range: -1 to 2147483647
            webhook_url: Optional callback URL for async notifications
            
        Returns:
            Dict with task_id or None on error
        """
        if len(images) > self.MAX_IMAGES:
            logger.error(f"Too many images: {len(images)}, max is {self.MAX_IMAGES}")
            return None
            
        # Parse size
        width, height = self._parse_size(size)
        
        payload = {
            "prompt": prompt,
            "images": images,
            "width": width,
            "height": height,
            "seed": seed if seed >= 0 else -1,
            "response_format": "url",
        }
        
        if webhook_url:
            payload["webhook_url"] = webhook_url
            
        url = f"{self.BASE_URL}/v3/flux/flux-pro/edit"
        
        logger.info(
            f"Novita FLUX.2 Pro edit request: prompt={prompt[:50]}..., "
            f"images_count={len(images)}, size={width}x{height}"
        )
        
        return await self._post_request(url, payload)

    async def generate_video(
        self,
        prompt: str,
        duration: int = 5,
        aspect_ratio: str = "16:9",
        seed: int = -1,
        webhook_url: Optional[str] = None,
    ) -> Optional[Dict]:
        """
        Generate video using FLUX.2 Pro (if supported)
        
        Args:
            prompt: Text prompt describing the expected video
            duration: Video duration in seconds (3-15)
            aspect_ratio: Video aspect ratio - "16:9", "9:16", "1:1", etc.
            seed: Random seed for generation (-1 for random). Range: -1 to 2147483647
            webhook_url: Optional callback URL for async notifications
            
        Returns:
            Dict with task_id or None on error
        """
        # Validate duration
        duration = self._validate_duration(duration)
        
        # Parse size from aspect ratio (use max quality)
        width, height = self._aspect_ratio_to_size(aspect_ratio)
        
        payload = {
            "prompt": prompt,
            "duration": str(duration),
            "width": width,
            "height": height,
            "seed": seed if seed >= 0 else -1,
            "response_format": "url",
        }
        
        if webhook_url:
            payload["webhook_url"] = webhook_url
            
        url = f"{self.BASE_URL}/v3/flux/flux-pro/video"
        
        logger.info(
            f"Novita FLUX.2 Pro video request: prompt={prompt[:50]}..., "
            f"duration={duration}s, size={width}x{height}, seed={seed}"
        )
        
        return await self._post_request(url, payload)

    def _validate_duration(self, duration: int) -> int:
        """Validate and clamp duration to valid range (3-15 seconds)"""
        return max(self.MIN_DURATION, min(self.MAX_DURATION, duration))

    def _aspect_ratio_to_size(self, aspect_ratio: str) -> tuple[int, int]:
        """Convert aspect ratio to size using max quality (1536px)"""
        ratio_map = {
            "1:1": (1536, 1536),
            "16:9": (1536, 864),
            "9:16": (864, 1536),
            "4:3": (1536, 1152),
            "3:4": (1152, 1536),
            "21:9": (1536, 656),
        }
        return ratio_map.get(aspect_ratio, (1536, 864))  # Default to 16:9

    async def get_task_result(self, task_id: str) -> Optional[Dict]:
        """
        Get task result (async polling)
        
        Args:
            task_id: ID of the task to check
            
        Returns:
            Dict with task status and result
        """
        url = f"{self.BASE_URL}/v3/task/{task_id}"
        logger.info(f"Novita get task result: {task_id}")
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
            max_attempts: Maximum number of polling attempts
            delay: Delay between polls in seconds
            
        Returns:
            Dict with final task status
        """
        for attempt in range(max_attempts):
            result = await self.get_task_result(task_id)
            
            if not result:
                await asyncio.sleep(delay)
                continue
                
            status = result.get("status")
            
            if status == "COMPLETED":
                logger.info(f"Task {task_id} completed successfully")
                return result
            elif status in ["FAILED", "ERROR"]:
                logger.error(f"Task {task_id} {status}: {result.get('error', 'Unknown error')}")
                return result
                
            logger.debug(
                f"Task {task_id} status: {status}, "
                f"attempt {attempt + 1}/{max_attempts}"
            )
            await asyncio.sleep(delay)
            
        logger.warning(f"Task {task_id} timeout after {max_attempts} attempts")
        return None

    def _parse_size(self, size: str) -> tuple[int, int]:
        """
        Parse size string to width and height
        
        Args:
            size: Size string like "1:1", "1024x1024", "16:9", etc.
            
        Returns:
            Tuple of (width, height)
        """
        # Check if it's a preset
        if size in self.SIZE_PRESETS:
            return self.SIZE_PRESETS[size]
        
        # Try to parse as "WIDTHxHEIGHT" format
        if "x" in size.lower():
            try:
                parts = size.lower().split("x")
                width = int(parts[0])
                height = int(parts[1])
                # Clamp to valid range
                width = max(self.MIN_SIZE, min(self.MAX_SIZE, width))
                height = max(self.MIN_SIZE, min(self.MAX_SIZE, height))
                return (width, height)
            except (ValueError, IndexError):
                pass
        
        # Default to 1024x1024
        logger.warning(f"Invalid size format: {size}, using default 1024x1024")
        return (1024, 1024)

    # =========================================================================
    # Private HTTP Methods
    # =========================================================================

    async def _post_request(
        self,
        url: str,
        payload: Dict,
    ) -> Optional[Dict]:
        """Execute POST request to Novita API"""
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(
                    url,
                    json=payload,
                    headers=self.headers,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as response:
                    data = await response.json()
                    
                    if response.status in [200, 201]:
                        task_id = data.get("task_id")
                        logger.info(
                            f"Novita request successful: {task_id}, status: {data.get('status', 'CREATED')}"
                        )
                        return data
                    else:
                        logger.error(
                            f"Novita API error {response.status}: {data}"
                        )
                        return None
                        
            except asyncio.TimeoutError:
                logger.error(f"Novita request timeout: {url}")
                return None
            except aiohttp.ClientError as e:
                logger.error(f"Novita request failed: {e}")
                return None
            except Exception as e:
                logger.exception(f"Unexpected error in Novita request: {e}")
                return None

    async def _get_request(
        self,
        url: str,
        params: Optional[Dict] = None,
    ) -> Optional[Dict]:
        """Execute GET request to Novita API"""
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
                                f"Novita API returned HTML: {text[:500]}"
                            )
                            return None
                    else:
                        try:
                            data = await response.json()
                            logger.error(f"Novita API error {response.status}: {data}")
                        except:
                            text = await response.text()
                            logger.error(f"Novita API error {response.status}: {text[:500]}")
                        return None
                        
            except asyncio.TimeoutError:
                logger.error(f"Novita request timeout: {url}")
                return None
            except aiohttp.ClientError as e:
                logger.error(f"Novita request failed: {e}")
                return None
            except Exception as e:
                logger.exception(f"Unexpected error in Novita request: {e}")
                return None


# =============================================================================
# Module initialization
# =============================================================================

from bot.config import config

# Initialize service with API key from config
novita_service = NovitaService(
    api_key=config.NOVITA_API_KEY,
) if config.NOVITA_API_KEY else None
