from html import escape

from bot.handlers.common import (
    TELEGRAM_HTML_MESSAGE_LIMIT,
    _format_subscription_limits,
    _split_text_for_telegram,
)
from bot.services.gpt55_service import GPT55Service


def test_split_text_for_telegram_keeps_escaped_chunks_under_limit():
    text = ("<tag>& длинный ответ " * 500) + "\n\n" + ("слово " * 500)
    prefix = "🧠 <b>GPT 5.5:</b>\n\n"

    chunks = _split_text_for_telegram(text, prefix=prefix)

    assert len(chunks) > 1
    assert "длинный ответ" in chunks[0]
    assert "слово" in chunks[-1]
    for chunk in chunks:
        assert len(prefix + escape(chunk)) <= TELEGRAM_HTML_MESSAGE_LIMIT


def test_gpt55_extract_text_uses_message_output_only():
    service = GPT55Service()
    data = {
        "instructions": "internal instructions must not be sent",
        "output": [
            {
                "type": "reasoning",
                "content": [{"type": "output_text", "text": "hidden reasoning"}],
            },
            {
                "type": "message",
                "content": [{"type": "output_text", "text": "visible answer"}],
            },
        ],
    }

    assert service._extract_text(data) == "visible answer"


def test_gpt55_stream_delta_parser_accepts_responses_and_chat_events():
    service = GPT55Service()

    assert service._extract_stream_delta(
        {"type": "response.output_text.delta", "delta": "Привет"}
    ) == "Привет"
    assert service._extract_stream_delta(
        {"choices": [{"delta": {"content": " world"}}]}
    ) == " world"


def test_format_subscription_limits_shows_remaining_package_limits():
    text = _format_subscription_limits(
        {
            "package_name": "Studio",
            "image_limit": 350,
            "images_used": 125,
            "video_limit": 8,
            "videos_used": 7,
            "expires_at": "2026-07-03 12:00:00",
        }
    )

    assert "Подписка: <code>Studio</code>" in text
    assert "Фото осталось: <code>225</code> из <code>350</code>" in text
    assert "Видео: <code>осталось 1 из 8</code>" in text
    assert "До: <code>2026-07-03 12:00:00</code>" in text


def test_format_subscription_limits_marks_missing_video_limit():
    text = _format_subscription_limits(
        {
            "package_name": "Boom",
            "image_limit": 100,
            "images_used": 3,
            "video_limit": 0,
            "videos_used": 0,
            "expires_at": "2026-07-03 12:00:00",
        }
    )

    assert "Фото осталось: <code>97</code> из <code>100</code>" in text
    assert "Видео: <code>не входит в пакет</code>" in text
