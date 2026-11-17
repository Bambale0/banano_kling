"""GPT-6 Responses adapter for KIE, isolated from Astro facts and billing.

KIE can encode 401, 402 and 429 as JSON *inside HTTP 200*; inspect both.
Only structured section text is accepted. Never log prompts, API keys or births.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import aiohttp

from bot.config import config


class KieRetryableError(RuntimeError):
    """Temporary provider failure or invalid/truncated response."""


class KiePermanentError(RuntimeError):
    """Invalid credentials, credits, configuration or payload."""


@dataclass(frozen=True, slots=True)
class AstroKieSettings:
    api_key: str
    model: str
    base_url: str
    timeout_seconds: float
    max_output_tokens: int
    reasoning_effort: str

    def __post_init__(self):
        if not self.api_key.strip() or not self.model.strip() or not self.base_url.startswith("https://"):
            raise KiePermanentError("KIE report model/credentials not configured")
        if not (1 <= self.timeout_seconds <= 600 and 512 <= self.max_output_tokens <= 128000):
            raise KiePermanentError("Unsafe Astro KIE limits")
        if self.reasoning_effort not in ("low", "medium", "high", "xhigh", "max"):
            raise KiePermanentError("Unsupported Astro reasoning effort")

    @classmethod
    def from_config(cls) -> AstroKieSettings:
        try:
            return cls(
                api_key=config.KIE_AI_API_KEY,
                model=os.getenv("ASTRO_REPORT_KIE_MODEL", ""),
                base_url=config.KIE_BASE_URL.rstrip("/"),
                timeout_seconds=float(os.getenv("ASTRO_REPORT_KIE_TIMEOUT_SECONDS", "120")),
                max_output_tokens=int(os.getenv("ASTRO_REPORT_KIE_MAX_OUTPUT_TOKENS", "8192")),
                reasoning_effort=os.getenv("ASTRO_REPORT_KIE_REASONING", "low"),
            )
        except (ValueError, TypeError) as exc:
            raise KiePermanentError("Invalid Astro KIE configuration") from exc


_SECTION_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {"section_id": {"type": "string"}, "text": {"type": "string"}},
    "required": ["section_id", "text"],
}


class KieSectionProvider:
    def __init__(self, settings: AstroKieSettings, *, session=None):
        self.settings = settings
        self.session = session

    @classmethod
    def from_config(cls):
        return cls(AstroKieSettings.from_config())

    async def analyze_text(
        self, *, user_instruction: str, system_prompt: str | None = None,
        json_response: bool = True,
    ) -> str:
        if not json_response or not system_prompt or not user_instruction:
            raise KiePermanentError("Astro sections require structured prompts")
        if len(user_instruction.encode("utf-8")) > 350_000:
            raise KiePermanentError("Astro source facts exceed provider limit")
        payload = {
            "model": self.settings.model,
            "stream": False,
            "store": False,
            "input": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_instruction},
            ],
            "reasoning": {"effort": self.settings.reasoning_effort},
            "max_output_tokens": self.settings.max_output_tokens,
            "text": {"format": {
                "type": "json_schema", "name": "astro_section",
                "strict": True, "schema": _SECTION_SCHEMA,
            }},
        }
        headers = {
            "Authorization": "Bearer " + self.settings.api_key,
            "Content-Type": "application/json",
        }
        url = self.settings.base_url + "/codex/v1/responses"
        timeout = aiohttp.ClientTimeout(
            total=self.settings.timeout_seconds, connect=min(self.settings.timeout_seconds, 15),
        )
        try:
            if self.session is None:
                async with (
                    aiohttp.ClientSession() as session,
                    session.post(url, json=payload, headers=headers, timeout=timeout) as response,
                ):
                    return self._parse(await response.json(content_type=None), response.status)
            async with self.session.post(url, json=payload, headers=headers, timeout=timeout) as response:
                return self._parse(await response.json(content_type=None), response.status)
        except (TimeoutError, aiohttp.ClientError) as exc:
            raise KieRetryableError("KIE transport timeout or network failure") from exc
        except (ValueError, UnicodeDecodeError) as exc:
            raise KieRetryableError("KIE response was not valid JSON") from exc

    @staticmethod
    def _parse(data: object, status: int) -> str:
        if not isinstance(data, dict):
            raise KieRetryableError("KIE returned invalid envelope")
        body_code = data.get("code")
        error = data.get("error")
        if isinstance(error, dict):
            body_code = error.get("code", body_code)
            kind = str(error.get("type", "")).lower()
            if "rate" in kind or "timeout" in kind or "unavailable" in kind:
                body_code = 429 if "rate" in kind else 503
        try:
            code = int(body_code) if body_code is not None else status
        except (TypeError, ValueError):
            code = status
        if code in (401, 402, 403, 400, 404, 422):
            raise KiePermanentError("KIE rejected configured Astro request")
        if code >= 500 or code in (408, 409, 425, 429) or error:
            raise KieRetryableError("KIE provider temporarily unavailable")
        if data.get("status") != "completed":
            raise KieRetryableError("KIE response incomplete")
        content = []
        for message in data.get("output", []):
            if not isinstance(message, dict) or message.get("type") != "message":
                continue
            for part in message.get("content", []):
                if isinstance(part, dict) and part.get("type") == "output_text":
                    value = part.get("text")
                    if isinstance(value, str):
                        content.append(value)
        if len(content) != 1 or not content[0].strip():
            raise KieRetryableError("KIE structured section missing")
        return content[0]
