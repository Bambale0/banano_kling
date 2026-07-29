from __future__ import annotations

import pytest

from bot.handlers.feed_model_filter_compat import (
    DEFAULT_FEED_MODEL,
    _build_model_picker_markup,
    _parse_model_picker_callback,
    clear_feed_model_cache,
    feed_model_matches,
    filter_feed_cards,
    normalize_feed_model,
    select_feed_model,
)


def test_banana_pro_aliases_share_one_feed_tab() -> None:
    assert normalize_feed_model(None) == DEFAULT_FEED_MODEL
    assert normalize_feed_model("banana_pro") == DEFAULT_FEED_MODEL
    assert normalize_feed_model("nano-banana-pro") == DEFAULT_FEED_MODEL
    assert normalize_feed_model("gemini-3-pro-image-preview") == DEFAULT_FEED_MODEL
    assert feed_model_matches("nano-banana-pro", "banana_pro") is True
    assert feed_model_matches("banana_2", "banana_pro") is False


def test_model_picker_has_banana_first_and_back_button() -> None:
    markup = _build_model_picker_markup(
        source_code="d",
        selected_model="seedream_5_pro",
        model_ids=["seedream_5_pro", "flux_pro", "banana_pro"],
    )

    buttons = [button for row in markup.inline_keyboard for button in row]
    assert buttons[0].text == "🧠 Nano Banana Pro"
    assert buttons[0].callback_data == "bfm:set:d:banana_pro"
    assert any(button.text == "✅ Seedream 5 Pro" for button in buttons)
    assert buttons[-1].text == "⬅️ Назад к ленте"
    assert buttons[-1].callback_data == "bfm:close:d"


def test_model_picker_callback_preserves_source() -> None:
    assert _parse_model_picker_callback("bfm:menu:t") == ("menu", "t", None)
    assert _parse_model_picker_callback("bfm:set:d:banana_2") == (
        "set",
        "d",
        "banana_2",
    )
    assert _parse_model_picker_callback("bfm:close:unknown") == (
        "close",
        "r",
        None,
    )


@pytest.mark.asyncio
async def test_filter_feed_cards_filters_before_pagination() -> None:
    clear_feed_model_cache()
    calls: list[dict] = []

    async def getter(**kwargs):
        calls.append(kwargs)
        return [
            {"id": 1, "model": "banana_2"},
            {"id": 2, "model": "banana_pro"},
            {"id": 3, "model": "nano-banana-pro"},
            {"id": 4, "model": "flux_pro"},
        ]

    cards = await filter_feed_cards(
        getter,
        model="banana_pro",
        limit=1,
        offset=1,
        source="recent",
        viewer_user_id=10,
    )

    assert [card["id"] for card in cards] == [3]
    assert calls == [
        {
            "limit": 0,
            "offset": 0,
            "source": "recent",
            "viewer_user_id": 10,
        }
    ]


@pytest.mark.asyncio
async def test_other_model_must_be_selected_explicitly() -> None:
    clear_feed_model_cache()

    async def getter(**_kwargs):
        return [
            {"id": 1, "model": "banana_pro"},
            {"id": 2, "model": "seedream_5_pro"},
        ]

    default_cards = await filter_feed_cards(getter, source="recent")
    seedream_cards = await filter_feed_cards(
        getter,
        model="seedream_5_pro",
        source="recent",
    )

    assert [card["id"] for card in default_cards] == [1]
    assert [card["id"] for card in seedream_cards] == [2]


@pytest.mark.asyncio
async def test_viewer_specific_cards_do_not_share_cache() -> None:
    clear_feed_model_cache()
    calls: list[int | None] = []

    async def getter(**kwargs):
        viewer = kwargs.get("viewer_user_id")
        calls.append(viewer)
        return [{"id": 1, "model": "banana_pro", "is_mine": viewer == 7}]

    owner_cards = await filter_feed_cards(
        getter,
        source="recent",
        viewer_user_id=7,
    )
    stranger_cards = await filter_feed_cards(
        getter,
        source="recent",
        viewer_user_id=8,
    )

    assert owner_cards[0]["is_mine"] is True
    assert stranger_cards[0]["is_mine"] is False
    assert calls == [7, 8]


@pytest.mark.asyncio
async def test_model_picker_acknowledges_callback_before_database_lookup(monkeypatch) -> None:
    events: list[str] = []

    class Callback:
        data = "bfm:menu:r"
        from_user = type("User", (), {"id": 42})()
        message = type("Message", (), {})()

        async def answer(self, _text=None):
            events.append("answer")

    async def published_models():
        events.append("database")
        return [DEFAULT_FEED_MODEL]

    async def edit_reply_markup(*, reply_markup):
        assert reply_markup.inline_keyboard
        events.append("edit")

    Callback.message.edit_reply_markup = edit_reply_markup
    monkeypatch.setattr(
        "bot.handlers.feed_model_filter_compat._published_model_ids",
        published_models,
    )

    await select_feed_model(Callback())

    assert events == ["answer", "database", "edit"]
