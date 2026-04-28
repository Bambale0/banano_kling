"""Photo to prompt service via Kie GPT 5.4 Responses API."""

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

    # Fallbacks for provider variations.
    if isinstance(data.get("output_text"), str):
        return data["output_text"].strip()
    if isinstance(data.get("text"), str):
        return data["text"].strip()

    return json.dumps(data, ensure_ascii=False)


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


class PhotoPromptService:
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or config.KIE_AI_API_KEY
        self.base_url = "https://api.kie.ai"
        self.endpoint = "/codex/v1/responses"

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

        user_instruction = f"""
Analyze this image and create a precise prompt for generating a visually similar image.

User goal:
{goal or "Generate a visually similar image based on the reference."}

Important details to preserve:
{preserve or "Subject appearance, composition, lighting, style, colors, pose, background, and camera feel."}

Return valid JSON only according to the required schema.
""".strip()

        payload = {
            "model": "gpt-5-4",
            "stream": False,
            "input": [
                {
                    "role": "system",
                    "content": [
                        {
                            "type": "input_text",
                            "text": SYSTEM_PROMPT,
                        }
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": user_instruction,
                        },
                        {
                            "type": "input_image",
                            "image_url": image_url,
                        },
                    ],
                },
            ],
            "reasoning": {
                "effort": "high",
            },
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        timeout = aiohttp.ClientTimeout(total=120)

        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                f"{self.base_url}{self.endpoint}",
                json=payload,
                headers=headers,
            ) as response:
                text = await response.text()

                if response.status >= 400:
                    logger.error(
                        "Photo prompt GPT 5.4 failed: status=%s body=%s",
                        response.status,
                        text[:2000],
                    )
                    raise RuntimeError(
                        f"AI-анализ фото временно недоступен. Код: {response.status}"
                    )

                try:
                    data = json.loads(text)
                except Exception:
                    logger.error(
                        "Photo prompt GPT 5.4 returned non-JSON: %s", text[:2000]
                    )
                    raise RuntimeError("AI вернул некорректный ответ")

        raw_output = _extract_output_text(data)
        parsed = _parse_json_object(raw_output)

        prompt_en = str(parsed.get("prompt_en") or "").strip()
        prompt_ru = str(parsed.get("prompt_ru") or "").strip()
        negative_prompt = str(parsed.get("negative_prompt") or "").strip()
        model_hint = str(parsed.get("model_hint") or "").strip()
        key_details = parsed.get("key_details") or []

        if not prompt_en:
            raise RuntimeError("AI не смог собрать prompt по фото")

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


photo_prompt_service = PhotoPromptService()
