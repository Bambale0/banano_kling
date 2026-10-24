"""Retail pricing and Telegram-admin regressions for Kling 4."""

import json
from copy import deepcopy
from itertools import count
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.fsm.storage.memory import MemoryStorage

from bot.handlers import admin
from bot.internal_admin_tariffs import _validate_tariff_config
from bot.kling4_tariff import (
    ADMIN_RATE_FIELDS,
    Kling4TariffNotConfigured,
    admin_rate_rows,
    format_admin_price,
    format_editor_admin_price,
    nominal_admin_quote,
    update_admin_rate,
    validate_kling4_model_config,
)

RATES = {
    "reference": {"720p": 1.0, "1080p": 1.5},
    "keyframe": {"720p": 2.0, "1080p": 2.5},
    "video": {"720p": 3.0, "1080p": 3.5},
}
_BOT_IDS = count(12000)


def price_config(rates=None):
    return {
        "credit_name_plural": "бананов",
        "credit_emoji": "🍌",
        "costs_reference": {
            "video_models": {"kling_4": {"billing_rates": rates or RATES}}
        },
    }


@pytest.mark.parametrize(
    ("category", "quality", "seconds", "expected"),
    [
        ("reference", "720p", "5", 5.0),
        ("reference", "1080p", "5", 7.5),
        ("keyframe", "720p", "7", 14.0),
        ("keyframe", "1080p", "7", 17.5),
        ("video", "720p", "12", 36.0),
        ("video", "1080p", "12", 42.0),
    ],
)
def test_kling4_all_admin_rate_cells(category, quality, seconds, expected):
    quote = nominal_admin_quote(
        {"tariff": category, "resolution": quality, "billed_seconds": seconds},
        price_config=price_config(),
    )
    assert quote["cost"] == expected
    assert quote["charge_cost"] == 0
    assert quote["profile"] == "admin"


def test_kling4_missing_or_partial_tariff_is_explicit_and_not_zero():
    provider = {"tariff": "reference", "resolution": "720p", "billed_seconds": "5"}
    with pytest.raises(Kling4TariffNotConfigured, match="не настроена"):
        nominal_admin_quote(provider, price_config={"costs_reference": {}})

    partial = {"reference": {"720p": 1.0}}
    publisher_config = json.loads(Path("data/price.json").read_text(encoding="utf-8"))
    publisher_config["costs_reference"]["video_models"]["kling_4"] = {
        "billing_rates": partial
    }
    _validate_tariff_config(publisher_config)
    with pytest.raises(ValueError, match="reference, keyframe and video"):
        validate_kling4_model_config({"billing_rates": partial})


def test_kling4_nominal_price_message_keeps_admin_charge_zero():
    quote = nominal_admin_quote(
        {"tariff": "video", "resolution": "1080p", "billed_seconds": "12"},
        price_config=price_config(),
    )
    assert format_admin_price(quote) == (
        "Цена: 42 🍌 бананов.\nДля администратора списание отключено."
    )


def test_kling4_editor_price_is_nominal_before_prompt_and_admin_is_free():
    recipe = {
        "mode": "reference",
        "input": {"resolution": "720p", "duration": 5, "image_urls": ["owned"]},
    }
    assert format_editor_admin_price(recipe, price_config=price_config()) == (
        "💰 Цена: <code>5</code> 🍌 бананов.\n"
        "Для администратора списание отключено."
    )


def test_kling4_editor_price_is_explicit_when_tariff_or_video_measurement_is_missing():
    recipe = {
        "mode": "reference",
        "input": {"resolution": "720p", "duration": 5, "image_urls": ["owned"]},
    }
    missing = format_editor_admin_price(
        recipe, price_config={"costs_reference": {}}
    )
    assert "Цена не настроена" in missing
    assert "Для администратора списание отключено" in missing
    assert "<code>0" not in missing

    recipe["input"]["video_urls"] = ["owned-video"]
    measured = format_editor_admin_price(recipe, price_config=price_config())
    assert "после проверки длительности" in measured
    assert "Для администратора списание отключено" in measured


class Manager:
    def __init__(self):
        self.config = {"costs_reference": {"video_models": {}}}

    def get_price_config(self):
        return deepcopy(self.config)

    def update_price_config(self, value):
        self.config = deepcopy(value)
        return True

    def get_video_cost(self, _model, _duration):
        return 1


def callbacks(markup):
    return {
        button.callback_data
        for row in markup.inline_keyboard
        for button in row
        if button.callback_data
    }


@pytest.fixture
def admin_ui(monkeypatch):
    manager = Manager()
    monkeypatch.setattr(admin, "preset_manager", manager)
    monkeypatch.setattr(admin, "is_admin", lambda _telegram_id: True)
    state = FSMContext(
        storage=MemoryStorage(),
        key=StorageKey(bot_id=next(_BOT_IDS), chat_id=999999999, user_id=999999999),
    )
    message = SimpleNamespace(edit_text=AsyncMock(), answer=AsyncMock())
    callback = SimpleNamespace(
        data="",
        from_user=SimpleNamespace(id=999999999),
        message=message,
        answer=AsyncMock(),
    )
    return manager, state, callback


@pytest.mark.asyncio
async def test_kling4_admin_navigation_save_and_readback(admin_ui):
    manager, state, callback = admin_ui
    assert "admin_prices_videos" in callbacks(admin._admin_price_menu_keyboard())
    assert "admin_prices_videos_g_kling_p0" in callbacks(
        admin._admin_video_prices_keyboard()
    )
    assert "admin_video_model_kling_4" in callbacks(
        admin._admin_video_prices_keyboard("kling", 0)
    )
    detail = callbacks(admin._admin_video_model_keyboard("kling_4"))
    assert {
        f"admin_price_video_kling_4_{field}" for field in ADMIN_RATE_FIELDS
    } <= detail

    callback.data = "admin_price_video_kling_4_rr720"
    await admin.admin_price_video(callback, state)
    assert (await state.get_data())["current_price_value"] is None
    incoming = SimpleNamespace(
        from_user=callback.from_user,
        text="1.25",
        answer=AsyncMock(),
    )
    await admin.admin_process_price_value(incoming, state)
    saved = manager.get_price_config()["costs_reference"]["video_models"]["kling_4"]
    assert saved["billing_rates"]["reference"]["720p"] == 1.25

    callback.data = "admin_price_video_kling_4_rr720"
    await admin.admin_price_video(callback, state)
    assert (await state.get_data())["current_price_value"] == 1.25
    assert admin_rate_rows(saved)[0][-1] == 1.25


@pytest.mark.asyncio
async def test_kling4_integer_rate_can_be_replaced_with_fraction(admin_ui):
    manager, state, callback = admin_ui
    manager.config = price_config()
    manager.config["costs_reference"]["video_models"]["kling_4"]["billing_rates"][
        "reference"
    ]["720p"] = 1

    callback.data = "admin_price_video_kling_4_rr720"
    await admin.admin_price_video(callback, state)
    assert (await state.get_data())["current_price_value"] == 1

    incoming = SimpleNamespace(
        from_user=callback.from_user,
        text="1.25",
        answer=AsyncMock(),
    )
    await admin.admin_process_price_value(incoming, state)

    saved = manager.get_price_config()["costs_reference"]["video_models"]["kling_4"]
    assert saved["billing_rates"]["reference"]["720p"] == 1.25


def test_kling4_miniapp_quote_displays_nominal_cost_and_admin_exemption():
    source = Path(
        "frontend/miniapp-v0/components/forms/kling4-form.tsx"
    ).read_text(encoding="utf-8")
    assert "{quote.cost}" in source
    assert "\\u0441\\u043f\\u0438\\u0441\\u0430\\u043d\\u0438\\u0435" in source


def test_kling4_manager_can_fill_all_six_cells_sequentially():
    manager = Manager()
    for index, field in enumerate(ADMIN_RATE_FIELDS, 1):
        assert update_admin_rate(manager, field, float(index)) is None
    saved = manager.get_price_config()["costs_reference"]["video_models"]["kling_4"]
    validate_kling4_model_config(saved)
