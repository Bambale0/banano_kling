"""
Novita AI Service - Интеграция с Novita AI для генерации изображений

Документация: https://novita.ai/

Поддерживаемые модели:
1. FLUX.2 [pro] - Production-grade text-to-image generation with enhanced realism,
   sharper text rendering, and native editing for reliable, repeatable results.
   
2. Seedream 5.0 lite - Supports text-to-image, single/multi-image-to-image 
   (up to 14 reference images), and sequential image generation.

3. Z-Image Turbo LoRA - High-speed image generation with custom LoRA weights support.
   Supports up to 3 LoRAs with configurable scale (0-4).

Endpoints:
- POST /v3/async/flux-2-pro - Generate image using FLUX.2 Pro
- POST /v3/async/flux-2-pro - Edit image using FLUX.2 Pro
- POST /v3/seedream/seedream-5-lite - Generate/edit using Seedream 5.0
- POST /v3/async/z-image-turbo-lora - Generate image with Z-Image Turbo LoRA
- GET /v3/async/task-result - Get task result

Особенности:
- Асинхронный API (возвращает task_id)
- Поддержка seed для воспроизводимых результатов
- FLUX: Image-to-image редактирование (до 3 изображений)
- Seedream: До 14 референсных изображений
- Z-Image Turbo: До 3 LoRA с настраиваемой силой (scale 0-4)
- Размеры от 256 до 2048 пикселей
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional

import aiohttp

logger = logging.getLogger(__name__)


class NovitaService:
    """Сервис для работы с Novita AI FLUX.2 Pro и Seedream API"""

    # API Endpoints
    BASE_URL = "https://api.novita.ai"

    # Valid parameters - FLUX
    MIN_SIZE = 256
    MAX_SIZE = 1536  # Backward compatibility alias for MAX_SIZE_FLUX
    MAX_SIZE_FLUX = 1536
    MAX_SIZE_SEEDREAM = 2048
    MAX_IMAGES = 3  # Backward compatibility alias for MAX_IMAGES_FLUX
    MAX_IMAGES_FLUX = 3
    MAX_IMAGES_SEEDREAM = 14

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

        API: POST /v3/async/flux-2-pro

        Args:
            prompt: Text prompt describing the expected image (required)
            size: Size preset like "1:1", "16:9", "9:16", "1:1_hq", "16:9_hq", etc.
                  Use "_hq" suffix for maximum quality (1536px)
            seed: Random seed for generation (-1 for random). Range: -1 to 2147483647
            webhook_url: Optional callback URL for async notifications

        Returns:
            Dict with task_id or None on error
        """
        # Parse size to WIDTH*HEIGHT format (API uses * as separator)
        width, height = self._parse_size(size)
        size_str = f"{width}*{height}"

        # Build payload according to API spec
        # Webhook must be in extra.webhook.url format
        payload = {
            "prompt": prompt,
            "size": size_str,
            "seed": seed if seed >= 0 else -1,
        }

        if webhook_url:
            payload["extra"] = {"webhook": {"url": webhook_url}}

        url = f"{self.BASE_URL}/v3/async/flux-2-pro"

        logger.info(
            f"Novita FLUX.2 Pro request: prompt={prompt[:50]}..., "
            f"size={size_str}, seed={seed}, webhook={webhook_url is not None}"
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

        API: POST /v3/async/flux-2-pro (same endpoint, with images param)

        Args:
            prompt: Text prompt describing the expected editing effect
            images: List of input image URLs for editing (up to 3)
            size: Size preset like "1:1", "16:9", "9:16", "1:1_hq", etc.
            seed: Random seed for generation (-1 for random). Range: -1 to 2147483647
            webhook_url: Optional callback URL for async notifications

        Returns:
            Dict with task_id or None on error
        """
        if len(images) > self.MAX_IMAGES_FLUX:
            logger.error(
                f"Too many images: {len(images)}, max is {self.MAX_IMAGES_FLUX}"
            )
            return None

        # Parse size to WIDTH*HEIGHT format (API uses * as separator)
        width, height = self._parse_size(size)
        size_str = f"{width}*{height}"

        # Build payload according to API spec
        # Webhook must be in extra.webhook.url format
        payload = {
            "prompt": prompt,
            "images": images,
            "size": size_str,
            "seed": seed if seed >= 0 else -1,
        }

        if webhook_url:
            payload["extra"] = {"webhook": {"url": webhook_url}}

        url = f"{self.BASE_URL}/v3/async/flux-2-pro"

        logger.info(
            f"Novita FLUX.2 Pro edit request: prompt={prompt[:50]}..., "
            f"images_count={len(images)}, size={size_str}, webhook={webhook_url is not None}"
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

    # =========================================================================
    # Seedream 5.0 Lite Methods
    # =========================================================================

    async def generate_seedream_image(
        self,
        prompt: str,
        size: str = "2048x2048",
        image: Optional[List[str]] = None,
        watermark: bool = True,
        optimize_prompt_options: Optional[Dict[str, str]] = None,
        sequential_image_generation: str = "disabled",
        sequential_image_generation_options: Optional[Dict[str, int]] = None,
        webhook_url: Optional[str] = None,
    ) -> Optional[Dict]:
        """
        Generate image using Seedream 5.0 Lite

        API: POST /v3/seedream/seedream-5-lite

        Args:
            prompt: Text prompt for image generation (supports Chinese and English)
                   Recommended: max 300 Chinese chars or 600 English words
            size: Image size - "2K", "3K", or "WIDTHxHEIGHT" format
                  Range: 2560x1440 (3,686,400 pixels) to 3072x3072 (9,437,184 pixels)
            image: Optional list of reference image URLs or Base64 (up to 14 images)
                   Supports: jpeg, png, webp, bmp, tiff, gif
            watermark: Whether to add watermark (default: True)
            optimize_prompt_options: Prompt optimization config
                - mode: "standard" (only supported mode)
            sequential_image_generation: Sequential generation mode
                - "auto": Model decides based on prompt
                - "disabled": Generate single image only (default)
            sequential_image_generation_options: Config for sequential generation
                - max_images: Maximum images to generate (1-15)
                  Note: input images + generated images ≤ 15
            webhook_url: Optional callback URL for async notifications

        Returns:
            Dict with task_id or None on error
        """
        # Validate image count
        if image and len(image) > self.MAX_IMAGES_SEEDREAM:
            logger.error(
                f"Too many images: {len(image)}, max is {self.MAX_IMAGES_SEEDREAM}"
            )
            return None

        # Parse size
        width, height = self._parse_seedream_size(size)

        # Build payload according to API spec
        # Webhook must be in extra.webhook.url format
        payload = {
            "prompt": prompt,
            "size": f"{width}x{height}",
            "watermark": watermark,
        }

        # Add optional image array
        if image:
            payload["image"] = image

        # Add prompt optimization options
        if optimize_prompt_options:
            payload["optimize_prompt_options"] = optimize_prompt_options

        # Add sequential image generation settings
        if sequential_image_generation in ["auto", "disabled"]:
            payload["sequential_image_generation"] = sequential_image_generation

        # Add sequential generation options (only when mode is "auto")
        if (
            sequential_image_generation == "auto"
            and sequential_image_generation_options
        ):
            payload[
                "sequential_image_generation_options"
            ] = sequential_image_generation_options

        if webhook_url:
            payload["extra"] = {"webhook": {"url": webhook_url}}

        url = f"{self.BASE_URL}/v3/seedream-5.0-lite"

        logger.info(f"POST {url}")  # Debug logging for URL
        logger.info(f"Payload: {payload}")  # Debug logging for payload
        
        logger.info(
            f"Novita Seedream 5.0 request: prompt={prompt[:50]}..., "
            f"size={width}x{height}, images={len(image) if image else 0}, "
            f"watermark={watermark}, sequential={sequential_image_generation}, webhook={webhook_url is not None}"
        )

        result = await self._post_request(url, payload)
        if result:
            logger.info(f"Seedream response: {result}")
        return result

    async def edit_seedream_image(
        self,
        prompt: str,
        images: List[str],
        size: str = "2048x2048",
        watermark: bool = True,
        optimize_prompt_options: Optional[Dict[str, str]] = None,
        sequential_image_generation: str = "disabled",
        sequential_image_generation_options: Optional[Dict[str, int]] = None,
        webhook_url: Optional[str] = None,
    ) -> Optional[Dict]:
        """
        Edit image(s) using Seedream 5.0 Lite (Image-to-Image)

        API: POST /v3/seedream/seedream-5-lite

        Args:
            prompt: Text prompt describing the editing effect
            images: List of input image URLs or Base64 (up to 14 images)
            size: Output image size - "2K", "3K", or "WIDTHxHEIGHT"
            watermark: Whether to add watermark (default: True)
            optimize_prompt_options: Prompt optimization config
            sequential_image_generation: Sequential generation mode
            sequential_image_generation_options: Config for sequential generation
            webhook_url: Optional callback URL for async notifications

        Returns:
            Dict with task_id or None on error
        """
        if len(images) > self.MAX_IMAGES_SEEDREAM:
            logger.error(
                f"Too many images: {len(images)}, max is {self.MAX_IMAGES_SEEDREAM}"
            )
            return None

        # Parse size
        width, height = self._parse_seedream_size(size)

        # Build payload
        # Webhook must be in extra.webhook.url format
        payload = {
            "prompt": prompt,
            "image": images,  # API uses "image" not "images"
            "size": f"{width}x{height}",
            "watermark": watermark,
        }

        # Add prompt optimization options
        if optimize_prompt_options:
            payload["optimize_prompt_options"] = optimize_prompt_options

        # Add sequential image generation settings
        if sequential_image_generation in ["auto", "disabled"]:
            payload["sequential_image_generation"] = sequential_image_generation

        # Add sequential generation options
        if (
            sequential_image_generation == "auto"
            and sequential_image_generation_options
        ):
            payload[
                "sequential_image_generation_options"
            ] = sequential_image_generation_options

        if webhook_url:
            payload["extra"] = {"webhook": {"url": webhook_url}}

        url = f"{self.BASE_URL}/v3/seedream-5.0-lite"

        logger.info(f"POST {url}")  # Debug logging for URL
        logger.info(f"Payload: {payload}")  # Debug logging for payload
        
        logger.info(
            f"Novita Seedream 5.0 edit request: prompt={prompt[:50]}..., "
            f"images_count={len(images)}, size={width}x{height}, "
            f"sequential={sequential_image_generation}, webhook={webhook_url is not None}"
        )

        result = await self._post_request(url, payload)
        if result:
            logger.info(f"Seedream edit response: {result}")
        return result

    def _parse_seedream_size(self, size: str) -> tuple[int, int]:
        """
        Parse Seedream size string to width and height

        Args:
            size: Size string like "2048x2048", "2K", "3K", "2560x1440"

        Returns:
            Tuple of (width, height)
        """
        # Check for presets
        if size.lower() in ["2k", "2k resolution"]:
            return (2048, 2048)
        elif size.lower() in ["3k", "3k resolution"]:
            return (3072, 3072)

        # Try to parse as "WIDTHxHEIGHT" format
        if "x" in size.lower():
            try:
                parts = size.lower().split("x")
                width = int(parts[0])
                height = int(parts[1])
                # Validate range (2560x1440 to 3072x3072)
                min_pixels = 2560 * 1440
                max_pixels = 3072 * 3072
                pixels = width * height
                if min_pixels <= pixels <= max_pixels:
                    return (width, height)
                # Clamp to valid range
                if pixels < min_pixels:
                    # Scale up to minimum
                    aspect = width / height
                    height = int((min_pixels / aspect) ** 0.5)
                    width = int(height * aspect)
                else:
                    # Scale down to maximum
                    aspect = width / height
                    height = int((max_pixels / aspect) ** 0.5)
                    width = int(height * aspect)
                return (width, height)
            except (ValueError, IndexError, ZeroDivisionError):
                pass

        # Default to 2048x2048
        logger.warning(f"Invalid Seedream size format: {size}, using default 2048x2048")
        return (2048, 2048)

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

    async def generate_image_turbo_lora(
        self,
        prompt: str,
        size: str = "1024*1024",
        seed: int = -1,
        loras: Optional[List[Dict[str, Any]]] = None,
        webhook_url: Optional[str] = None,
    ) -> Optional[Dict]:
        """
        Generate image using Z-Image Turbo LoRA (alias for generate_z_image_turbo_lora)

        API: POST /v3/async/z-image-turbo-lora

        Z-Image Turbo LoRA is a high-speed image generation model that supports
        rapid generation of high-quality images based on text prompts,
        with support for applying custom LoRA weights.

        Args:
            prompt: Positive prompt for generation (required)
            size: Pixel dimensions of the generated image (width*height)
                  Default: "1024*1024"
            seed: Random seed for generation (-1 for random)
                  Range: -1 to 2147483647
            loras: List of LoRAs to apply (maximum 3)
                  Each LoRA should have:
                  - path: URL or path to the LoRA weights (required)
                  - scale: Scale factor for the LoRA weights (default: 1, range: 0-4)
            webhook_url: Optional callback URL for async notifications

        Returns:
            Dict with task_id or None on error
        """
        # Validate LoRA count
        if loras and len(loras) > 3:
            logger.error(f"Too many loras: {len(loras)}, max is 3")
            return None

        # Validate each LoRA
        validated_loras = []
        if loras:
            for i, lora in enumerate(loras):
                if not isinstance(lora, dict):
                    logger.error(f"LoRA {i}: must be a dictionary")
                    continue
                
                lora_path = lora.get("path")
                if not lora_path:
                    logger.error(f"LoRA {i}: 'path' is required")
                    continue
                
                # Validate scale
                scale = lora.get("scale", 1)
                if not isinstance(scale, (int, float)):
                    try:
                        scale = float(scale)
                    except (ValueError, TypeError):
                        scale = 1
                scale = max(0, min(4, scale))  # Clamp to 0-4 range
                
                validated_loras.append({
                    "path": lora_path,
                    "scale": scale,
                })

        # Parse size (format: WIDTH*HEIGHT)
        width, height = self._parse_turbo_size(size)
        size_str = f"{width}*{height}"

        # Build payload according to API spec
        payload = {
            "prompt": prompt,
            "size": size_str,
            "seed": seed if seed >= 0 else -1,
            "loras": validated_loras,
        }

        if webhook_url:
            payload["extra"] = {"webhook": {"url": webhook_url}}

        url = f"{self.BASE_URL}/v3/async/z-image-turbo-lora"

        lora_info = ""
        if validated_loras:
            lora_names = [l["path"].split("/")[-1] if "/" in l["path"] else l["path"][:20] for l in validated_loras]
            lora_info = f", loras={lora_names}"

        logger.info(
            f"Novita Z-Image Turbo LoRA request: prompt={prompt[:50]}..., "
            f"size={size_str}, seed={seed}{lora_info}, webhook={webhook_url is not None}"
        )

        return await self._post_request(url, payload)

    def _parse_turbo_size(self, size: str) -> tuple[int, int]:
        """
        Parse Z-Image Turbo size string to width and height

        Args:
            size: Size string like "1024*1024", "512*512", "1024x1024", etc.

        Returns:
            Tuple of (width, height)
        """
        # Try to parse as "WIDTH*HEIGHT" or "WIDTHxHEIGHT" format
        for separator in ["*", "x"]:
            if separator in size.lower():
                try:
                    parts = size.lower().split(separator)
                    width = int(parts[0])
                    height = int(parts[1])
                    # Z-Image Turbo supports various sizes, default to reasonable range
                    width = max(256, min(2048, width))
                    height = max(256, min(2048, height))
                    return (width, height)
                except (ValueError, IndexError, ZeroDivisionError):
                    pass

        # Default to 1024x1024
        logger.warning(f"Invalid Z-Image Turbo size format: {size}, using default 1024*1024")
        return (1024, 1024)

    async def get_task_result(self, task_id: str) -> Optional[Dict]:
        """
        Get task result (async polling)

        Args:
            task_id: ID of the task to check

        Returns:
            Dict with task status and result
        """
        url = f"{self.BASE_URL}/v3/async/task-result?task_id={task_id}"
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
            Dict with final task status and images
        """
        for attempt in range(max_attempts):
            result = await self.get_task_result(task_id)

            if not result:
                await asyncio.sleep(delay)
                continue

            # New API format: status is in result["task"]["status"]
            task_info = result.get("task", {})
            status = task_info.get("status")

            if status == "TASK_STATUS_SUCCEED":
                logger.info(f"Task {task_id} completed successfully")
                return result
            elif status == "TASK_STATUS_FAILED":
                reason = task_info.get("reason", "Unknown error")
                logger.error(f"Task {task_id} failed: {reason}")
                return result
            elif status == "TASK_STATUS_QUEUED":
                logger.debug(
                    f"Task {task_id} queued, attempt {attempt + 1}/{max_attempts}"
                )
            elif status == "TASK_STATUS_PROCESSING":
                logger.debug(
                    f"Task {task_id} processing, attempt {attempt + 1}/{max_attempts}"
                )
            else:
                logger.debug(
                    f"Task {task_id} status: {status}, attempt {attempt + 1}/{max_attempts}"
                )

            await asyncio.sleep(delay)

        logger.warning(f"Task {task_id} timeout after {max_attempts} attempts")
        return None

    def _parse_size(self, size: str, max_size: int = None) -> tuple[int, int]:
        """
        Parse size string to width and height

        Args:
            size: Size string like "1:1", "1024x1024", "16:9", etc.
            max_size: Optional max size override (for different models)

        Returns:
            Tuple of (width, height)
        """
        if max_size is None:
            max_size = self.MAX_SIZE_FLUX

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
                width = max(self.MIN_SIZE, min(max_size, width))
                height = max(self.MIN_SIZE, min(max_size, height))
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
                        logger.error(f"Novita API error {response.status}: {data}")
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
                            logger.error(f"Novita API returned HTML: {text[:500]}")
                            return None
                    else:
                        try:
                            data = await response.json()
                            logger.error(f"Novita API error {response.status}: {data}")
                        except:
                            text = await response.text()
                            logger.error(
                                f"Novita API error {response.status}: {text[:500]}"
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


# =============================================================================
# Module initialization
# =============================================================================

from bot.config import config

# Initialize service with API key from config
novita_service = (
    NovitaService(
        api_key=config.NOVITA_API_KEY,
    )
    if config.NOVITA_API_KEY
    else None
)
