"""Neironych native WAN 3.0 contract for the restricted Telegram admin test lab.

The public WAN 3.0 generation/lifecycle stays on its configured KIE route.
This adapter only builds Neironych /v1/videos/generations requests and reuses
the existing bounded HTTP, idempotency, polling and content transport.
"""
from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlsplit

from bot.services.neironych_seedance_admin_service import NeironychSeedanceAdminService


class NeironychWan3AdminService(NeironychSeedanceAdminService):
    MODEL = "wan-3"
    MODES = frozenset({"text", "reference", "frames", "edit"})
    RESOLUTIONS = ("480p", "720p", "1080p")
    RATIOS = ("adaptive", "16:9", "9:16", "1:1", "4:3", "3:4", "21:9")
    MAX_REFERENCE_COUNTS = {"image": 10, "video": 5, "audio": 5}
    MAX_REFERENCES = 20
    MAX_PROMPT_CHARS = 20_000
    MAX_SEED = 4_294_967_295

    async def list_enabled_wan_models(self) -> set[str]:
        _status, data = await self._request_json(
            method="GET", path="/v1/models", retry=True,
        )
        items = data.get("data")
        if not isinstance(items, list):
            raise ValueError("Neironych model catalog has no data array")
        return {self.MODEL for row in items if isinstance(row, dict) and row.get("id") == self.MODEL}

    @staticmethod
    def _urls(values: list[str] | None, *, field: str, maximum: int) -> list[str]:
        if values is None:
            return []
        if not isinstance(values, list) or len(values) > maximum:
            raise ValueError(f"{field}: maximum {maximum} references")
        result = []
        for value in values:
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{field} requires HTTPS media URLs")
            value = value.strip()
            parts = urlsplit(value)
            if parts.scheme != "https" or not parts.hostname or parts.username or parts.password:
                raise ValueError(f"{field} requires HTTPS media URLs without credentials")
            result.append(value)
        return result

    @classmethod
    def build_payload(
        cls,
        *,
        mode: str,
        prompt: str,
        duration: int,
        resolution: str,
        aspect_ratio: str,
        generate_audio: bool = True,
        seed: int | None = None,
        reference_images: list[str] | None = None,
        reference_videos: list[str] | None = None,
        reference_audios: list[str] | None = None,
        start_image: str = "",
        end_image: str = "",
    ) -> dict[str, Any]:
        if mode not in cls.MODES:
            raise ValueError("unsupported WAN 3.0 mode")
        prompt = str(prompt or "").strip()
        if not prompt or len(prompt) > cls.MAX_PROMPT_CHARS:
            raise ValueError(f"prompt is required (max {cls.MAX_PROMPT_CHARS} chars)")
        if resolution not in cls.RESOLUTIONS:
            raise ValueError("unsupported WAN 3.0 resolution")
        if aspect_ratio not in cls.RATIOS:
            raise ValueError("unsupported WAN 3.0 aspect_ratio")
        if isinstance(duration, bool) or not isinstance(duration, int) or not 2 <= duration <= 30:
            raise ValueError("WAN 3.0 duration must be 2-30 seconds")
        if not isinstance(generate_audio, bool):
            raise ValueError("generate_audio must be a boolean")
        if seed is not None and (
            isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= cls.MAX_SEED
        ):
            raise ValueError("WAN 3.0 seed is out of range")

        images = cls._urls(reference_images, field="reference_images", maximum=10)
        videos = cls._urls(reference_videos, field="reference_videos", maximum=5)
        audios = cls._urls(reference_audios, field="reference_audios", maximum=5)
        start = cls._urls([start_image] if start_image else None, field="start_image", maximum=1)
        end = cls._urls([end_image] if end_image else None, field="end_image", maximum=1)
        if len(images) + len(videos) + len(audios) > cls.MAX_REFERENCES:
            raise ValueError("WAN 3.0 reference_limit_exceeded")

        refs = bool(images or videos or audios)
        if mode == "text" and (refs or start or end):
            raise ValueError("text mode cannot include media references")
        if mode == "reference" and (not refs or start or end):
            raise ValueError("reference mode requires references without frames")
        if mode == "frames" and (refs or not start or (end and not start)):
            raise ValueError("frames mode requires start_image and excludes references")
        if mode == "edit" and (not videos or start or end):
            raise ValueError("edit mode requires source video and excludes frames")

        cls._validate_prompt_references(
            prompt,
            images=len(images) if mode in {"reference", "edit"} else 0,
            videos=len(videos) if mode in {"reference", "edit"} else 0,
            audios=len(audios) if mode in {"reference", "edit"} else 0,
        )

        payload: dict[str, Any] = {
            "model": cls.MODEL,
            "prompt": prompt,
            "resolution": resolution,
            "generate_audio": generate_audio,
        }
        if mode != "edit":
            payload.update(duration=duration, aspect_ratio=aspect_ratio)
        if mode in {"reference", "edit"}:
            if images:
                payload["reference_images"] = [{"url": u} for u in images]
            if videos:
                payload["reference_videos"] = [{"url": u} for u in videos]
            if audios:
                payload["reference_audios"] = [{"url": u} for u in audios]
            payload["omni_reference_task_type"] = mode
        elif mode == "frames":
            payload["start_image"] = {"url": start[0]}
            if end:
                payload["end_image"] = {"url": end[0]}
        if seed is not None:
            payload["seed"] = seed
        if len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()) >= 1024 * 1024:
            raise ValueError("WAN 3.0 payload is too large")
        return payload


neironych_wan3_admin_service = NeironychWan3AdminService()
