import asyncio
import json
import logging
import os
from typing import Dict, Optional

import aiohttp

logger = logging.getLogger(__name__)


class KieService:
    """Kie.ai API service for Nano Banana 2 and other models."""

    BASE_URL = "https://api.kie.ai/api/v1"

    def __init__(self, api_token: str = None):
        self.api_token = api_token or os.environ.get("KIE_AI_API_KEY")
        if not self.api_token:
            logger.warning("KIE_API_TOKEN not set - KieService disabled")

    async def create_task(
        self,
        model: str = "nano-banana-2",
        input_data: dict = None,
        callback_url: str = None,
    ):
        """Create generation task via POST /api/v1/jobs/createTask."""
        if not self.api_token:
            logger.error("KIE_API_TOKEN required")
            return None

        if input_data is None:
            input_data = {}

        payload = {
            "model": model,
            "input": input_data,
        }
        if callback_url:
            payload["callBackUrl"] = callback_url

        headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json",
        }

        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(
                    f"{self.BASE_URL}/jobs/createTask",
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    resp.raise_for_status()
                    result = await resp.json()
                    logger.debug(f"Kie create_task full response: {result}")
                    data = result.get("data") or {}
                    task_id = (
                        data.get("taskId") or result.get("task_id") or result.get("id")
                    )
                    if task_id:
                        logger.info(f"Kie task created: {task_id}")
                        return {"task_id": task_id, "raw": result}
                    else:
                        logger.error(f"No task_id in Kie response: {result}")
                        return None
            except Exception as e:
                logger.error(f"Kie create_task failed: {e}")
                return None

    async def get_task_status(self, task_id: str):
        """Query task status via GET /api/v1/jobs/recordInfo."""
        if not self.api_token:
            logger.error("KIE_AI_API_KEY required")
            return None

        headers = {
            "Authorization": f"Bearer {self.api_token}",
        }

        params = {"taskId": task_id}

        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(
                    f"{self.BASE_URL}/jobs/recordInfo",
                    headers=headers,
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    resp.raise_for_status()
                    result = await resp.json()
                    logger.info(
                        f"Kie task status: {task_id} = {result.get('data', {}).get('state')}"
                    )
                    return result
            except Exception as e:
                logger.error(f"Kie get_task_status failed for {task_id}: {e}")
                return None

    async def generate_nano_banana(
        self,
        prompt: str,
        image_input_uris: list[str] = None,
        aspect_ratio: str = "auto",
        resolution: str = "1K",
        output_format: str = "png",
        callback_url: str = None,
        user_id: str = None,
    ):
        """Generate Nano Banana 2 image via Kie API."""
        input_data = {
            "prompt": prompt,
            "image_input": image_input_uris or [],
            "aspect_ratio": aspect_ratio,
            "resolution": resolution,
            "output_format": output_format,
        }
        if user_id:
            input_data["user_id"] = str(user_id)

        return await self.create_task(
            model="nano-banana-2",
            input_data=input_data,
            callback_url=callback_url,
        )

    async def generate_nano_banana_pro(
        self,
        prompt: str,
        image_input_uris: list[str] = None,
        aspect_ratio: str = "1:1",
        resolution: str = "1K",
        output_format: str = "png",
        callback_url: str = None,
        user_id: str = None,
    ):
        """Generate Nano Banana Pro image via Kie API."""
        input_data = {
            "prompt": prompt,
            "image_input": image_input_uris or [],
            "aspect_ratio": aspect_ratio,
            "resolution": resolution,
            "output_format": output_format,
        }
        if user_id:
            input_data["user_id"] = str(user_id)

        return await self.create_task(
            model="nano-banana-pro",
            input_data=input_data,
            callback_url=callback_url,
        )

    async def generate_seedream45_t2i(
        self,
        prompt: str,
        aspect_ratio: str = "1:1",
        resolution: str = "1K",
        output_format: str = "png",
        callback_url: str = None,
        user_id: str = None,
    ):
        """Generate Seedream 4.5 Text-to-Image via Kie API."""
        input_data = {
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "resolution": resolution,
            "output_format": output_format,
        }
        if user_id:
            input_data["user_id"] = str(user_id)

        return await self.create_task(
            model="seedream-4.5-text-to-image",
            input_data=input_data,
            callback_url=callback_url,
        )

    async def generate_kling_motion_control(
        self,
        prompt: str,
        input_urls: list[str],
        video_urls: list[str],
        character_orientation: str = "video",
        mode: str = "720p",
        callback_url: str = None,
        user_id: str = None,
    ):
        """Generate Kling 2.6 Motion Control video via Kie API."""
        input_data = {
            "prompt": prompt,
            "input_urls": input_urls,
            "video_urls": video_urls,
            "character_orientation": character_orientation,
            "mode": mode,
        }
        if user_id:
            input_data["user_id"] = str(user_id)

        return await self.create_task(
            model="kling-2.6/motion-control",
            input_data=input_data,
            callback_url=callback_url,
        )

    async def generate_kling_3_0(
        self,
        prompt: str,
        image_urls: list[str] = None,
        sound: bool = True,
        duration: str = "5",
        aspect_ratio: str = "16:9",
        mode: str = "pro",
        multi_shots: bool = False,
        multi_prompt: list[dict] = None,
        kling_elements: list[dict] = None,
        callback_url: str = None,
        user_id: str = None,
    ):
        """Generate Kling 3.0 video via Kie API."""
        input_data = {
            "prompt": prompt,
            "sound": sound,
            "duration": duration,
            "aspect_ratio": aspect_ratio,
            "mode": mode,
            "multi_shots": multi_shots,
        }
        if image_urls:
            input_data["image_urls"] = image_urls
        if multi_prompt:
            input_data["multi_prompt"] = multi_prompt
        if kling_elements:
            input_data["kling_elements"] = kling_elements
        if user_id:
            input_data["user_id"] = str(user_id)

        return await self.create_task(
            model="kling-3.0/video",
            input_data=input_data,
            callback_url=callback_url,
        )

    async def wait_for_completion(
        self, task_id: str, max_attempts: int = 120, delay: int = 10
    ) -> Optional[Dict]:
        """Poll task status until completion."""
        for attempt in range(max_attempts):
            status = await self.get_task_status(task_id)
            if not status:
                await asyncio.sleep(delay)
                continue
            data = status.get("data", {})
            state = data.get("state", "").lower()
            if state in ["success", "completed"]:
                logger.info(f"Kie task {task_id} completed")
                return status
            elif state in ["fail", "error", "failed"]:
                logger.error(f"Kie task {task_id} failed: {data.get('failMsg')}")
                return status
            logger.debug(f"Kie task {task_id}: {state}, attempt {attempt+1}")
            await asyncio.sleep(delay)
        logger.warning(f"Kie task {task_id} timeout")
        return None

    async def generate_seedream45_edit(
        self,
        prompt: str,
        image_input_uris: list[str] = None,
        aspect_ratio: str = "1:1",
        resolution: str = "1K",
        output_format: str = "png",
        callback_url: str = None,
        user_id: str = None,
    ):
        """Generate Seedream 4.5 Edit (Image-to-Image) via Kie API."""
        input_data = {
            "prompt": prompt,
            "image_input": image_input_uris or [],
            "aspect_ratio": aspect_ratio,
            "resolution": resolution,
            "output_format": output_format,
        }
        if user_id:
            input_data["user_id"] = str(user_id)

        return await self.create_task(
            model="seedream-4.5-edit",
            input_data=input_data,
            callback_url=callback_url,
        )

    async def generate_sync(
        self,
        model: str,
        input_data: dict,
        max_wait: int = 300,
    ) -> Optional[bytes]:
        """Synchronous generation: create task + poll until done."""
        task = await self.create_task(model=model, input_data=input_data)
        if not task:
            logger.error("Failed to create Kie task")
            return None

        task_id = task["task_id"]
        logger.info(f"Polling Kie task {task_id}")

        import json

        start_time = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() - start_time < max_wait:
            status_resp = await self.get_task_status(task_id)
            if not status_resp:
                await asyncio.sleep(5)
                continue

            data = status_resp.get("data", {})
            state = data.get("state")
            logger.info(f"Kie task {task_id}: {state}")

            if state == "success":
                result_json_str = data.get("resultJson", "{}")
                try:
                    result_json = json.loads(result_json_str)
                    result_urls = result_json.get("resultUrls", [])
                    if result_urls:
                        output_url = result_urls[0]
                        async with aiohttp.ClientSession() as session:
                            async with session.get(output_url) as resp:
                                if resp.status == 200:
                                    return await resp.read()
                                else:
                                    logger.error(
                                        f"Failed to download Kie output: {resp.status}"
                                    )
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse resultJson: {e}")
                return None
            elif state in ("fail", "error"):
                logger.error(
                    f"Kie task failed: {data.get('failMsg', data.get('error'))}"
                )
                return None

            await asyncio.sleep(5)

        logger.error(f"Kie task {task_id} timeout")
        return None


# Singleton
kie_service = KieService()
