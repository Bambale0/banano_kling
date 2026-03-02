"""
Replicate API Service - Интеграция с Replicate для генерации изображений

Документация: https://replicate.com/

Поддерживаемые модели:
- bytedance/seedream-5 - Генерация изображений из текста и image-to-image

Вебхуки (Webhook):
- Для асинхронного получения результатов укажите webhook_url при создании предикта
- webhook_events_filter: "start", "output", "logs", "completed"
- По умолчанию используется "completed" для минимизации нагрузки

Пример использования вебхука:
    result = await replicate_service.generate_image(
        prompt="A beautiful sunset",
        webhook_url="https://your-domain.com/webhook/replicate",
        webhook_events_filter=["completed"]  # или ["start", "completed"]
    )

Authentication:
- Токен хранится в REPLICATE_API_TOKEN
- Устанавливается через: export REPLICATE_API_TOKEN=<your-token>
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional

import aiohttp

logger = logging.getLogger(__name__)


class ReplicateService:
    """Сервис для работы с Replicate API"""

    # API Endpoints
    BASE_URL = "https://api.replicate.com/v1"
    
    # Supported models
    MODEL_SEEDREAM = "bytedance/seedream-5"

    # Valid parameters for Seedream
    ASPECT_RATIOS = ["1:1", "4:3", "3:4", "16:9", "9:16", "3:2", "2:3", "21:9", "match_input_image"]
    SIZES = ["2K", "3K"]
    OUTPUT_FORMATS = ["png", "jpeg"]
    SEQUENTIAL_MODES = ["disabled", "auto"]

    def __init__(self, api_token: str):
        self.api_token = api_token
        self.headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
        }

    async def generate_image(
        self,
        prompt: str,
        model: str = None,
        size: str = "2K",
        aspect_ratio: str = "2:3",
        max_images: int = 1,
        image_input: Optional[List[str]] = None,
        output_format: str = "png",
        sequential_image_generation: str = "disabled",
        webhook_url: Optional[str] = None,
        webhook_events_filter: Optional[List[str]] = None,
    ) -> Optional[Dict]:
        """
        Generate image using Replicate model (e.g., Seedream)
        
        Args:
            prompt: Text prompt for image generation
            model: Model identifier (default: bytedance/seedream-5)
            size: Image resolution - "2K" (2048px) or "3K" (3072px)
            aspect_ratio: Image aspect ratio
            max_images: Maximum number of images (1-15, only for sequential_image_generation='auto')
            image_input: List of input images for image-to-image generation
            output_format: Output format - "png" or "jpeg"
            sequential_image_generation: "disabled" or "auto"
            webhook_url: Optional callback URL for async notifications
            webhook_events_filter: List of events to trigger webhook
                - "start": immediately on prediction start
                - "output": each time a prediction generates an output
                - "logs": each time log output is generated
                - "completed": when prediction reaches terminal state (succeeded/canceled/failed)
                Default: ["completed"] if webhook_url is provided
            
        Returns:
            Dict with prediction info or None on error
        """
        if model is None:
            model = self.MODEL_SEEDREAM
            
        url = f"{self.BASE_URL}/predictions"
        
        # Build payload based on model
        payload = {
            "version": model,
            "input": {
                "prompt": prompt,
                "size": size,
                "aspect_ratio": aspect_ratio,
                "output_format": output_format,
                "sequential_image_generation": sequential_image_generation,
            }
        }
        
        # Add optional parameters
        if max_images > 1:
            payload["input"]["max_images"] = max_images
            
        if image_input:
            payload["input"]["image_input"] = image_input
            
        if webhook_url:
            payload["webhook"] = webhook_url
            # Use provided events filter or default to ["completed"]
            payload["webhook_events_filter"] = webhook_events_filter or ["completed"]
            
        logger.info(
            f"Replicate request: model={model}, prompt={prompt[:50]}..., "
            f"size={size}, aspect_ratio={aspect_ratio}"
        )
        
        return await self._post_request(url, payload)

    async def generate_seedream(
        self,
        prompt: str,
        size: str = "2K",
        aspect_ratio: str = "2:3",
        max_images: int = 1,
        image_input: Optional[List[str]] = None,
        output_format: str = "png",
        sequential_image_generation: str = "disabled",
    ) -> Optional[Dict]:
        """
        Generate image using Seedream model (bytedance/seedream-5-lite)
        
        Args:
            prompt: Text prompt for image generation
            size: Image resolution - "2K" (2048px) or "3K" (3072px)
            aspect_ratio: Image aspect ratio
            max_images: Maximum number of images (1-15, only for sequential_image_generation='auto')
            image_input: List of input images for image-to-image generation
            output_format: Output format - "png" or "jpeg"
            sequential_image_generation: "disabled" or "auto"
            
        Returns:
            Dict with prediction info or None on error
        """
        return await self.generate_image(
            prompt=prompt,
            model=self.MODEL_SEEDREAM,
            size=size,
            aspect_ratio=aspect_ratio,
            max_images=max_images,
            image_input=image_input,
            output_format=output_format,
            sequential_image_generation=sequential_image_generation,
        )

    async def get_prediction(self, prediction_id: str) -> Optional[Dict]:
        """
        Get prediction status and result
        
        Args:
            prediction_id: ID of the prediction
            
        Returns:
            Dict with prediction status and output
        """
        url = f"{self.BASE_URL}/predictions/{prediction_id}"
        logger.info(f"Replicate get prediction: {prediction_id}")
        return await self._get_request(url)

    async def cancel_prediction(self, prediction_id: str) -> Optional[Dict]:
        """
        Cancel a running prediction
        
        Args:
            prediction_id: ID of the prediction to cancel
            
        Returns:
            Dict with updated prediction status
        """
        url = f"{self.BASE_URL}/predictions/{prediction_id}/cancel"
        logger.info(f"Replicate cancel prediction: {prediction_id}")
        return await self._post_request(url, {})

    async def list_predictions(
        self,
        page: int = 1,
        page_size: int = 20,
    ) -> Optional[Dict]:
        """
        List user's predictions
        
        Args:
            page: Page number
            page_size: Number of items per page
            
        Returns:
            Dict with list of predictions
        """
        url = f"{self.BASE_URL}/predictions"
        params = {
            "page": page,
            "page_size": min(page_size, 100),
        }
        logger.info(f"Replicate list predictions: page={page}, page_size={page_size}")
        return await self._get_request(url, params)

    async def wait_for_completion(
        self,
        prediction_id: str,
        max_attempts: int = 60,
        delay: int = 5,
    ) -> Optional[Dict]:
        """
        Poll prediction until completion
        
        Args:
            prediction_id: ID of the prediction
            max_attempts: Maximum number of polling attempts
            delay: Delay between polls in seconds
            
        Returns:
            Dict with final prediction status
        """
        for attempt in range(max_attempts):
            prediction = await self.get_prediction(prediction_id)
            
            if not prediction:
                await asyncio.sleep(delay)
                continue
                
            status = prediction.get("status")
            
            if status == "succeeded":
                logger.info(f"Prediction {prediction_id} succeeded")
                return prediction
            elif status in ["failed", "canceled"]:
                logger.error(f"Prediction {prediction_id} {status}")
                return prediction
                
            logger.debug(
                f"Prediction {prediction_id} status: {status}, "
                f"attempt {attempt + 1}/{max_attempts}"
            )
            await asyncio.sleep(delay)
            
        logger.warning(f"Prediction {prediction_id} timeout after {max_attempts} attempts")
        return None

    # =========================================================================
    # Private HTTP Methods
    # =========================================================================

    async def _post_request(
        self,
        url: str,
        payload: Dict,
    ) -> Optional[Dict]:
        """Execute POST request to Replicate API"""
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
                        logger.info(
                            f"Replicate request successful: {data.get('id')}, "
                            f"status: {data.get('status')}"
                        )
                        return data
                    else:
                        logger.error(
                            f"Replicate API error {response.status}: {data}"
                        )
                        return None
                        
            except asyncio.TimeoutError:
                logger.error(f"Replicate request timeout: {url}")
                return None
            except aiohttp.ClientError as e:
                logger.error(f"Replicate request failed: {e}")
                return None
            except Exception as e:
                logger.exception(f"Unexpected error in Replicate request: {e}")
                return None

    async def _get_request(
        self,
        url: str,
        params: Optional[Dict] = None,
    ) -> Optional[Dict]:
        """Execute GET request to Replicate API"""
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
                                f"Replicate API returned HTML: {text[:500]}"
                            )
                            return None
                    else:
                        try:
                            data = await response.json()
                            logger.error(f"Replicate API error {response.status}: {data}")
                        except:
                            text = await response.text()
                            logger.error(f"Replicate API error {response.status}: {text[:500]}")
                        return None
                        
            except asyncio.TimeoutError:
                logger.error(f"Replicate request timeout: {url}")
                return None
            except aiohttp.ClientError as e:
                logger.error(f"Replicate request failed: {e}")
                return None
            except Exception as e:
                logger.exception(f"Unexpected error in Replicate request: {e}")
                return None


# =============================================================================
# Module initialization
# =============================================================================

from bot.config import config

# Initialize service with API token from config
replicate_service = ReplicateService(
    api_token=config.REPLICATE_API_TOKEN,
) if config.REPLICATE_API_TOKEN else None
