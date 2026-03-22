"""
RunwayML Gen-4.5 Service via Replicate API

Model: runwayml/gen-4.5
Docs: runway.md
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional

import replicate

from bot.config import config

logger = logging.getLogger(__name__)


class RunwayService:
    """Сервис для работы с RunwayML Gen-4.5 через Replicate API"""

    MODEL_VERSION = "runwayml/gen-4.5"

    ASPECT_RATIOS = ["16:9", "9:16", "4:3", "3:4", "1:1", "21:9"]
    DURATIONS = [5, 10]

    def __init__(self, api_token: Optional[str] = None):
        self.api_token = api_token or config.REPLICATE_API_TOKEN
        if self.api_token:
            replicate.Client(api_token=self.api_token)

    async def generate_video(
        self,
        prompt: str,
        duration: int = 5,
        aspect_ratio: str = "16:9",
        image_url: Optional[str] = None,
        reference_image_urls: Optional[List[str]] = None,
        seed: Optional[int] = None,
        webhook_url: Optional[str] = None,
    ) -> Optional[Dict]:
        """Генерация видео text-to-video или image-to-video"""
        duration = max(5, min(duration, 10))
        aspect_ratio = aspect_ratio if aspect_ratio in self.ASPECT_RATIOS else "16:9"

        input_data = {
            "prompt": prompt,
            "duration": duration,
            "aspect_ratio": aspect_ratio,
        }

        # Preserve face/identity when the caller supplies reference imagery.
        # Runway Gen-4.5 only accepts a single initial image, so we prefer the
        # explicit start image, then fall back to the first reference image.
        if not image_url and reference_image_urls:
            image_url = reference_image_urls[0]

        if image_url:
            input_data["image"] = image_url
        # If reference images provided, build elements to help preserve
        # identity/face consistency. Runway accepts a single start image but
        # we can pass reference images as 'elements' so downstream logic
        # can preserve faces similar to Kling's "elements" parameter.
        if reference_image_urls:
            elements = []
            for ref in reference_image_urls[:4]:
                elements.append(
                    {"reference_image_urls": [ref], "frontal_image_url": ref}
                )
            input_data["elements"] = elements
        if seed:
            input_data["seed"] = seed

        try:
            prediction = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: replicate.predictions.create(
                    model=self.MODEL_VERSION,
                    input=input_data,
                    webhook=webhook_url,
                    webhook_events_filter=["completed"] if webhook_url else None,
                ),
            )
            logger.info(f"Runway prediction created: {prediction.id}")
            return {
                "task_id": prediction.id,
                "status": prediction.status,
            }
        except Exception as e:
            logger.error(f"Runway API error: {e}")
            return {"error": "api_error", "message": str(e)}

    async def get_task_status(self, task_id: str) -> Optional[Dict]:
        """Получить статус предсказания"""
        try:
            prediction = await asyncio.get_event_loop().run_in_executor(
                None, lambda: replicate.predictions.get(task_id)
            )
            if prediction.status in ["succeeded", "failed", "canceled"]:
                output = prediction.output
                if prediction.status == "succeeded" and output:
                    return {
                        "status": "COMPLETED",
                        "generated": [
                            {"url": output[0] if isinstance(output, list) else output}
                        ],
                    }
                elif prediction.status == "failed":
                    return {"status": "FAILED", "error": prediction.error}
            return {"status": prediction.status}
        except Exception as e:
            logger.error(f"Error getting Runway status {task_id}: {e}")
            return None

    async def wait_for_completion(
        self, task_id: str, max_attempts: int = 60, delay: int = 10
    ) -> Optional[Dict]:
        """Ожидание завершения задачи с polling"""
        for attempt in range(max_attempts):
            status = await self.get_task_status(task_id)
            if status:
                task_status = status.get("status", "").lower()
                if task_status in ["completed", "succeeded"]:
                    logger.info(f"Runway task {task_id} completed")
                    return status
                elif task_status in ["failed", "error", "canceled"]:
                    logger.error(f"Runway task {task_id} failed")
                    return status
            await asyncio.sleep(delay)
        logger.warning(f"Runway task {task_id} timeout")
        return None


runway_service = RunwayService()
