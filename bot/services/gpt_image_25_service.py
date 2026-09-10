from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Mapping, Sequence
from typing import Any, ClassVar
from urllib.parse import urlparse

from bot.config import config
from bot.services.kling_service import KlingService

logger = logging.getLogger(__name__)


class GPTImage25Service(KlingService):
    """KIE Market client for GPT Image 2.5 Flare and Sunburst.

    KIE exposes separate text-to-image and image-to-image model ids. The
    caller selects only the quality/speed variant; the service chooses the
    correct provider model from whether reference images are present.
    """

    CREATE_ENDPOINT = "/api/v1/jobs/createTask"
    RECORD_ENDPOINT = "/api/v1/jobs/recordInfo"

    VARIANTS: ClassVar[set[str]] = {"flare", "sunburst"}
    MODEL_IDS: ClassVar[dict[tuple[str, bool], str]] = {
        ("flare", False): "gpt-image-2-5-flare-text-to-image",
        ("flare", True): "gpt-image-2-5-flare-image-to-image",
        ("sunburst", False): "gpt-image-2-5-sunburst-text-to-image",
        ("sunburst", True): "gpt-image-2-5-sunburst-image-to-image",
    }
    ASPECT_RATIOS: ClassVar[set[str]] = {
        "auto",
        "1:1",
        "3:2",
        "2:3",
        "16:9",
        "9:16",
        "4:3",
        "3:4",
        "21:9",
        "27:16",
        "16:27",
        "9:8",
        "8:9",
    }
    RESOLUTIONS: ClassVar[set[str]] = {"1K", "2K", "4K"}
    MAX_PROMPT_CHARS = 20_000
    MAX_INPUT_IMAGES = 16
    TERMINAL_SUCCESS: ClassVar[set[str]] = {"success", "completed"}
    TERMINAL_FAILURE: ClassVar[set[str]] = {"fail", "failed", "error", "cancelled", "canceled"}

    @classmethod
    def model_id(cls, variant: str, *, has_references: bool) -> str:
        normalized = str(variant or "").strip().lower()
        if normalized not in cls.VARIANTS:
            raise ValueError(f"Unsupported GPT Image 2.5 variant: {variant}")
        return cls.MODEL_IDS[(normalized, bool(has_references))]

    @staticmethod
    def _public_image_urls(input_urls: Sequence[str] | None) -> list[str]:
        urls: list[str] = []
        seen: set[str] = set()
        for raw in input_urls or []:
            url = str(raw or "").strip()
            if not url or url in seen:
                continue
            parsed = urlparse(url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError("GPT Image 2.5 references must be public HTTP(S) URLs")
            seen.add(url)
            urls.append(url)
        return urls

    @classmethod
    def build_payload(
        cls,
        *,
        prompt: str,
        variant: str = "flare",
        input_urls: Sequence[str] | None = None,
        aspect_ratio: str = "auto",
        resolution: str = "1K",
        callback_url: str | None = None,
    ) -> dict[str, Any]:
        prompt_text = str(prompt or "").strip()
        if not prompt_text:
            raise ValueError("GPT Image 2.5 prompt is required")
        if len(prompt_text) > cls.MAX_PROMPT_CHARS:
            raise ValueError(
                f"GPT Image 2.5 prompt exceeds {cls.MAX_PROMPT_CHARS} characters"
            )

        ratio = str(aspect_ratio or "auto").strip()
        if ratio not in cls.ASPECT_RATIOS:
            raise ValueError(f"Unsupported GPT Image 2.5 aspect ratio: {ratio}")

        normalized_resolution = str(resolution or "1K").strip().upper()
        if normalized_resolution not in cls.RESOLUTIONS:
            raise ValueError(
                f"Unsupported GPT Image 2.5 resolution: {normalized_resolution}"
            )

        references = cls._public_image_urls(input_urls)
        if len(references) > cls.MAX_INPUT_IMAGES:
            raise ValueError(
                f"GPT Image 2.5 accepts at most {cls.MAX_INPUT_IMAGES} reference images"
            )

        model = cls.model_id(variant, has_references=bool(references))
        input_data: dict[str, Any] = {
            "prompt": prompt_text,
            "aspect_ratio": ratio,
            "resolution": normalized_resolution,
        }
        if references:
            input_data["input_urls"] = references

        payload: dict[str, Any] = {"model": model, "input": input_data}
        callback = str(callback_url or "").strip()
        if callback:
            payload["callBackUrl"] = callback
        return payload

    async def generate(
        self,
        *,
        prompt: str,
        variant: str = "flare",
        input_urls: Sequence[str] | None = None,
        aspect_ratio: str = "auto",
        resolution: str = "1K",
        callback_url: str | None = None,
    ) -> dict[str, Any]:
        payload = self.build_payload(
            prompt=prompt,
            variant=variant,
            input_urls=input_urls,
            aspect_ratio=aspect_ratio,
            resolution=resolution,
            callback_url=callback_url,
        )
        result = await self._kie_post(self.CREATE_ENDPOINT, payload)
        if isinstance(result, dict) and result.get("task_id"):
            result.setdefault("provider", "kie")
            result["provider_model"] = payload["model"]
        return result

    @staticmethod
    def _parse_result_json(value: Any) -> dict[str, Any]:
        if isinstance(value, Mapping):
            return dict(value)
        if isinstance(value, str) and value.strip():
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                return {}
            return dict(parsed) if isinstance(parsed, Mapping) else {}
        return {}

    @classmethod
    def _result_urls(cls, task_data: Mapping[str, Any]) -> list[str]:
        candidates: list[Any] = []
        result_json = cls._parse_result_json(
            task_data.get("resultJson") or task_data.get("result_json")
        )
        candidates.extend(
            [
                result_json.get("resultUrls"),
                result_json.get("result_urls"),
                result_json.get("urls"),
                result_json.get("images"),
                task_data.get("resultUrls"),
                task_data.get("result_urls"),
                task_data.get("output"),
            ]
        )

        urls: list[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            if isinstance(candidate, str):
                items: Sequence[Any] = [candidate]
            elif isinstance(candidate, Sequence) and not isinstance(
                candidate, (bytes, bytearray, str)
            ):
                items = candidate
            else:
                continue
            for item in items:
                if isinstance(item, Mapping):
                    raw = item.get("url") or item.get("image_url")
                else:
                    raw = item
                url = str(raw or "").strip()
                if url.startswith(("https://", "http://")) and url not in seen:
                    seen.add(url)
                    urls.append(url)
        return urls

    async def get_task_record(self, task_id: str) -> dict[str, Any]:
        normalized_task_id = str(task_id or "").strip()
        if not normalized_task_id:
            raise ValueError("GPT Image 2.5 task id is required")

        response = await self._kie_get(
            self.RECORD_ENDPOINT,
            {"taskId": normalized_task_id},
        )
        if not isinstance(response, Mapping):
            return {
                "task_id": normalized_task_id,
                "state": "unknown",
                "result_urls": [],
                "error": "KIE task status is temporarily unavailable",
                "raw": response,
            }

        raw_data = response.get("data")
        task_data = raw_data if isinstance(raw_data, Mapping) else {}
        state = str(
            task_data.get("state")
            or task_data.get("status")
            or response.get("state")
            or "unknown"
        ).strip().lower()
        return {
            "task_id": str(task_data.get("taskId") or normalized_task_id),
            "model": str(task_data.get("model") or ""),
            "state": state,
            "progress": task_data.get("progress"),
            "result_urls": self._result_urls(task_data),
            "error_code": str(
                task_data.get("failCode")
                or task_data.get("errorCode")
                or ""
            ),
            "error": str(
                task_data.get("failMsg")
                or task_data.get("errorMessage")
                or ""
            ),
            "credits_consumed": task_data.get("creditsConsumed"),
            "raw": dict(response),
        }

    async def wait_for_result(
        self,
        task_id: str,
        *,
        timeout_seconds: float = 900.0,
    ) -> dict[str, Any]:
        """Poll the unified KIE task endpoint with bounded exponential backoff."""
        deadline = asyncio.get_running_loop().time() + max(1.0, timeout_seconds)
        delays = (3.0, 5.0, 8.0, 12.0, 15.0)
        attempt = 0
        last_record: dict[str, Any] = {
            "task_id": task_id,
            "state": "unknown",
            "result_urls": [],
        }

        while True:
            record = await self.get_task_record(task_id)
            last_record = record
            state = str(record.get("state") or "unknown").lower()
            if state in self.TERMINAL_SUCCESS | self.TERMINAL_FAILURE:
                return record
            if asyncio.get_running_loop().time() >= deadline:
                return {
                    **last_record,
                    "state": "timeout",
                    "error": "GPT Image 2.5 task did not finish within the test timeout",
                }
            delay = delays[min(attempt, len(delays) - 1)]
            attempt += 1
            await asyncio.sleep(delay)


gpt_image_25_service = GPTImage25Service(kie_key=config.KIE_AI_API_KEY)
