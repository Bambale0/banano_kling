"""Kie.ai GPT 5.5 chat service using the Responses endpoint."""

import json
import logging
from typing import Optional

import aiohttp

from bot.config import config

logger = logging.getLogger(__name__)


class GPT55Service:
    ENDPOINT = "/codex/v1/responses"
    MODEL = "gpt-5-5"

    def __init__(self):
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=180)
            )
        return self._session

    def _history_to_input(self, history: list[dict]) -> list[dict]:
        result = []
        for item in history:
            role = item.get("role")
            if role == "assistant":
                text = str(item.get("content") or "").strip()
                if text:
                    result.append(
                        {
                            "role": "assistant",
                            "content": [{"type": "output_text", "text": text}],
                        }
                    )
                continue

            if role == "user":
                content = item.get("content") or []
                if isinstance(content, str):
                    content = [{"type": "input_text", "text": content}]
                if isinstance(content, list) and content:
                    result.append({"role": "user", "content": content})
        return result

    def _extract_text(self, data: dict) -> str:
        if isinstance(data.get("output_text"), str):
            return data["output_text"].strip()

        texts = []
        for output_item in data.get("output", []) or []:
            if output_item.get("type") not in {None, "message"}:
                continue
            for content_item in output_item.get("content", []) or []:
                if content_item.get("type") == "output_text":
                    text = content_item.get("text")
                    if text:
                        texts.append(text)
        return "\n\n".join(texts).strip()

    def _parse_response_text(self, response_text: str) -> Optional[dict]:
        try:
            return json.loads(response_text)
        except json.JSONDecodeError:
            pass

        # Some Kie docs mark the response as text/event-stream even for examples.
        # Accept simple SSE frames if the gateway returns them.
        for line in response_text.splitlines():
            line = line.strip()
            if not line.startswith("data:"):
                continue
            payload = line.removeprefix("data:").strip()
            if not payload or payload == "[DONE]":
                continue
            try:
                data = json.loads(payload)
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict) and data.get("output"):
                return data
        return None

    async def ask(
        self,
        user_content: list[dict],
        history: list[dict] | None = None,
        reasoning_effort: str = "high",
        web_search: bool = True,
    ) -> Optional[str]:
        if not config.KIE_AI_API_KEY:
            logger.error("KIE_AI_API_KEY is not configured for GPT 5.5")
            return None

        system_prompt = (
            "Ты GPT 5.5 внутри Telegram-бота Banana Boom. Отвечай на русском, "
            "если пользователь не попросил другой язык. Помогай с любыми задачами: "
            "текст, код, анализ, промпты, изображения и файлы. Учитывай предыдущий "
            "контекст диалога. Если используешь web search, кратко отделяй проверенные "
            "факты от выводов."
        )

        input_items = [
            {
                "role": "developer",
                "content": [{"type": "input_text", "text": system_prompt}],
            }
        ]
        input_items.extend(self._history_to_input(history or []))
        input_items.append({"role": "user", "content": user_content})

        payload = {
            "model": self.MODEL,
            "stream": False,
            "input": input_items,
            "reasoning": {"effort": reasoning_effort},
        }
        if web_search:
            payload["tools"] = [{"type": "web_search"}]

        headers = {
            "Authorization": f"Bearer {config.KIE_AI_API_KEY}",
            "Content-Type": "application/json",
        }

        session = await self._get_session()
        async with session.post(
            f"{config.KIE_BASE_URL}{self.ENDPOINT}", headers=headers, json=payload
        ) as response:
            response_text = await response.text()
            logger.info(
                "Kie.ai GPT 5.5 status=%s content-type=%s bytes=%s",
                response.status,
                response.headers.get("content-type", "none"),
                len(response_text),
            )
            if response.status != 200:
                return None
            data = self._parse_response_text(response_text)
            if not data:
                logger.error("Failed to parse GPT 5.5 response")
                return None
            return self._extract_text(data)

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()


gpt55_service = GPT55Service()
