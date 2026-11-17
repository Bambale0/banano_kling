"""KIE GPT-6 Responses contract: HTTP 200 is not necessarily success."""
import asyncio
import json

import pytest

from bot.services.astro_kie_gpt6 import (
    AstroKieSettings,
    KiePermanentError,
    KieRetryableError,
    KieSectionProvider,
)


class Response:
    def __init__(self, body, status=200):
        self.body = body
        self.status = status
        self.headers = {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        pass

    async def json(self, **_):
        return self.body


class Session:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def post(self, url, *, json, headers, timeout):
        self.calls.append((url, json, headers, timeout))
        return self.response


def settings():
    return AstroKieSettings(
        api_key="test-only", model="gpt-6-astra", base_url="https://api.kie.ai",
        timeout_seconds=30, max_output_tokens=8192, reasoning_effort="low",
    )


def run(session):
    return asyncio.run(KieSectionProvider(settings(), session=session).analyze_text(
        user_instruction='{"section_id":"first"}',
        system_prompt="Не выдумывай астрономические факты.",
        json_response=True,
    ))


def test_real_responses_envelope_and_configurable_gpt6_model():
    body = {"status": "completed", "output": [{"type": "message", "content": [
        {"type": "output_text", "text": '{"section_id":"first","text":"Готово"}'},
    ]}]}
    session = Session(Response(body))
    assert json.loads(run(session))["section_id"] == "first"
    url, request, headers, _timeout = session.calls[0]
    assert url.endswith("/codex/v1/responses")
    assert request["model"] == "gpt-6-astra"
    assert request["stream"] is False
    assert request["input"][0]["role"] == "system"
    assert request["input"][1]["role"] == "user"
    assert "tools" not in request
    assert request["text"]["format"]["strict"] is True
    assert headers["Authorization"] == "Bearer test-only"


@pytest.mark.parametrize("code,temporary", [(429, True), (500, True), (402, False), (401, False)])
def test_json_body_errors_even_with_http_200(code, temporary):
    error = {"code": code, "msg": "provider internal detail must not leak"}
    with pytest.raises(KieRetryableError if temporary else KiePermanentError):
        run(Session(Response(error, 200)))


def test_nonfinal_incomplete_or_malformed_responses_retry():
    for body in ({"status": "incomplete", "output": []},
                 {"status": "completed", "output": []},
                 {"error": {"type": "rate_limit_error"}}):
        with pytest.raises(KieRetryableError):
            run(Session(Response(body)))


def test_missing_model_and_key_fail_closed(monkeypatch):
    monkeypatch.delenv("ASTRO_REPORT_KIE_MODEL", raising=False)
    monkeypatch.setattr("bot.services.astro_kie_gpt6.config.KIE_AI_API_KEY", "")
    with pytest.raises(KiePermanentError):
        KieSectionProvider.from_config()
