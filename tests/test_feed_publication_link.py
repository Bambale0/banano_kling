from bot.handlers.generation import (
    _published_feed_bot_link,
    _published_feed_link,
    _published_feed_link_keyboard,
)


def test_published_feed_link_opens_exact_work() -> None:
    url = _published_feed_link(
        "Neuromixx_bot",
        {"id": 321, "author_referral_code": "banana"},
    )

    assert url == "https://t.me/Neuromixx_bot?startapp=feed_321_ref_BANANA"
    bot_url = _published_feed_bot_link(
        "Neuromixx_bot",
        {"id": 321, "author_referral_code": "banana"},
    )
    assert bot_url == "https://t.me/Neuromixx_bot?start=feed_321_ref_BANANA"

    markup = _published_feed_link_keyboard(url, bot_url)
    copy_button = markup.inline_keyboard[0][0]
    bot_button = markup.inline_keyboard[1][0]
    miniapp_button = markup.inline_keyboard[2][0]
    assert copy_button.text == "📋 Скопировать ссылку"
    assert copy_button.copy_text.text == url
    assert bot_button.text == "🤖 Открыть работу в боте"
    assert bot_button.url == bot_url
    assert miniapp_button.text == "📱 Открыть работу в Mini App"
    assert miniapp_button.url == url
