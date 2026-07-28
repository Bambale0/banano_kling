from bot.handlers.generation import (
    _published_feed_link,
    _published_feed_link_keyboard,
)


def test_published_feed_link_opens_exact_work() -> None:
    url = _published_feed_link(
        "Neuromixx_bot",
        {"id": 321, "author_referral_code": "banana"},
    )

    assert url == "https://t.me/Neuromixx_bot?startapp=feed_321_ref_BANANA"

    markup = _published_feed_link_keyboard(url)
    copy_button = markup.inline_keyboard[0][0]
    open_button = markup.inline_keyboard[1][0]
    assert copy_button.text == "📋 Скопировать ссылку"
    assert copy_button.copy_text.text == url
    assert open_button.text == "🔗 Открыть работу"
    assert open_button.url == url
