"""Kie.ai adapter for Wan 3.0 Video Prime."""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from string import Formatter
from typing import Any

from bot.config import config
from bot.services.kling_service import KlingService
from bot.services.media_input_utils import canonicalize_local_upload_url

logger = logging.getLogger(__name__)

WAN3_EDIT_TEMPLATE_SETTING = "wan3_prime_edit_prompt_template"
WAN3_EDIT_TEMPLATE_VERSION = "wan3-prime-edit-v1"
WAN3_MAX_TEMPLATE_CHARS = 4_096
DEFAULT_WAN3_EDIT_TEMPLATE = (
    "Edit Video1 according to these instructions: {instruction}\n"
    "Use Video1 as the source video. Preserve timing, scene structure, camera motion, "
    "and continuity except for the requested changes. Use additional Image/Video/Audio/"
    "File/Link references only where they are explicitly relevant."
)


def validate_wan3_edit_template(text: str) -> str:
    cleaned = str(text or "").strip()
    if not cleaned or len(cleaned) > WAN3_MAX_TEMPLATE_CHARS:
        raise ValueError(f"Wan 3.0 edit template must contain 1-{WAN3_MAX_TEMPLATE_CHARS} characters")
    try:
        fields = list(Formatter().parse(cleaned))
    except ValueError as exc:
        raise ValueError("Invalid Wan 3.0 edit template placeholders") from exc
    for _, field, spec, conversion in fields:
        if field is not None and (field != "instruction" or spec or conversion):
            raise ValueError("Only {instruction} is allowed in the Wan 3.0 edit template")
    if not any(field == "instruction" for _, field, _, _ in fields):
        raise ValueError("Wan 3.0 edit template must include {instruction}")
    if not re.search(r"\bVideo1\b", cleaned, re.IGNORECASE):
        raise ValueError("Wan 3.0 edit template must label the source as Video1")
    return cleaned


async def get_wan3_edit_template() -> str:
    from bot.database import get_bot_setting

    configured = await get_bot_setting(WAN3_EDIT_TEMPLATE_SETTING, "")
    return validate_wan3_edit_template(configured) if configured else DEFAULT_WAN3_EDIT_TEMPLATE


async def save_wan3_edit_template(text: str, *, admin_id: int) -> None:
    from bot.database import set_bot_setting

    cleaned = validate_wan3_edit_template(text)
    await set_bot_setting(WAN3_EDIT_TEMPLATE_SETTING, cleaned, updated_by_telegram_id=admin_id)


async def reset_wan3_edit_template(*, admin_id: int) -> None:
    from bot.database import set_bot_setting

    await set_bot_setting(WAN3_EDIT_TEMPLATE_SETTING, "", updated_by_telegram_id=admin_id)


class Wan3PrimeService(KlingService):
    MODEL_NAME = "wan/3-0-video-prime"
    INTERNAL_MODEL_KEY = "wan_3_prime"

    ALLOWED_RESOLUTIONS = frozenset({"480P", "720P", "1080P"})
    ALLOWED_RATIOS = frozenset({"adaptive", "16:9", "4:3", "1:1", "3:4", "9:16"})
    MIN_DURATION = 2
    MAX_DURATION = 30
    AUTO_DURATION = -1
    MAX_PROMPT_LENGTH = 20_000
    MAX_SEED = 2_147_483_647

    MAX_REFERENCE_IMAGES = 10
    MAX_REFERENCE_VIDEOS = 5
    MAX_REFERENCE_AUDIO = 5
    MAX_REFERENCE_FILES = 1
    MAX_REFERENCE_LINKS = 1
    SCENARIOS = {
        "text",
        "first_frame",
        "first_last",
        "reference",
        "edit",
        "file",
        "link",
    }
    _ROLE_RE = re.compile(r"\b(?P<kind>Image|Video|Audio)(?P<index>[1-9][0-9]*)\b", re.IGNORECASE)

    @staticmethod
    def _clean_ordered_urls(values: Iterable[str] | None, *, label: str) -> list[str]:
        if values is None:
            return []
        if isinstance(values, (str, bytes)) or not isinstance(values, Iterable):
            raise ValueError(f"Wan 3.0 {label} must be a list of URL strings")
        cleaned: list[str] = []
        for index, raw in enumerate(values, start=1):
            if not isinstance(raw, str):
                raise ValueError(f"Wan 3.0 {label} slot {index} must be a URL string")
            value = raw.strip()
            if not value:
                raise ValueError(f"Wan 3.0 {label} slot {index} is empty")
            cleaned.append(canonicalize_local_upload_url(value))
        return cleaned

    @classmethod
    def _limited_urls(
        cls,
        values: Iterable[str] | None,
        *,
        limit: int,
        label: str,
    ) -> list[str]:
        cleaned = cls._clean_ordered_urls(values, label=label)
        if len(cleaned) > limit:
            raise ValueError(f"Wan 3.0 Video Prime accepts at most {limit} {label}")
        return cleaned

    @classmethod
    def normalize_duration(cls, duration: int | str | None) -> int:
        if duration is None:
            value = 5
        elif isinstance(duration, bool):
            raise ValueError("Wan 3.0 Video Prime duration must be an integer")
        elif isinstance(duration, int):
            value = duration
        elif isinstance(duration, str) and re.fullmatch(r"-?\d+", duration.strip()):
            value = int(duration.strip())
        else:
            raise ValueError("Wan 3.0 Video Prime duration must be an integer")
        if value == cls.AUTO_DURATION:
            return value
        if not cls.MIN_DURATION <= value <= cls.MAX_DURATION:
            raise ValueError(
                "Wan 3.0 Video Prime duration must be 2-30 seconds or -1 (Auto)"
            )
        return value

    @classmethod
    def _prepare_prompt(cls, prompt: str, *, scenario: str, edit_template: str | None = None) -> tuple[str, str]:
        raw = str(prompt or "").strip()
        if len(raw) > cls.MAX_PROMPT_LENGTH:
            raise ValueError(
                f"Wan 3.0 Video Prime prompt exceeds {cls.MAX_PROMPT_LENGTH} characters"
            )
        if scenario != "edit":
            return raw, raw
        if not raw:
            raise ValueError("Wan 3.0 edit mode requires change instructions")
        instruction = raw
        template = validate_wan3_edit_template(edit_template or DEFAULT_WAN3_EDIT_TEMPLATE)
        provider_prompt = template.format(instruction=instruction)
        if len(provider_prompt) > cls.MAX_PROMPT_LENGTH:
            raise ValueError(
                f"Wan 3.0 Video Prime edit prompt exceeds {cls.MAX_PROMPT_LENGTH} characters"
            )
        return provider_prompt, raw

    @classmethod
    def _infer_scenario(
        cls,
        *,
        first_frame_url: str | None,
        last_frame_url: str | None,
        reference_image_urls: list[str],
        reference_video_urls: list[str],
        reference_audio_urls: list[str],
        reference_file_urls: list[str],
        reference_link_urls: list[str],
    ) -> str:
        first = str(first_frame_url or "").strip()
        last = str(last_frame_url or "").strip()
        if first and last:
            return "first_last"
        if first:
            return "first_frame"
        if reference_file_urls and not (
            reference_image_urls or reference_video_urls or reference_audio_urls or reference_link_urls
        ):
            return "file"
        if reference_link_urls and not (
            reference_image_urls or reference_video_urls or reference_audio_urls or reference_file_urls
        ):
            return "link"
        if (
            reference_image_urls
            or reference_video_urls
            or reference_audio_urls
            or reference_file_urls
            or reference_link_urls
        ):
            return "reference"
        return "text"

    @classmethod
    def _validate_reference_role_tags(
        cls,
        prompt: str,
        *,
        image_count: int,
        video_count: int,
        audio_count: int,
    ) -> None:
        if not prompt.strip():
            return
        max_seen = {"image": 0, "video": 0, "audio": 0}
        for match in cls._ROLE_RE.finditer(prompt):
            kind = match.group("kind").lower()
            max_seen[kind] = max(max_seen[kind], int(match.group("index")))
        limits = {"image": image_count, "video": video_count, "audio": audio_count}
        for kind, seen in max_seen.items():
            if seen > limits[kind]:
                raise ValueError(f"Prompt references {kind.title()}{seen}, but only {limits[kind]} {kind} inputs were provided")

    @classmethod
    def _validate_scenario(
        cls,
        *,
        scenario: str,
        first_frame_url: str | None,
        last_frame_url: str | None,
        reference_image_urls: list[str],
        reference_video_urls: list[str],
        reference_audio_urls: list[str],
        reference_file_urls: list[str],
        reference_link_urls: list[str],
    ) -> str:
        first = str(first_frame_url or "").strip()
        last = str(last_frame_url or "").strip()
        has_refs = bool(
            reference_image_urls
            or reference_video_urls
            or reference_audio_urls
            or reference_file_urls
            or reference_link_urls
        )
        if last and not first:
            raise ValueError("last_frame_url requires first_frame_url")
        if first and has_refs:
            raise ValueError(
                "Wan 3.0 first/last frames cannot be combined with reference_* inputs"
            )
        if reference_file_urls and reference_link_urls:
            raise ValueError("reference_file_urls and reference_link_urls are mutually exclusive")
        if scenario == "text":
            if has_refs or first or last:
                raise ValueError("Wan 3.0 text mode cannot include media inputs")
            return "text"
        if scenario == "first_frame":
            if not first or last:
                raise ValueError("Wan 3.0 first-frame mode requires exactly first_frame_url")
            return "first_frame"
        if scenario == "first_last":
            if not first or not last:
                raise ValueError("Wan 3.0 first+last-frame mode requires both frame URLs")
            return "first_last"
        if scenario == "reference":
            if not has_refs:
                raise ValueError("Wan 3.0 reference mode requires at least one reference input")
            return "reference"
        if scenario == "edit":
            if not reference_video_urls:
                raise ValueError("Wan 3.0 video editing requires Video1 as a source video")
            return "edit"
        if scenario == "file":
            if not reference_file_urls:
                raise ValueError("Wan 3.0 file mode requires reference_file_urls")
            return "file"
        if scenario == "link":
            if not reference_link_urls:
                raise ValueError("Wan 3.0 link mode requires reference_link_urls")
            return "link"
        raise ValueError(f"Unsupported Wan 3.0 scenario: {scenario}")

    async def generate_video(
        self,
        prompt: str,
        *,
        scenario: str | None = None,
        duration: int = 5,
        aspect_ratio: str = "adaptive",
        resolution: str = "1080P",
        first_frame_url: str | None = None,
        last_frame_url: str | None = None,
        reference_image_urls: list[str] | None = None,
        reference_video_urls: list[str] | None = None,
        reference_audio_urls: list[str] | None = None,
        reference_file_urls: list[str] | None = None,
        reference_link_urls: list[str] | None = None,
        audio: bool = True,
        seed: int | None = None,
        nsfw_checker: bool = False,
        callBackUrl: str | None = None,
        _prepare_only: bool = False,
    ) -> dict[str, Any]:
        if not self.kie_key and not _prepare_only:
            return {"success": False, "error": "KIE_AI_API_KEY is not configured"}
        explicit_scenario = scenario is not None
        normalized_scenario = str(scenario).strip().lower() if explicit_scenario else ""
        if explicit_scenario and normalized_scenario not in self.SCENARIOS:
            return {"success": False, "error": f"Unsupported Wan 3.0 scenario: {scenario}"}
        if not isinstance(audio, bool):
            return {"success": False, "error": "Wan 3.0 audio must be a boolean"}
        if not isinstance(nsfw_checker, bool):
            return {"success": False, "error": "Wan 3.0 nsfw_checker must be a boolean"}

        try:
            normalized_duration = self.normalize_duration(duration)
            image_urls = self._limited_urls(
                reference_image_urls,
                limit=self.MAX_REFERENCE_IMAGES,
                label="image references",
            )
            video_urls = self._limited_urls(
                reference_video_urls,
                limit=self.MAX_REFERENCE_VIDEOS,
                label="video references",
            )
            audio_urls = self._limited_urls(
                reference_audio_urls,
                limit=self.MAX_REFERENCE_AUDIO,
                label="audio references",
            )
            file_urls = self._limited_urls(
                reference_file_urls,
                limit=self.MAX_REFERENCE_FILES,
                label="file references",
            )
            link_urls = self._limited_urls(
                reference_link_urls,
                limit=self.MAX_REFERENCE_LINKS,
                label="link references",
            )
        except ValueError as exc:
            return {"success": False, "error": str(exc)}

        normalized_resolution = str(resolution or "1080P").strip().upper()
        if normalized_resolution not in self.ALLOWED_RESOLUTIONS:
            return {
                "success": False,
                "error": f"Unsupported Wan 3.0 resolution: {normalized_resolution}",
            }

        normalized_ratio = str(aspect_ratio or "adaptive").strip()
        if normalized_ratio.lower() == "adaptive":
            normalized_ratio = "adaptive"
        if normalized_ratio not in self.ALLOWED_RATIOS:
            return {
                "success": False,
                "error": f"Unsupported Wan 3.0 aspect ratio: {normalized_ratio}",
            }

        normalized_seed: int | None = None
        if seed is not None and seed != "":
            if isinstance(seed, bool):
                return {"success": False, "error": "Wan 3.0 seed must be an integer"}
            if isinstance(seed, int):
                normalized_seed = seed
            elif isinstance(seed, str) and re.fullmatch(r"\d+", seed.strip()):
                normalized_seed = int(seed.strip())
            else:
                return {"success": False, "error": "Wan 3.0 seed must be an integer"}
            if not 0 <= normalized_seed <= self.MAX_SEED:
                return {
                    "success": False,
                    "error": f"Wan 3.0 seed must be 0-{self.MAX_SEED}",
                }

        first_frame = str(first_frame_url or "").strip() or None
        last_frame = str(last_frame_url or "").strip() or None
        if first_frame:
            first_frame = canonicalize_local_upload_url(first_frame)
        if last_frame:
            last_frame = canonicalize_local_upload_url(last_frame)

        try:
            if not explicit_scenario:
                normalized_scenario = self._infer_scenario(
                    first_frame_url=first_frame,
                    last_frame_url=last_frame,
                    reference_image_urls=image_urls,
                    reference_video_urls=video_urls,
                    reference_audio_urls=audio_urls,
                    reference_file_urls=file_urls,
                    reference_link_urls=link_urls,
                )
            edit_template = await get_wan3_edit_template() if normalized_scenario == "edit" else None
            provider_prompt, raw_prompt = self._prepare_prompt(
                prompt,
                scenario=normalized_scenario,
                edit_template=edit_template,
            )
            if normalized_scenario == "text" and not provider_prompt:
                raise ValueError("Wan 3.0 text mode requires a prompt")
            resolved_scenario = self._validate_scenario(
                scenario=normalized_scenario,
                first_frame_url=first_frame,
                last_frame_url=last_frame,
                reference_image_urls=image_urls,
                reference_video_urls=video_urls,
                reference_audio_urls=audio_urls,
                reference_file_urls=file_urls,
                reference_link_urls=link_urls,
            )
            self._validate_reference_role_tags(
                provider_prompt,
                image_count=len(image_urls),
                video_count=len(video_urls),
                audio_count=len(audio_urls),
            )
        except ValueError as exc:
            return {"success": False, "error": str(exc)}

        input_data: dict[str, Any] = {
            "prompt": provider_prompt,
            "resolution": normalized_resolution,
            "aspect_ratio": normalized_ratio,
            "duration": normalized_duration,
            "audio": audio,
            "nsfw_checker": nsfw_checker,
        }
        if first_frame:
            input_data["first_frame_url"] = first_frame
        if last_frame:
            input_data["last_frame_url"] = last_frame
        if image_urls:
            input_data["reference_image_urls"] = image_urls
        if video_urls:
            input_data["reference_video_urls"] = video_urls
        if audio_urls:
            input_data["reference_audio_urls"] = audio_urls
        if file_urls:
            input_data["reference_file_urls"] = file_urls
        if link_urls:
            input_data["reference_link_urls"] = link_urls
        if normalized_seed is not None:
            input_data["seed"] = normalized_seed

        payload: dict[str, Any] = {
            "model": self.MODEL_NAME,
            "input": input_data,
        }
        callback_url = str(callBackUrl or "").strip()
        if callback_url:
            payload["callBackUrl"] = callback_url

        if _prepare_only:
            return {"success": True, "payload": payload, "scenario": resolved_scenario}

        logger.info(
            "Wan 3.0 Video Prime request: scenario=%s duration=%s ratio=%s resolution=%s refs(image=%s,video=%s,audio=%s,file=%s,link=%s) audio=%s seed=%s nsfw_checker=%s callback=%s",
            resolved_scenario,
            normalized_duration,
            normalized_ratio,
            normalized_resolution,
            len(image_urls),
            len(video_urls),
            len(audio_urls),
            len(file_urls),
            len(link_urls),
            audio,
            normalized_seed is not None,
            nsfw_checker,
            "yes" if callback_url else "polling-only",
        )
        result = await self._kie_post("/api/v1/jobs/createTask", payload)
        if isinstance(result, dict):
            result.setdefault("success", bool(result.get("task_id")))
            result.setdefault("scenario", resolved_scenario)
            result.setdefault("provider_model", self.MODEL_NAME)
            result.setdefault("duration", normalized_duration)
            result.setdefault("aspect_ratio", normalized_ratio)
            result.setdefault("resolution", normalized_resolution)
            result.setdefault("raw_prompt", raw_prompt)
            if resolved_scenario == "edit":
                result.setdefault("edit_prompt_template_version", WAN3_EDIT_TEMPLATE_VERSION)
        return result


    async def prepare_request(self, **kwargs: Any) -> dict[str, Any]:
        """Build the exact wire input without credentials or a provider request."""
        result = await self.generate_video(**kwargs, _prepare_only=True)
        if result.get("success") is not True:
            raise ValueError(str(result.get("error") or "Invalid Wan request"))
        return result["payload"]["input"]

    async def submit_prepared(self, prepared_input: dict[str, Any], *, callback_url: str | None) -> dict[str, Any]:
        """Submit a server-frozen validated input; never compose the edit prompt twice."""
        from copy import deepcopy

        if not self.kie_key:
            return {"success": False, "error": "api_error", "message": "Provider is not configured"}
        payload = {"model": self.MODEL_NAME, "input": deepcopy(prepared_input)}
        if callback_url:
            payload["callBackUrl"] = callback_url
        logger.info("Wan3 prepared request: model=%s duration=%s resolution=%s",
                    self.MODEL_NAME, prepared_input.get("duration"), prepared_input.get("resolution"))
        return await self._kie_post(self.CREATE_TASK_ENDPOINT, payload)


wan3_prime_service = Wan3PrimeService(kie_key=config.KIE_AI_API_KEY)
