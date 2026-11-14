"""Regression for volume-backed price.json predating Seedream 5.5."""
import json

import pytest

from bot.handlers import admin
from bot.services import seedream55_pricing
from bot.services.preset_manager import PresetManager


def _manager(tmp_path, monkeypatch, extra=None):
    legacy = {
        "admin_ids": [123],
        "costs_reference": {
            "image_models": {"banana_2": 8, **(extra or {})},
            "video_models": {},
        },
        "packages": [],
    }
    path = tmp_path / "price.json"
    path.write_text(json.dumps(legacy), encoding="utf-8")
    manager = PresetManager(
        presets_path=str(tmp_path / "presets.json"), price_path=str(path),
    )
    monkeypatch.setattr(admin, "preset_manager", manager)
    monkeypatch.setattr(admin, "PRICE_PATH", path)
    monkeypatch.setattr(seedream55_pricing, "preset_manager", manager)
    return path, manager


def test_edit_2k_from_3_to_2_materializes_missing_seedream55_cells(tmp_path, monkeypatch):
    path, manager = _manager(tmp_path, monkeypatch)
    assert "seedream_55_2k" not in json.loads(path.read_text())["costs_reference"]["image_models"]
    assert manager.get_generation_cost("seedream_55") == 3

    original = admin._update_price_value("image", "seedream_55_2k", "cost", 2)
    assert original == 3
    saved = json.loads(path.read_text())["costs_reference"]["image_models"]
    assert saved["seedream_55_2k"] == 2
    assert saved["seedream_55_1k"] == 2
    assert saved["seedream_55_1_5k"] == 2.5
    assert saved["seedream_55_ref"] == 0.5
    assert saved["banana_2"] == 8
    assert manager.get_generation_cost("seedream_55") == 2
    assert seedream55_pricing.image_generation_cost(
        "seedream_55", "2K", reference_count=1,
    ) == 2.5


def test_edit_seedream55_preserves_existing_custom_cells(tmp_path, monkeypatch):
    path, manager = _manager(tmp_path, monkeypatch, {
        "seedream_55_1k": 1.75, "seedream_55_ref": 1.25,
    })
    old = admin._update_price_value("image", "seedream_55_2k", "cost", 2)
    assert old == 3
    saved = json.loads(path.read_text())["costs_reference"]["image_models"]
    assert saved["seedream_55_1k"] == 1.75
    assert saved["seedream_55_ref"] == 1.25
    assert saved["seedream_55_1_5k"] == 2.5
    assert manager.get_generation_cost("seedream_55") == 2


def test_other_nonexistent_image_key_still_fails_closed(tmp_path, monkeypatch):
    path, _ = _manager(tmp_path, monkeypatch)
    before = path.read_bytes()
    with pytest.raises(KeyError):
        admin._update_price_value("image", "does_not_exist", "cost", 2)
    assert path.read_bytes() == before


def test_failed_reload_reports_error_not_false_success(tmp_path, monkeypatch):
    path, manager = _manager(tmp_path, monkeypatch)
    monkeypatch.setattr(manager, "update_price_config", lambda config: False)
    with pytest.raises(RuntimeError, match="reload"):
        admin._update_price_value("image", "seedream_55_2k", "cost", 2)
    assert "seedream_55_2k" not in json.loads(path.read_text())["costs_reference"]["image_models"]


@pytest.mark.asyncio
async def test_admin_message_saves_two_bananas_and_confirms_real_price(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    path, manager = _manager(tmp_path, monkeypatch)
    monkeypatch.setattr(admin, "is_admin", lambda user_id: user_id == 123)
    state = SimpleNamespace(
        get_data=AsyncMock(return_value={
            "price_target": "image",
            "price_key": "seedream_55_2k",
            "price_field": "cost",
            "current_price_value": manager.get_generation_cost("seedream_55"),
            "return_to": "admin_prices_images",
        }),
        clear=AsyncMock(),
    )
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=123),
        text="2",
        answer=AsyncMock(),
    )
    await admin.admin_process_price_value(message, state)
    assert "✅" in message.answer.await_args.args[0]
    assert "Стало: <code>2</code>" in message.answer.await_args.args[0]
    state.clear.assert_awaited_once()
    assert json.loads(path.read_text())["costs_reference"]["image_models"]["seedream_55_2k"] == 2
    assert seedream55_pricing.quality_prices()["2K"] == 2


@pytest.mark.asyncio
async def test_admin_message_never_confirms_when_save_failed(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    _, manager = _manager(tmp_path, monkeypatch)
    monkeypatch.setattr(admin, "is_admin", lambda user_id: user_id == 123)
    monkeypatch.setattr(manager, "update_price_config", lambda config: False)
    state = SimpleNamespace(
        get_data=AsyncMock(return_value={
            "price_target": "image",
            "price_key": "seedream_55_2k",
            "price_field": "cost",
            "current_price_value": 3,
            "return_to": "admin_prices_images",
        }),
        clear=AsyncMock(),
    )
    message = SimpleNamespace(
        from_user=SimpleNamespace(id=123), text="2", answer=AsyncMock(),
    )
    await admin.admin_process_price_value(message, state)
    assert "❌" in message.answer.await_args.args[0]
    assert "✅" not in message.answer.await_args.args[0]
    state.clear.assert_awaited_once()


def test_existing_image_prices_still_update(tmp_path, monkeypatch):
    path, manager = _manager(tmp_path, monkeypatch)
    assert admin._update_price_value("image", "banana_2", "cost", 5) == 8
    assert manager.get_generation_cost("banana_2") == 5
    assert json.loads(path.read_text())["costs_reference"]["image_models"]["banana_2"] == 5
