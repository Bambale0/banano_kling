import asyncio
import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram import Bot
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
    TelegramServerError,
)
from aiogram.methods import SendMessage

from bot.promo_message import (
    DeliveryLeaseLost,
    DeliveryPartError,
    PromoMessageValidationError,
    build_message_snapshot,
    deliver_message_snapshot,
    normalize_message,
    validate_snapshot,
)


@pytest.mark.asyncio
async def test_two_video_promo_preserves_order_and_attaches_two_trend_buttons():
    source = {
        "schema_version": 2,
        "text": "<b>Try these</b>",
        "parse_mode": "HTML",
        "media": [
            {"type": "video", "file_id": "video_one"},
            {"type": "video", "file_id": "video_two"},
        ],
        "buttons": [
            {"position": 2, "text": "Second", "action": "trend", "trend_id": 22},
            {"position": 1, "text": "First", "action": "trend", "trend_id": 11},
        ],
    }
    snapshot = build_message_snapshot(source, "example_bot")
    bot = SimpleNamespace(
        send_media_group=AsyncMock(
            return_value=[
                SimpleNamespace(message_id=101),
                SimpleNamespace(message_id=102),
            ]
        ),
        send_message=AsyncMock(return_value=SimpleNamespace(message_id=103)),
    )
    saved = []

    async def persist(parts):
        saved.append(parts)

    result = await deliver_message_snapshot(
        bot, 123, snapshot, delivery_parts=[], save_progress=persist
    )
    assert result.message_ids == [101, 102, 103]
    album = bot.send_media_group.await_args.kwargs
    assert album["media"] == [
        {"type": "video", "media": "video_one", "parse_mode": None},
        {"type": "video", "media": "video_two", "parse_mode": None},
    ]
    assert "reply_markup" not in album
    text = bot.send_message.await_args.kwargs
    assert text["text"] == "<b>Try these</b>"
    assert text["parse_mode"] == "HTML"
    assert text["reply_markup"]["inline_keyboard"] == [
        [{"text": "First", "url": "https://t.me/example_bot?startapp=prompt_11"}],
        [{"text": "Second", "url": "https://t.me/example_bot?startapp=prompt_22"}],
    ]
    assert [p[0]["status"] for p in saved[:2]] == ["sending", "sent"]
    assert saved[-1][1]["message_ids"] == [103]


def promo(*, media_count=0, button_count=0, text="Promotion"):
    return {
        "schema_version": 2,
        "text": text,
        "media": [
            {"type": "video", "file_id": f"video_{index}"}
            for index in range(media_count)
        ],
        "buttons": [
            {
                "position": index + 1,
                "text": f"Trend {index + 1}",
                "action": "trend",
                "trend_id": index + 11,
            }
            for index in range(button_count)
        ],
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("media_count", [0, 1])
@pytest.mark.parametrize("button_count", [0, 1, 2])
async def test_single_part_text_and_video_promos_keep_keyboard(
    media_count, button_count
):
    snapshot = build_message_snapshot(
        promo(media_count=media_count, button_count=button_count), "example_bot"
    )
    bot = SimpleNamespace(
        send_message=AsyncMock(return_value=SimpleNamespace(message_id=1)),
        send_video=AsyncMock(return_value=SimpleNamespace(message_id=1)),
    )
    persist = AsyncMock()
    result = await deliver_message_snapshot(
        bot, 123, snapshot, delivery_parts=[], save_progress=persist
    )
    assert result.message_ids == [1]
    call = bot.send_video if media_count else bot.send_message
    kwargs = call.await_args.kwargs
    assert kwargs["parse_mode"] is None  # Override any bot-wide HTML default.
    keyboard = kwargs["reply_markup"]
    assert (
        keyboard is None
        if button_count == 0
        else len(keyboard["inline_keyboard"]) == button_count
    )
    assert persist.await_count == 2


@pytest.mark.asyncio
async def test_snapshot_is_accepted_by_actual_aiogram_method_models():
    bot = Bot(token="123456789:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")
    bot.session = AsyncMock(
        side_effect=[
            [SimpleNamespace(message_id=1), SimpleNamespace(message_id=2)],
            SimpleNamespace(message_id=3),
        ]
    )
    snapshot = build_message_snapshot(
        promo(media_count=2, button_count=2), "example_bot"
    )
    await deliver_message_snapshot(
        bot, 123, snapshot, delivery_parts=[], save_progress=AsyncMock()
    )
    album_method = bot.session.await_args_list[0].args[1]
    text_method = bot.session.await_args_list[1].args[1]
    assert [item.media for item in album_method.media] == ["video_0", "video_1"]
    assert all(item.parse_mode is None for item in album_method.media)
    assert text_method.reply_markup.inline_keyboard[1][0].url.endswith("prompt_12")


@pytest.mark.parametrize("bad", [True, False, 1.0, "1", 0, -1, None])
def test_trend_ids_are_positive_integers_without_coercion(bad):
    value = promo(button_count=1)
    value["buttons"][0]["trend_id"] = bad
    with pytest.raises(PromoMessageValidationError, match="positive integer"):
        normalize_message(value)


@pytest.mark.parametrize(
    "change",
    [
        lambda value: value["buttons"][0].update(url="https://evil.invalid"),
        lambda value: value["buttons"][0].update(action="url"),
        lambda value: value["buttons"][0].update(text="a" * 65),
        lambda value: value["buttons"][0].update(text=" "),
        lambda value: value["buttons"][1].update(position=1),
        lambda value: value["buttons"][0].update(position=True),
        lambda value: value.update(parse_mode="Markdown"),
        lambda value: value.update(button_url="https://evil.invalid"),
        lambda value: value["media"][0].update(
            file_id="https://evil.invalid/video.mp4"
        ),
        lambda value: value["media"][0].update(type="document"),
    ],
)
def test_invalid_parts_are_rejected_atomically(change):
    value = promo(media_count=2, button_count=2)
    change(value)
    with pytest.raises(PromoMessageValidationError):
        build_message_snapshot(value, "example_bot")


def test_media_and_text_limits_and_draft_composition():
    normalize_message(promo(media_count=10))
    with pytest.raises(PromoMessageValidationError, match="at most 10"):
        normalize_message(promo(media_count=11))
    normalize_message(promo(text="x" * 4096))
    with pytest.raises(PromoMessageValidationError, match="4096"):
        normalize_message(promo(text="x" * 4097))
    normalize_message(promo(media_count=1, text="x" * 1024))
    with pytest.raises(PromoMessageValidationError, match="1024"):
        normalize_message(promo(media_count=1, text="x" * 1025))
    normalize_message(promo(media_count=1, text=""))
    with pytest.raises(PromoMessageValidationError, match="required"):
        normalize_message(promo(media_count=2, text=""))
    normalize_message(promo(media_count=2, text=""), allow_empty=True)
    normalize_message(promo(text=""), allow_empty=True)


def test_html_is_validated_without_rewriting_formatting():
    value = promo(media_count=1, text="<b>" + "x" * 1024 + "</b>")
    value["parse_mode"] = "HTML"
    assert normalize_message(value)["text"] == value["text"]
    for text in ["<b>broken", "<b><i>bad</b></i>", "<script>bad</script>"]:
        value["text"] = text
        with pytest.raises(PromoMessageValidationError):
            normalize_message(value)


def test_snapshot_hash_covers_order_text_format_button_and_resolved_url():
    value = promo(media_count=2, button_count=2)
    original = build_message_snapshot(value, "example_bot")
    variants = []
    changed = copy.deepcopy(value)
    changed["media"].reverse()
    variants.append(build_message_snapshot(changed, "example_bot"))
    changed = copy.deepcopy(value)
    changed["buttons"][0]["text"] = "Different"
    variants.append(build_message_snapshot(changed, "example_bot"))
    changed = copy.deepcopy(value)
    changed["buttons"][0]["trend_id"] = 99
    variants.append(build_message_snapshot(changed, "example_bot"))
    changed = copy.deepcopy(value)
    changed["text"] = "Different"
    variants.append(build_message_snapshot(changed, "example_bot"))
    changed = copy.deepcopy(value)
    changed["parse_mode"] = "HTML"
    variants.append(build_message_snapshot(changed, "example_bot"))
    variants.append(build_message_snapshot(value, "other_bot"))
    assert all(item["content_hash"] != original["content_hash"] for item in variants)
    changed = copy.deepcopy(value)
    changed["buttons"].reverse()
    assert build_message_snapshot(changed, "example_bot") == original
    original["parts"][0]["kwargs"]["media"].reverse()
    with pytest.raises(PromoMessageValidationError, match="hash"):
        validate_snapshot(original)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        TelegramRetryAfter(
            method=SendMessage(chat_id=1, text="test"),
            message="limited",
            retry_after=37,
        )
    ],
)
async def test_partial_album_failure_resumes_text_only(error):
    snapshot = build_message_snapshot(
        promo(media_count=2, button_count=2), "example_bot"
    )
    bot = SimpleNamespace(
        send_media_group=AsyncMock(
            return_value=[
                SimpleNamespace(message_id=10),
                SimpleNamespace(message_id=11),
            ]
        ),
        send_message=AsyncMock(side_effect=[error, SimpleNamespace(message_id=12)]),
    )
    saved = []

    async def persist(parts):
        saved[:] = copy.deepcopy(parts)

    with pytest.raises(DeliveryPartError) as failure:
        await deliver_message_snapshot(
            bot, 123, snapshot, delivery_parts=[], save_progress=persist
        )
    assert failure.value.kind == "retryable"
    assert saved[0]["message_ids"] == [10, 11]
    assert saved[1]["status"] == "retryable"
    if isinstance(error, TelegramRetryAfter):
        assert failure.value.retry_after == 37
        assert saved[1]["retry_after"] == 37
    result = await deliver_message_snapshot(
        bot, 123, snapshot, delivery_parts=saved, save_progress=persist
    )
    assert result.message_ids == [10, 11, 12]
    bot.send_media_group.assert_awaited_once()
    assert bot.send_message.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error,kind",
    [
        (TimeoutError(), "uncertain"),
        (
            TelegramServerError(
                method=SendMessage(chat_id=1, text="x"), message="temporary"
            ),
            "uncertain",
        ),
        (
            TelegramNetworkError(
                method=SendMessage(chat_id=1, text="x"),
                message="connection lost secret-token",
            ),
            "uncertain",
        ),
        (
            TelegramForbiddenError(
                method=SendMessage(chat_id=1, text="x"), message="blocked"
            ),
            "blocked",
        ),
        (
            TelegramBadRequest(
                method=SendMessage(chat_id=1, text="x"), message="chat not found"
            ),
            "blocked",
        ),
        (
            TelegramBadRequest(
                method=SendMessage(chat_id=1, text="x"),
                message="invalid HTML secret-token",
            ),
            "terminal",
        ),
    ],
)
async def test_ambiguous_and_terminal_failures_never_replay(error, kind):
    snapshot = build_message_snapshot(promo(), "example_bot")
    bot = SimpleNamespace(send_message=AsyncMock(side_effect=error))
    saved = []

    async def persist(parts):
        saved[:] = copy.deepcopy(parts)

    with pytest.raises(DeliveryPartError) as failure:
        await deliver_message_snapshot(
            bot, 123, snapshot, delivery_parts=[], save_progress=persist
        )
    assert failure.value.kind == kind
    assert "secret-token" not in str(saved)
    with pytest.raises(DeliveryPartError):
        await deliver_message_snapshot(
            bot, 123, snapshot, delivery_parts=saved, save_progress=persist
        )
    bot.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_lease_fence_failure_prevents_network_send():
    snapshot = build_message_snapshot(promo(), "example_bot")
    bot = SimpleNamespace(send_message=AsyncMock())
    with pytest.raises(DeliveryLeaseLost):
        await deliver_message_snapshot(
            bot,
            123,
            snapshot,
            delivery_parts=[],
            save_progress=AsyncMock(side_effect=DeliveryLeaseLost()),
        )
    bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_receipt_write_failure_leaves_inflight_part_for_reconciliation():
    snapshot = build_message_snapshot(promo(), "example_bot")
    bot = SimpleNamespace(
        send_message=AsyncMock(return_value=SimpleNamespace(message_id=5))
    )
    saved = []

    async def persist(parts):
        if parts[0]["status"] == "sent":
            raise RuntimeError("database connection lost")
        saved[:] = copy.deepcopy(parts)

    with pytest.raises(RuntimeError):
        await deliver_message_snapshot(
            bot, 123, snapshot, delivery_parts=[], save_progress=persist
        )
    assert saved[0]["status"] == "sending"
    with pytest.raises(DeliveryPartError, match="unconfirmed_previous_attempt"):
        await deliver_message_snapshot(
            bot, 123, snapshot, delivery_parts=saved, save_progress=AsyncMock()
        )
    bot.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_cancelled_network_call_remains_inflight_and_is_not_replayed():
    snapshot = build_message_snapshot(promo(), "example_bot")
    bot = SimpleNamespace(send_message=AsyncMock(side_effect=asyncio.CancelledError()))
    saved = []

    async def persist(parts):
        saved[:] = copy.deepcopy(parts)

    with pytest.raises(asyncio.CancelledError):
        await deliver_message_snapshot(
            bot, 123, snapshot, delivery_parts=[], save_progress=persist
        )
    assert saved[0]["status"] == "sending"
    with pytest.raises(DeliveryPartError):
        await deliver_message_snapshot(
            bot, 123, snapshot, delivery_parts=saved, save_progress=AsyncMock()
        )
    bot.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_all_confirmed_receipts_recover_without_a_network_call():
    snapshot = build_message_snapshot(promo(media_count=2), "example_bot")
    bot = SimpleNamespace(
        send_media_group=AsyncMock(
            return_value=[SimpleNamespace(message_id=1), SimpleNamespace(message_id=2)]
        ),
        send_message=AsyncMock(return_value=SimpleNamespace(message_id=3)),
    )
    saved = []

    async def persist(parts):
        saved[:] = copy.deepcopy(parts)

    await deliver_message_snapshot(
        bot, 123, snapshot, delivery_parts=[], save_progress=persist
    )
    result = await deliver_message_snapshot(
        bot, 123, snapshot, delivery_parts=saved, save_progress=persist
    )
    assert result.message_ids == [1, 2, 3]
    bot.send_media_group.assert_awaited_once()
    bot.send_message.assert_awaited_once()


@pytest.mark.parametrize(
    "text",
    [
        "2 < 3",
        "2 > 1",
        "Rock & roll",
        "Unsupported &nbsp;",
        "<a>missing href</a>",
        "<b>broken &oops;</b>",
        "<?secret?>text",
        "<tg-emoji>missing id</tg-emoji>",
    ],
)
def test_invalid_telegram_html_is_rejected_before_album_can_send(text):
    value = promo(media_count=2, text=text)
    value["parse_mode"] = "HTML"
    with pytest.raises(PromoMessageValidationError):
        build_message_snapshot(value, "example_bot")


def test_telegram_html_entities_preserve_source_and_visible_length():
    value = promo(text="<b>&lt;&gt;&amp;&quot;&#128512;</b>")
    value["parse_mode"] = "HTML"
    assert normalize_message(value)["text"] == value["text"]


@pytest.mark.asyncio
async def test_hung_telegram_request_has_finite_timeout_and_is_uncertain(monkeypatch):
    from bot import promo_message

    monkeypatch.setattr(promo_message, "REQUEST_TIMEOUT_SECONDS", 0.01)

    async def hung_request(**kwargs):
        await asyncio.sleep(60)

    bot = SimpleNamespace(send_message=AsyncMock(side_effect=hung_request))
    snapshot = build_message_snapshot(promo(), "example_bot")
    saved = []

    async def persist(parts):
        saved[:] = copy.deepcopy(parts)

    with pytest.raises(DeliveryPartError) as error:
        await deliver_message_snapshot(bot, 123, snapshot, delivery_parts=[], save_progress=persist)
    assert error.value.kind == "uncertain"
    assert saved[0]["status"] == "uncertain"
    bot.send_message.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("button_count", [0, 1, 2])
async def test_single_photo_uses_caption_and_same_trend_keyboard(button_count):
    source = promo(media_count=1, button_count=button_count, text="<b>Photo</b>")
    source["parse_mode"] = "HTML"
    source["media"] = [{"type": "photo", "file_id": "photo_one"}]
    snapshot = build_message_snapshot(source, "example_bot")
    bot = SimpleNamespace(send_photo=AsyncMock(return_value=SimpleNamespace(message_id=15)))
    await deliver_message_snapshot(bot, 123, snapshot, delivery_parts=[], save_progress=AsyncMock())
    kwargs = bot.send_photo.await_args.kwargs
    assert kwargs["photo"] == "photo_one"
    assert kwargs["caption"] == "<b>Photo</b>"
    assert kwargs["parse_mode"] == "HTML"
    keyboard = kwargs["reply_markup"]
    assert keyboard is None if button_count == 0 else len(keyboard["inline_keyboard"]) == button_count
