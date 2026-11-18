"""Astro pricing admin UI: authenticated editor, atomic persistence, no billing switch."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot.handlers import admin
from bot.services.preset_manager import PresetManager
from bot.services.astro_pricing import (
    ASTRO_SERVICE_LABELS,
    get_astro_service_price,
    update_astro_service_price,
    validate_astro_service_prices,
)


def manager_fixture(tmp_path, monkeypatch):
    payload = {
        "admin_ids": [1234],
        "currency": "RUB",
        "packages": [{"id": "starter", "name": "Старт", "credits": 10, "price_rub": 99}],
        "costs_reference": {"image_models": {"banana_2": 2}, "video_models": {"kling": {"base": 5}}},
        "service_prices": {"video_prompt": 3, "photo_prompt_rub": 1},
        "support_contact": "@test",
    }
    path = tmp_path / "price.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    manager = PresetManager(presets_path=str(tmp_path / "presets.json"), price_path=str(path))
    monkeypatch.setattr(admin, "preset_manager", manager)
    monkeypatch.setattr(admin, "is_admin", lambda uid: uid == 1234)
    return manager, path, payload


def test_all_seven_astro_services_visible_in_admin_price_menu():
    root = admin._admin_price_menu_keyboard()
    assert any(b.callback_data == "admin_prices_astro"
               for row in root.inline_keyboard for b in row)
    rows = admin._admin_astro_prices_keyboard().inline_keyboard
    keys = {b.callback_data for row in rows for b in row}
    assert {f"admin_price_astro_{name}" for name in ASTRO_SERVICE_LABELS} <= keys


@pytest.mark.asyncio
async def test_admin_astro_editor_sets_state_without_charging(tmp_path, monkeypatch):
    manager, path, _ = manager_fixture(tmp_path, monkeypatch)
    state = SimpleNamespace(clear=AsyncMock(), set_state=AsyncMock(), update_data=AsyncMock())
    callback = SimpleNamespace(from_user=SimpleNamespace(id=1234),
                               data="admin_price_astro_natal",
                               message=SimpleNamespace(edit_text=AsyncMock()),
                               answer=AsyncMock())
    await admin.admin_astro_price_edit(callback, state)
    assert state.update_data.await_args.kwargs["price_target"] == "astro"
    assert state.update_data.await_args.kwargs["price_key"] == "natal"
    assert "не настроена" in callback.message.edit_text.await_args.args[0]
    assert "service_prices" not in json.loads(path.read_text())


@pytest.mark.asyncio
async def test_admin_price_message_persists_seven_service_tariff_and_preserves_others(tmp_path, monkeypatch):
    manager, path, original = manager_fixture(tmp_path, monkeypatch)
    state = SimpleNamespace(get_data=AsyncMock(return_value={
        "price_target": "astro", "price_key": "natal", "price_field": "cost",
        "current_price_value": None, "return_to": "admin_prices_astro",
    }), clear=AsyncMock())
    message = SimpleNamespace(from_user=SimpleNamespace(id=1234), text="75,5", answer=AsyncMock())
    await admin.admin_process_price_value(message, state)
    saved = json.loads(path.read_text())
    assert saved["service_prices"]["astro"]["natal"] == 75.5
    assert saved["service_prices"]["video_prompt"] == 3
    assert saved["admin_ids"] == [1234]
    assert saved["support_contact"] == "@test"
    assert get_astro_service_price(manager.get_price_config(), "natal") == 75.5
    assert "✅" in message.answer.await_args.args[0]
    state.clear.assert_awaited_once()


@pytest.mark.asyncio
async def test_lost_update_rejected_if_admin_saw_old_price(tmp_path, monkeypatch):
    manager, path, _ = manager_fixture(tmp_path, monkeypatch)
    await update_astro_service_price(manager, "natal", 20, expected_old=None)
    with pytest.raises(ValueError, match="changed"):
        await update_astro_service_price(manager, "natal", 30, expected_old=None)
    assert get_astro_service_price(json.loads(path.read_text()), "natal") == 20


@pytest.mark.asyncio
async def test_price_update_rolls_back_if_reload_fails(tmp_path, monkeypatch):
    manager, path, _ = manager_fixture(tmp_path, monkeypatch)
    old_bytes = path.read_bytes()
    monkeypatch.setattr(manager, "reload", lambda: False)
    with pytest.raises(RuntimeError, match="reload"):
        await update_astro_service_price(manager, "karma", 10, expected_old=None)
    assert path.read_bytes() == old_bytes


@pytest.mark.parametrize("bad", [0, -1, float("nan"), float("inf"), True, "100", 0.001])
def test_invalid_price_rejected_without_mutating_config(bad):
    payload = {"service_prices": {"astro": {"natal": bad}}}
    with pytest.raises(ValueError):
        validate_astro_service_prices(payload)


def test_unknown_service_and_unset_price_are_not_billed_or_silently_defaulted():
    assert get_astro_service_price({"service_prices": {}}, "natal") is None
    with pytest.raises(ValueError):
        get_astro_service_price({"service_prices": {}}, "unknown")


@pytest.mark.asyncio
async def test_non_admin_cannot_edit_astro_price(tmp_path, monkeypatch):
    manager, path, _ = manager_fixture(tmp_path, monkeypatch)
    state = SimpleNamespace(clear=AsyncMock(), set_state=AsyncMock(), update_data=AsyncMock())
    callback = SimpleNamespace(from_user=SimpleNamespace(id=987), data="admin_price_astro_natal",
                               message=SimpleNamespace(edit_text=AsyncMock()), answer=AsyncMock())
    await admin.admin_astro_price_edit(callback, state)
    state.set_state.assert_not_awaited()
    callback.answer.assert_awaited_once()
    assert "astro" not in json.loads(path.read_text())["service_prices"]
