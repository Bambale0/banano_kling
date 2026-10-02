import io
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.exceptions import TelegramBadRequest
from PIL import Image

from bot.handlers import common, generation


def reference(filename="original.png"):
    return SimpleNamespace(
        id=7,
        file_url="https://example.invalid/original.png",
        created_at=None,
        original_filename=filename,
    )


def state():
    return SimpleNamespace(get_data=AsyncMock(return_value={}), clear=AsyncMock())


@pytest.mark.asyncio
async def test_oversized_saved_reference_sends_bounded_preview_and_preserves_original(
    tmp_path, monkeypatch
):
    source = tmp_path / "original.png"
    Image.new("RGB", (2200, 2200), "white").save(source, compress_level=0)
    original = source.read_bytes()
    assert len(original) > 10 * 1024 * 1024
    monkeypatch.setattr(
        "bot.services.media_input_utils.resolve_local_upload_path",
        lambda _: str(source),
    )
    sent = SimpleNamespace(message_id=2)

    async def send_photo(**kwargs):
        photo = kwargs["photo"]
        if isinstance(photo, str) or len(photo.data) > 10 * 1024 * 1024:
            raise TelegramBadRequest(
                method="sendPhoto", message="file is too big for a photo"
            )
        with Image.open(io.BytesIO(photo.data)) as preview:
            assert preview.format == "JPEG"
            assert max(preview.size) <= 2048
        return sent

    message = SimpleNamespace(
        answer_photo=AsyncMock(side_effect=send_photo), answer=AsyncMock()
    )
    ref = reference()
    result = await generation._send_saved_reference_preview(
        message, state(), refs=[ref], index=0
    )
    assert result is sent
    assert source.read_bytes() == original
    assert ref.file_url == "https://example.invalid/original.png"
    assert (
        "savedref"
        in message.answer_photo.await_args.kwargs["reply_markup"].model_dump_json()
    )


@pytest.mark.asyncio
async def test_unusable_saved_preview_remains_selectable_as_text(tmp_path, monkeypatch):
    source = tmp_path / "broken.png"
    source.write_bytes(b"not an image")
    monkeypatch.setattr(
        "bot.services.media_input_utils.resolve_local_upload_path",
        lambda _: str(source),
    )
    message = SimpleNamespace(
        answer_photo=AsyncMock(
            side_effect=TelegramBadRequest(method="sendPhoto", message="invalid photo")
        ),
        answer=AsyncMock(),
    )
    await generation._send_saved_reference_preview(
        message, state(), refs=[reference("<original>.png")], index=0
    )
    message.answer.assert_awaited_once()
    assert "&lt;original&gt;.png" in message.answer.await_args.args[0]
    assert (
        "savedref" in message.answer.await_args.kwargs["reply_markup"].model_dump_json()
    )


@pytest.mark.asyncio
async def test_rejected_normalized_preview_falls_back_to_selectable_text(
    tmp_path, monkeypatch
):
    source = tmp_path / "ok.png"
    Image.new("RGB", (30, 30)).save(source)
    monkeypatch.setattr(
        "bot.services.media_input_utils.resolve_local_upload_path",
        lambda _: str(source),
    )
    message = SimpleNamespace(
        answer_photo=AsyncMock(
            side_effect=TelegramBadRequest(method="sendPhoto", message="invalid photo")
        ),
        answer=AsyncMock(),
    )
    await generation._send_saved_reference_preview(
        message, state(), refs=[reference()], index=0
    )
    message.answer.assert_awaited_once()
    assert (
        "savedref" in message.answer.await_args.kwargs["reply_markup"].model_dump_json()
    )


@pytest.mark.asyncio
async def test_saved_preview_url_success_keeps_original(monkeypatch):
    message = SimpleNamespace(answer_photo=AsyncMock(), answer=AsyncMock())
    await generation._send_saved_reference_preview(
        message, state(), refs=[reference()], index=0
    )
    message.answer_photo.assert_awaited_once()
    assert message.answer_photo.await_args.kwargs["photo"] == reference().file_url
    message.answer.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("media", [True, False])
async def test_more_menu_opens_from_media_and_text_messages(monkeypatch, media):
    message = SimpleNamespace(
        from_user=SimpleNamespace(is_bot=True),
        photo=[object()] if media else None,
        delete=AsyncMock(),
        answer=AsyncMock(),
        edit_text=AsyncMock(),
    )
    if media:
        message.edit_text.side_effect = TelegramBadRequest(
            method="editMessageText", message="there is no text in the message to edit"
        )
    callback = SimpleNamespace(
        message=message, from_user=SimpleNamespace(id=1), answer=AsyncMock()
    )
    monkeypatch.setattr(
        common,
        "get_or_create_user",
        AsyncMock(return_value=SimpleNamespace(credits=10)),
    )
    await common.show_more_menu(callback, state())
    callback.answer.assert_awaited_once()
    if media:
        message.answer.assert_awaited_once()
        message.edit_text.assert_not_awaited()
    else:
        message.edit_text.assert_awaited_once()
