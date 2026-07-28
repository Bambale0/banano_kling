import asyncio
import hashlib
import hmac
import json
import logging
from unittest.mock import AsyncMock
from unittest.mock import Mock

import pytest
from aiohttp import web

import bot.database
import bot.main as main
from bot.config import config
from bot.main import (
    _build_failure_notification_text,
    _build_plain_result_link_text,
    _extract_gemini_omni_asset_id,
    _send_video_file_from_url,
    _TELEGRAM_WEBHOOK_TASKS,
    handle_kling_webhook,
    handle_telegram_webhook,
)


@pytest.mark.asyncio
async def test_handle_kling_webhook_signature_ok(monkeypatch, caplog):
    # Prepare a minimal successful payload
    payload = {
        "id": "task123",
        "status": "succeeded",
        "output": "https://x.example/out.mp4",
    }
    body = json.dumps(payload).encode("utf-8")

    secret = "testsecret"
    monkeypatch.setenv("REPLICATE_WEBHOOK_SECRET", secret)
    # monkeypatch config to pick up secret
    monkeypatch.setattr(config, "REPLICATE_WEBHOOK_SECRET", secret)

    sig = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()

    # Build a lightweight fake request object with just the attributes the handler uses
    class FakeReq:
        def __init__(self, body, headers):
            self._body = body
            self.headers = headers

        async def read(self):
            return self._body

    monkeypatch.setattr(bot.database, "get_task_by_id", AsyncMock(return_value=None))

    req = FakeReq(body, {"x-replicate-signature": sig})

    with caplog.at_level(logging.WARNING):
        resp = await handle_kling_webhook(req)
    assert resp.status == 200
    assert "Task task123 not found in database" not in caplog.text
    assert "Kling webhook error" not in caplog.text


@pytest.mark.asyncio
async def test_handle_kling_webhook_signature_rejects_invalid_signature(monkeypatch):
    payload = {
        "id": "task123",
        "status": "succeeded",
        "output": "https://x.example/out.mp4",
    }
    body = json.dumps(payload).encode("utf-8")

    secret = "testsecret"
    monkeypatch.setattr(config, "REPLICATE_WEBHOOK_SECRET", secret)

    class FakeReq:
        def __init__(self, body, headers):
            self._body = body
            self.headers = headers

        async def read(self):
            return self._body

    req = FakeReq(body, {"x-replicate-signature": "bad-signature"})

    resp = await handle_kling_webhook(req)
    assert resp.status == 200


@pytest.mark.asyncio
async def test_handle_telegram_webhook_uses_plain_background_update_processing():
    class FakeReq:
        async def read(self):
            return b'{"update_id": 12345}'

    bot = Mock()
    dp = Mock()
    dp.feed_update = AsyncMock()
    dp.feed_webhook_update = AsyncMock()

    resp = await handle_telegram_webhook(FakeReq(), bot, dp)

    assert resp.status == 200
    for task in list(_TELEGRAM_WEBHOOK_TASKS):
        await task

    dp.feed_update.assert_awaited_once()
    dp.feed_webhook_update.assert_not_awaited()


def test_extract_gemini_omni_asset_id_from_result_json():
    audio_payload = {
        "data": {
            "resultJson": json.dumps(
                {"data": {"kieAudioId": "audio_abc"}}
            )
        }
    }
    character_payload = {
        "data": {
            "resultJson": json.dumps(
                {"result": {"characterID": "character_abc"}}
            )
        }
    }

    assert _extract_gemini_omni_asset_id(audio_payload, "audio") == "audio_abc"
    assert (
        _extract_gemini_omni_asset_id(character_payload, "character")
        == "character_abc"
    )


def test_failure_notification_escapes_html_reason():
    text = _build_failure_notification_text(
        service_name="WAN <pro>",
        task_id="task<1>",
        reason="<ContentLengthError: 400, message='Not enough data'>",
        media_kind="результата",
        refund_text="\n\nБананы возвращены.",
    )

    assert "WAN &lt;pro&gt;" in text
    assert "task&lt;1&gt;" in text
    assert "&lt;ContentLengthError: 400" in text
    assert "<ContentLengthError:" not in text


def test_plain_result_link_text_does_not_use_html_markup():
    text = _build_plain_result_link_text(
        media_label="Видео",
        model_label="Model <raw>",
        task_id="task<1>",
        result_url="https://example.com/video.mp4?x=<raw>",
    )

    assert "Model <raw>" in text
    assert "task<1>" in text
    assert "<code>" not in text
    assert "parse_mode" not in text


def test_seedance_real_person_image_failure_is_retryable_once_by_model():
    task = Mock(type="video", model="seedance_2")

    assert main._is_retryable_seedance_real_person_failure(
        task,
        "The input image 'content[0]' may contain real person.",
    )
    assert not main._is_retryable_seedance_real_person_failure(
        Mock(type="video", model="v3_pro"),
        "The input image 'content[0]' may contain real person.",
    )
    assert not main._is_retryable_seedance_real_person_failure(
        task,
        "The request contains prohibited content.",
    )


class _FakeContent:
    def __init__(self, chunks):
        self._chunks = chunks

    async def iter_chunked(self, _size):
        for chunk in self._chunks:
            yield chunk


class _FakeResponse:
    status = 200

    def __init__(self, chunks):
        self.content_length = sum(len(chunk) for chunk in chunks)
        self.content = _FakeContent(chunks)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeClientSession:
    chunks = [b"small-video"]

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def get(self, *args, **kwargs):
        return _FakeResponse(self.chunks)


class _FakeBot:
    def __init__(self):
        self.video_calls = []

    async def send_video(self, **kwargs):
        self.video_calls.append(kwargs)


@pytest.mark.asyncio
async def test_send_video_file_from_url_uploads_small_remote_file(monkeypatch):
    monkeypatch.setattr(main.aiohttp, "ClientSession", _FakeClientSession)
    bot = _FakeBot()

    delivered = await _send_video_file_from_url(
        bot,
        123,
        "https://cdn.example.com/result.mp4",
        caption="ready",
        max_upload_bytes=1024,
    )

    assert delivered is True
    assert len(bot.video_calls) == 1
    assert bot.video_calls[0]["chat_id"] == 123
    assert bot.video_calls[0]["caption"] == "ready"
    assert bot.video_calls[0]["video"].__class__.__name__ == "FSInputFile"
