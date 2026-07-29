from __future__ import annotations

import pytest

from bot.handlers.feed_model_filter_compat import (
    DEFAULT_FEED_MODEL,
    feed_model_matches,
    filter_feed_cards,
    normalize_feed_model,
)


def test_banana_pro_aliases_share_one_feed_tab() -> None:
    assert normalize_feed_model(None) == DEFAULT_FEED_MODEL
    assert normalize_feed_model("banana_pro") == DEFAULT_FEED_MODEL
    assert normalize_feed_model("nano-banana-pro") == DEFAULT_FEED_MODEL
    assert normalize_feed_model("gemini-3-pro-image-preview") == DEFAULT_FEED_MODEL
    assert feed_model_matches("nano-banana-pro", "banana_pro") is True
    assert feed_model_matches("banana_2", "banana_pro") is False


@pytest.mark.asyncio
async def test_filter_feed_cards_filters_before_pagination() -> None:
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
