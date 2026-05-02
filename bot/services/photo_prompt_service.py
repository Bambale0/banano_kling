"""Photo to prompt service via Kie GPT 5.4 Responses API with Claude Haiku fallback."""

import asyncio
import json
import logging
from typing import Any, Dict, Optional

import aiohttp

from bot.config import config

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """
You are a professional photo-to-prompt analyst for AI image generation.

Your task:
Analyze the reference image and create a precise generation prompt that can recreate a visually similar image.

Strict rules:
- Do not identify any person.
- Do not guess names, age, ethnicity, nationality, or private attributes.
- Describe only visible visual features.
- Preserve subject identity visually through neutral descriptions: face shape, hair, pose, clothing, proportions, accessories, but do not claim who the person is.
- If the image contains a person, focus on: composition, pose, expression, hairstyle, clothing, lighting, background, camera angle, lens feel, color grading, mood.
- If the image contains a product/object, focus on: object shape, material, colors, surface texture, lighting, camera angle, environment, composition.
- The main prompt must be in English and optimized for image generation models.
- Return only valid JSON. No markdown. No explanation.

JSON schema:
{
  "prompt_en": "Detailed English image generation prompt",
  "prompt_ru": "Natural Russian version for the user",
  "negative_prompt": "Common defects to avoid",
  "model_hint": "Short Russian recommendation which model to use",
  "key_details": ["detail 1", "detail 2", "detail 3"]
}
""".strip()


def _extract_output_text(data: Dict[str, Any]) -> str:
    parts: list[str] = []

    for item in data.get("output", []) or []:
        if isinstance(item, dict) and item.get("type") == "message":
            for content in item.get("content", []) or []:
                if isinstance(content, dict):
                    text = content.get("text")
                    if text:
                        parts.append(str(text))

    if parts:
        return "\n".join(parts).strip()

    if isinstance(data.get("output_text"), str):
        return data["output_text"].strip()
    if isinstance(data.get("text"), str):
        return data["text"].strip()

    return json.dumps(data, ensure_ascii=False)


def _extract_claude_text(data: Dict[str, Any]) -> str:
    parts: list[str] = []
    for block in data.get("content", []) or []:
        if isinstance(block, dict) and block.get("type") == "text":
            text = block.get("text", "")
            if text:
                parts.append(str(text))
    return "\n".join(parts).strip()


def _parse_json_object(raw_text: str) -> Dict[str, Any]:
    raw_text = (raw_text or "").strip()

    try:
        parsed = json.loads(raw_text)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    start = raw_text.find("{")
    end = raw_text.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            parsed = json.loads(raw_text[start : end + 1])
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass

    return {
        "prompt_en": raw_text,
        "prompt_ru": "Не удалось разобрать структурированный ответ. Используйте английский prompt выше.",
        "negative_prompt": "blurry, low quality, distorted face, bad anatomy, extra fingers, bad hands, watermark, text, logo, overexposed, underexposed, plastic skin, unnatural eyes, asymmetry",
        "model_hint": "Для похожей генерации попробуйте Nano Banana Pro. Для редактирования по исходнику — Seedream 4.5 Edit.",
        "key_details": [],
    }


def _build_result(parsed: Dict[str, Any]) -> Dict[str, Any]:
    prompt_en = str(parsed.get("prompt_en") or "").strip()
    prompt_ru = str(parsed.get("prompt_ru") or "").strip()
    negative_prompt = str(parsed.get("negative_prompt") or "").strip()
    model_hint = str(parsed.get("model_hint") or "").strip()
    key_details = parsed.get("key_details") or []

    if not prompt_en:
        raise RuntimeError("prompt_en пустой")

    if not negative_prompt:
        negative_prompt = (
            "blurry, low quality, distorted face, bad anatomy, extra fingers, "
            "bad hands, watermark, text, logo, overexposed, underexposed, "
            "plastic skin, unnatural eyes, asymmetry"
        )

    if not model_hint:
        model_hint = (
            "Nano Banana Pro — для похожей генерации. "
            "Seedream 4.5 Edit — для редактирования по исходнику."
        )

    return {
        "prompt_en": prompt_en,
        "prompt_ru": prompt_ru,
        "negative_prompt": negative_prompt,
        "model_hint": model_hint,
        "key_details": key_details if isinstance(key_details, list) else [],
        "raw": parsed,
    }


class PhotoPromptService:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or config.KIE_AI_API_KEY
        self.base_url = "https://api.kie.ai"

    async def _analyze_with_gpt54(
        self,
        *,
        image_url: str,
        user_instruction: str,
        headers: Dict[str, str],
    ) -> Dict[str, Any]:
        payload = {
            "model": "gpt-5-4",
            "stream": False,
            "input": [
                {
                    "role": "system",
                    "content": [{"type": "input_text", "text": SYSTEM_PROMPT}],
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": user_instruction},
                        {"type": "input_image", "image_url": image_url},
                    ],
                },
            ],
            "reasoning": {"effort": "high"},
        }

        timeout = aiohttp.ClientTimeout(total=120)
        data: Optional[Dict[str, Any]] = None

        for attempt in range(3):
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    f"{self.base_url}/codex/v1/responses",
                    json=payload,
                    headers=headers,
                ) as response:
                    text = await response.text()

                    if response.status >= 500:
                        logger.error(
                            "GPT-5.4 server error: status=%s body=%s attempt=%d",
                            response.status,
                            text[:500],
                            attempt,
                        )
                        if attempt < 2:
                            await asyncio.sleep(2**attempt)
                            continue
                        raise RuntimeError(
                            f"GPT-5.4 недоступен. Код: {response.status}"
                        )

                    if response.status >= 400:
                        raise RuntimeError(f"GPT-5.4 ошибка. Код: {response.status}")

                    try:
                        data = json.loads(text)
                    except Exception:
                        raise RuntimeError("GPT-5.4 вернул некорректный JSON")

                    body_code = data.get("code") if isinstance(data, dict) else None
                    if body_code and int(body_code) >= 400:
                        logger.error(
                            "GPT-5.4 application error in body: %s attempt=%d",
                            data,
                            attempt,
                        )
                        if attempt < 2:
                            await asyncio.sleep(2**attempt)
                            data = None
                            continue
                        raise RuntimeError(f"GPT-5.4 вернул ошибку: {body_code}")
            break

        if data is None:
            raise RuntimeError("GPT-5.4 не вернул данных после всех попыток")

        raw_output = _extract_output_text(data)
        parsed = _parse_json_object(raw_output)
        return _build_result(parsed)

    async def _analyze_with_claude(
        self,
        *,
        image_url: str,
        user_instruction: str,
        headers: Dict[str, str],
    ) -> Dict[str, Any]:
        payload = {
            "model": "claude-haiku-4-5",
            "stream": False,
            "max_tokens": 2048,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": SYSTEM_PROMPT + "\n\n" + user_instruction,
                        },
                        {
                            "type": "image",
                            "source": {"type": "url", "url": image_url},
                        },
                    ],
                }
            ],
        }

        timeout = aiohttp.ClientTimeout(total=90)

        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                f"{self.base_url}/claude/v1/messages",
                json=payload,
                headers=headers,
            ) as response:
                text = await response.text()

                if response.status >= 400:
                    logger.error(
                        "Claude Haiku fallback failed: status=%s body=%s",
                        response.status,
                        text[:2000],
                    )
                    raise RuntimeError(
                        f"Claude Haiku недоступен. Код: {response.status}"
                    )

                try:
                    data = json.loads(text)
                except Exception:
                    raise RuntimeError("Claude Haiku вернул некорректный JSON")

        raw_output = _extract_claude_text(data)
        if not raw_output:
            raise RuntimeError("Claude Haiku вернул пустой ответ")

        parsed = _parse_json_object(raw_output)
        return _build_result(parsed)

    async def analyze_photo(
        self,
        *,
        image_url: str,
        preserve: str = "",
        goal: str = "",
    ) -> Dict[str, Any]:
        if not self.api_key:
            raise RuntimeError("KIE_AI_API_KEY is not configured")
        if not image_url:
            raise ValueError("image_url is required")

        user_instruction = (
            f"Analyze this image and create a precise prompt for generating a visually similar image.\n\n"
            f"User goal:\n{goal or 'Generate a visually similar image based on the reference.'}\n\n"
            f"Important details to preserve:\n{preserve or 'Subject appearance, composition, lighting, style, colors, pose, background, and camera feel.'}\n\n"
            f"Return valid JSON only according to the required schema."
        )

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            return await self._analyze_with_gpt54(
                image_url=image_url,
                user_instruction=user_instruction,
                headers=headers,
            )
        except Exception as exc:
            logger.warning(
                "GPT-5.4 failed (%s), switching to Claude Haiku fallback", exc
            )

        return await self._analyze_with_claude(
            image_url=image_url,
            user_instruction=user_instruction,
            headers=headers,
        )


photo_prompt_service = PhotoPromptService()
