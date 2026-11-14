"""Seedance 2.5 Telegram sends must preserve the real MP4 display aspect ratio."""

from __future__ import annotations

import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import SendVideo

from bot.handlers import seedance_25_fullstack, seedance_25_public_release

GEOMETRY = importlib.import_module("bot.services.telegram_video_geometry")


@pytest.mark.asyncio
@pytest.mark.parametrize("handler", ["public", "fullstack"])
@pytest.mark.parametrize("fallback", [False, True])
async def test_seedance25_telegram_portrait_geometry_survives_url_and_file_fallback(
    monkeypatch, tmp_path, handler, fallback
):
    video_path = tmp_path / "portrait.mp4"
    video_path.write_bytes(b"video fixture geometry provided by the probe")
    monkeypatch.setattr(
        GEOMETRY.media_input_utils,
        "resolve_local_upload_path",
        lambda _url: str(video_path),
    )
    monkeypatch.setattr(GEOMETRY, "video_preview_dimensions", lambda _path: (720, 1280))
    monkeypatch.setattr(
        seedance_25_fullstack,
        "_download_to_temp",
        AsyncMock(return_value=str(video_path)),
    )

    rejected_url = TelegramBadRequest(
        method=SendVideo(chat_id=123, video="https://cdn.example/portrait.mp4"),
        message="Bad Request: failed to get HTTP URL content",
    )
    send = AsyncMock(
        side_effect=[rejected_url, SimpleNamespace(video=None)]
        if fallback
        else [SimpleNamespace(video=None)]
    )
    bot = SimpleNamespace(send_video=send, send_message=AsyncMock())
    request_data = {
        "output_format": "mp4",
        "duration": 10,
        "aspect_ratio": "9:16",
        "seedance25_scenario": "multimodal",
    }
    deliver = (
        seedance_25_public_release._public_send_results
        if handler == "public"
        else seedance_25_fullstack._send_seedance25_results
    )

    delivered = await deliver(
        {"bot": bot},
        123,
        "seedance-task-portrait",
        "https://cdn.example/portrait.mp4",
        None,
        request_data,
    )

    assert delivered is True
    assert send.await_count == (2 if fallback else 1)
    for call in send.await_args_list:
        assert (call.kwargs.get("width"), call.kwargs.get("height")) == (720, 1280)
        assert call.kwargs["supports_streaming"] is True
    bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("handler", ["public", "fullstack"])
async def test_seedance25_telegram_delivery_keeps_working_without_ffprobe(
    monkeypatch, tmp_path, handler
):
    video_path = tmp_path / "unprobeable.mp4"
    video_path.write_bytes(b"video fixture")
    monkeypatch.setattr(
        GEOMETRY.media_input_utils,
        "resolve_local_upload_path",
        lambda _url: str(video_path),
    )
    monkeypatch.setattr(GEOMETRY, "video_preview_dimensions", lambda _path: None)
    send = AsyncMock(return_value=SimpleNamespace(video=None))
    bot = SimpleNamespace(send_video=send)
    deliver = (
        seedance_25_public_release._public_send_results
        if handler == "public"
        else seedance_25_fullstack._send_seedance25_results
    )

    assert await deliver(
        {"bot": bot},
        123,
        "seedance-task-unprobeable",
        "https://cdn.example/unprobeable.mp4",
        None,
        {"output_format": "mp4", "duration": 10},
    )
    sent = send.await_args.kwargs
    assert "width" not in sent
    assert "height" not in sent


@pytest.mark.asyncio
async def test_geometry_local_upload_resolution_never_blocks_the_event_loop(
    monkeypatch,
):
    import threading

    current_thread = threading.get_ident()

    def slow_s3_resolver(_source):
        assert threading.get_ident() != current_thread

    monkeypatch.setattr(
        GEOMETRY.media_input_utils, "resolve_local_upload_path", slow_s3_resolver
    )
    assert (
        await GEOMETRY.telegram_video_geometry("https://example.com/uploads/clip.mp4")
        == {}
    )
