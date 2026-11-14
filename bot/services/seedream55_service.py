"""Seedream 5.5 KIE Market contract for text, edit and layered decomposition.

Official API: https://docs.kie.ai/market/seedream/5-5-text-to-image
Keep 5.0 Pro (quality=basic/high) separate: 5.5 uses size=1K/1.5K/2K.
"""
from __future__ import annotations

import logging

from bot.config import config
from bot.services.seedream_service import SeedreamService

logger = logging.getLogger(__name__)

TEXT_MODEL = "seedream/5-5-text-to-image"
EDIT_MODEL = "seedream/5-5-image-to-image"
LAYERS_MODEL = "seedream/5-5-layer-decomposition"
SIZES = frozenset({"1K", "1.5K", "2K"})
RATIOS = frozenset({"1:1", "4:3", "3:4", "16:9", "9:16", "2:3", "3:2", "21:9"})
FORMATS = frozenset({"png", "jpeg"})
BACKGROUNDS = frozenset({"auto", "transparent", "opaque"})


def _error(message: str) -> dict:
    return {"error": "invalid_input", "message": message}


def _image_settings(
    *,
    size: str,
    output_format: str,
    background: str = "auto",
    nsfw_checker: bool = False,
    layered: bool = False,
) -> dict | None:
    if size not in (SIZES | {"auto"} if layered else SIZES):
        return None
    if output_format not in FORMATS or background not in BACKGROUNDS:
        return None
    if background == "transparent" and output_format != "png":
        return None
    return {
        "size": size, "output_format": output_format,
        "nsfw_checker": bool(nsfw_checker),
        **({} if layered else {"background": background}),
    }


class Seedream55Service(SeedreamService):
    """Full three-mode adapter. Existing reference uploader uses this instance's limit."""

    MAX_REFERENCE_IMAGES = 10

    async def generate_text_to_image(
        self, prompt: str, *, aspect_ratio: str = "1:1", size: str = "2K",
        output_format: str = "png", background: str = "auto",
        nsfw_checker: bool = False, callBackUrl: str | None = None,
    ) -> dict | None:
        if not 5 <= len(str(prompt or "").strip()) <= 5000 or aspect_ratio not in RATIOS:
            return _error("Seedream 5.5: prompt must be 5–5000 characters and ratio must be supported")
        settings = _image_settings(
            size=size, output_format=output_format,
            background=background, nsfw_checker=nsfw_checker,
        )
        if settings is None:
            return _error("Seedream 5.5: invalid output settings")
        payload = {
            "model": TEXT_MODEL,
            "input": {"prompt": prompt.strip(), "aspect_ratio": aspect_ratio, **settings},
        }
        if callBackUrl:
            payload["callBackUrl"] = callBackUrl
        return await self._kie_post("/api/v1/jobs/createTask", payload)

    async def generate_image(
        self, prompt: str, image_urls: list[str], *,
        aspect_ratio: str = "auto", size: str = "2K",
        output_format: str = "png", background: str = "auto",
        nsfw_checker: bool = False, callBackUrl: str | None = None,
    ) -> dict | None:
        if not 5 <= len(str(prompt or "").strip()) <= 5000:
            return _error("Seedream 5.5: prompt must be 5–5000 characters")
        if aspect_ratio not in RATIOS | {"auto"}:
            return _error("Seedream 5.5: unsupported ratio")
        if not 1 <= len(image_urls) <= self.MAX_REFERENCE_IMAGES:
            return _error("Seedream 5.5: expected 1–10 reference images")
        settings = _image_settings(
            size=size, output_format=output_format,
            background=background, nsfw_checker=nsfw_checker,
        )
        if settings is None:
            return _error("Seedream 5.5: invalid output settings")
        urls = await self._prepare_effective_image_urls(image_urls)
        if not urls or len(urls) != len(image_urls):
            return _error("Seedream 5.5: could not prepare all reference images")
        payload = {
            "model": EDIT_MODEL,
            "input": {
                "prompt": prompt.strip(), "image_urls": urls,
                "aspect_ratio": aspect_ratio, **settings,
            },
        }
        if callBackUrl:
            payload["callBackUrl"] = callBackUrl
        return await self._kie_post("/api/v1/jobs/createTask", payload)

    async def generate_layers(
        self, image_url: str, *, prompt: str = "", size: str = "auto",
        output_format: str = "png", max_images: int = 30,
        text_recognition: bool = False, nsfw_checker: bool = False,
        callBackUrl: str | None = None,
    ) -> dict | None:
        if not image_url or not isinstance(image_url, str):
            return _error("Seedream 5.5 layers: one reference image is required")
        if len(str(prompt or "")) > 2000:
            return _error("Seedream 5.5 layers: prompt must not exceed 2000 characters")
        if type(max_images) is not int or not 2 <= max_images <= 100:
            return _error("Seedream 5.5 layers: max_images must be 2–100")
        settings = _image_settings(
            size=size, output_format=output_format, nsfw_checker=nsfw_checker,
            layered=True,
        )
        if settings is None:
            return _error("Seedream 5.5 layers: invalid output settings")
        urls = await self._prepare_effective_image_urls([image_url])
        if not urls or len(urls) != 1:
            return _error("Seedream 5.5 layers: could not prepare source image")
        payload = {
            "model": LAYERS_MODEL,
            "input": {
                "image_url": urls[0], "prompt": str(prompt or ""),
                **settings, "max_images": max_images,
                "text_recognition": bool(text_recognition),
            },
        }
        if callBackUrl:
            payload["callBackUrl"] = callBackUrl
        return await self._kie_post("/api/v1/jobs/createTask", payload)


seedream55_service = Seedream55Service(kie_key=config.KIE_AI_API_KEY)
