"""
Kei Kling 3.0 API wrapper (100% Kie.ai migration)
"""

import logging
from typing import Any, Dict, List, Optional

from bot.services.kie_service import kie_service

logger = logging.getLogger(__name__)


class KlingService:
    """100% Kei Kling 3.0 wrapper - proxies to kie_service"""

    @classmethod
    async def generate_video_generation(
        cls,
        prompt: str,
        mode: str = "std",
        duration: int = 5,
        aspect_ratio: str = "16:9",
        image_url: Optional[str] = None,
        image_tail_url: Optional[str] = None,
        enable_audio: bool = False,
        multi_shots: bool = False,
        multi_prompt: Optional[List[Dict[str, Any]]] = None,
        kling_elements: Optional[List[Dict[str, Any]]] = None,
        callback_url: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> Optional[Dict]:
        image_urls = [image_url] if image_url else []
        if image_tail_url:
            image_urls.append(image_tail_url)
        input_data = {
            "prompt": prompt,
            "sound": enable_audio,
            "duration": str(duration),
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
            input_data["user_id"] = user_id
        return await kie_service.generate_kling_3_0(
            **input_data, callback_url=callback_url
        )

        image_urls = [image_url] if image_url else []
        if image_tail_url:
            image_urls.append(image_tail_url)
        input_data = {
            "prompt": prompt,
            "sound": enable_audio,
            "duration": str(duration),
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
        return await kie_service.generate_kling_3_0(
            **input_data, callback_url=callback_url
        )

    @classmethod
    async def generate_motion_control(
        cls,
        prompt: str = "",
        input_urls: List[str] = None,
        video_urls: List[str] = None,
        character_orientation: str = "video",
        mode: str = "720p",
        callback_url: Optional[str] = None,
        user_id: Optional[int] = None,
    ) -> Optional[Dict]:
        return await kie_service.generate_kling_motion_control(
            prompt=prompt,
            input_urls=input_urls or [],
            video_urls=video_urls or [],
            character_orientation=character_orientation,
            mode=mode,
            callback_url=callback_url,
            user_id=user_id,
        )

    @classmethod
    async def get_task_status(cls, task_id: str) -> Optional[Dict]:
        return await kie_service.get_task_status(task_id)

    @classmethod
    async def wait_for_completion(
        cls, task_id: str, max_attempts: int = 120, delay: int = 10
    ) -> Optional[Dict]:
        return await kie_service.wait_for_completion(task_id, max_attempts, delay)

    @classmethod
    def _elements_to_kling_elements(
        cls, elements: Optional[List[Dict]]
    ) -> Optional[List[Dict]]:
        if not elements:
            return None
        kling_elements = []
        for idx, el in enumerate(elements[:3]):
            urls = list(
                set(
                    el.get("reference_image_urls", [])
                    + [el.get("frontal_image_url") or ""]
                )
            )
            urls = [u for u in urls if u][:4]
            if len(urls) >= 2:
                kling_elements.append(
                    {
                        "name": f"element_{idx}",
                        "description": el.get("description", f"element {idx}"),
                        "element_input_urls": urls,
                    }
                )
        return kling_elements if kling_elements else None

    @classmethod
    async def generate_video(
        cls,
        prompt: str,
        model: str = "v3_std",
        duration: int = 5,
        aspect_ratio: str = "16:9",
        webhook_url: Optional[str] = None,
        image_url: Optional[str] = None,
        video_url: Optional[str] = None,
        end_image_url: Optional[str] = None,
        elements: Optional[List[Dict]] = None,
        generate_audio: bool = True,
        multi_shots: Optional[List[Dict[str, Any]]] = None,
    ) -> Optional[Dict]:
        kling_elements = cls._elements_to_kling_elements(elements)
        if "motion" in model.lower():
            return await cls.generate_motion_control(
                prompt=prompt,
                input_urls=[image_url] if image_url else [],
                video_urls=[video_url] if video_url else [],
                callback_url=webhook_url,
            )
        else:
            mode = "pro" if "pro" in model.lower() else "std"
            return await cls.generate_video_generation(
                prompt=prompt,
                mode=mode,
                duration=duration,
                aspect_ratio=aspect_ratio,
                image_url=image_url,
                image_tail_url=end_image_url,
                enable_audio=generate_audio,
                multi_shots=bool(multi_shots),
                multi_prompt=multi_shots,
                kling_elements=kling_elements,
                callback_url=webhook_url,
            )


kling_service = KlingService()
