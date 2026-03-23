"""
RunwayML Gen-4.5 Service via Replicate API

Model: runwayml/gen-4.5
Docs: runway.md
"""

import asyncio
import base64
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
        # Initialize a dedicated Replicate client instance so we don't depend
        # on module-level global state. This makes behavior deterministic and
        # easier to mock in tests.
        try:
            if self.api_token:
                self.client = replicate.Client(api_token=self.api_token)
            else:
                # If no token provided, create default client which will
                # read from environment variables if available.
                self.client = replicate.Client()
        except Exception:
            # Fallback to module-level usage if client construction fails.
            # Keep a reference for backwards compatibility.
            logger.exception(
                "Failed to initialize Replicate client, falling back to module-level client"
            )
            self.client = None

    async def generate_video(
        self,
        prompt: str,
        duration: int = 5,
        aspect_ratio: str = "16:9",
        image_url: Optional[str] = None,
        reference_image_urls: Optional[List[str]] = None,
        reference_images: Optional[List[bytes]] = None,
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
        refs_combined: List[Any] = []
        if reference_images:
            refs_combined.extend(reference_images)
        if reference_image_urls:
            refs_combined.extend(reference_image_urls)

        if not image_url and refs_combined:
            # If the first ref is bytes, convert to data URI for the 'image' field
            first = refs_combined[0]
            if isinstance(first, (bytes, bytearray)):
                image_url = (
                    f"data:image/png;base64,{base64.b64encode(first).decode('utf-8')}"
                )
            else:
                image_url = first

        if image_url:
            input_data["image"] = image_url

        # If reference images provided, build elements to help preserve
        # identity/face consistency. Convert any bytes to data URIs so the
        # Replicate input contains strings only.
        if refs_combined:

            def _maybe_data_uri(v):
                if isinstance(v, (bytes, bytearray)):
                    return (
                        f"data:image/png;base64,{base64.b64encode(v).decode('utf-8')}"
                    )
                return v

            elements = []
            for ref in refs_combined[:4]:
                r = _maybe_data_uri(ref)
                elements.append({"reference_image_urls": [r], "frontal_image_url": r})
            input_data["elements"] = elements
        if seed:
            input_data["seed"] = seed

        # Best-practice: retry transient errors with exponential backoff,
        # and enforce a reasonable timeout on the blocking call.
        max_retries = 3
        base_delay = 1.0
        # Build a callable that will call predictions.create on whichever client
        # object is available (self.client or the replicate module). This makes it
        # easier to monkeypatch in tests by setting replicate.Client to return a
        # fake client instance.
        def _make_create_callable():
            if self.client:
                return lambda: self.client.predictions.create(
                    model=self.MODEL_VERSION,
                    input=input_data,
                    webhook=webhook_url,
                    webhook_events_filter=["completed"] if webhook_url else None,
                )
            else:
                return lambda: replicate.predictions.create(
                    model=self.MODEL_VERSION,
                    input=input_data,
                    webhook=webhook_url,
                    webhook_events_filter=["completed"] if webhook_url else None,
                )

        # If no webhook_url supplied, prefer the dedicated replicate webhook
        # endpoint configured in settings so Replicate callbacks arrive at
        # /webhook/replicate instead of the generic /webhook/kling.
        if not webhook_url and config.WEBHOOK_HOST:
            webhook_url = config.replicate_notification_url

        create_callable = _make_create_callable()

        last_exc: Optional[Exception] = None
        for attempt in range(1, max_retries + 1):
            try:
                # Protect the blocking call with asyncio.wait_for to avoid hangs
                prediction = await asyncio.wait_for(
                    asyncio.get_event_loop().run_in_executor(None, create_callable),
                    timeout=60,
                )
                logger.info(f"Runway prediction created: {prediction.id}")
                return {"task_id": prediction.id, "status": prediction.status}

            except asyncio.TimeoutError as te:
                last_exc = te
                logger.warning(
                    f"Runway prediction create timed out (attempt {attempt}/{max_retries})"
                )
            except Exception as e:
                # For replicate exceptions we could inspect type/message to
                # decide whether to retry or not. For now: retry on any
                # exception up to max_retries, treating as transient.
                last_exc = e
                logger.warning(
                    f"Runway API call failed on attempt {attempt}/{max_retries}: {e}"
                )

            # Backoff before next attempt (jittered)
            if attempt < max_retries:
                delay = base_delay * (2 ** (attempt - 1))
                # add small jitter
                await asyncio.sleep(delay + (0.1 * attempt))

        # If we get here all attempts failed
        logger.error(f"Runway API error after {max_retries} attempts: {last_exc}")
        return {"error": "api_error", "message": str(last_exc)}

    async def get_task_status(self, task_id: str) -> Optional[Dict]:
        """Получить статус предсказания"""
        try:
            get_fn = (
                lambda: self.client.predictions.get(task_id)
                if self.client
                else lambda: replicate.predictions.get(task_id)
            )
            prediction = await asyncio.get_event_loop().run_in_executor(None, get_fn)
            if prediction.status in ["succeeded", "failed", "canceled"]:
                output = getattr(prediction, "output", None)
                # Normalize output to a list of URLs (strings).
                urls: List[str] = []
                if prediction.status == "succeeded" and output:
                    try:
                        outputs = output if isinstance(output, list) else [output]
                        for o in outputs:
                            # FileOutput objects from replicate have .url attribute
                            if hasattr(o, "url"):
                                urls.append(getattr(o, "url"))
                            elif isinstance(o, str):
                                urls.append(o)
                            else:
                                # Last resort: string representation
                                urls.append(str(o))
                    except Exception:
                        logger.exception("Failed to parse prediction.output")

                    # Filter out empty/None entries
                    urls = [u for u in urls if u]
                    if urls:
                        logger.info(
                            f"Runway prediction {task_id} succeeded, urls: {urls}"
                        )
                        return {
                            "status": "COMPLETED",
                            "generated": [{"url": u} for u in urls],
                        }
                    else:
                        logger.warning(
                            f"Runway prediction {task_id} succeeded but no URLs found in output: {output}"
                        )
                        return {"status": "COMPLETED", "generated": []}
                elif prediction.status == "failed":
                    # Try to provide useful error information
                    err = getattr(prediction, "error", None) or getattr(
                        prediction, "logs", None
                    )
                    return {"status": "FAILED", "error": err}
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
