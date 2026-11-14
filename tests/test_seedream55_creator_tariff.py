"""Creator tariff: independent Seedream 5.5 output + reference charges."""

from copy import deepcopy
from types import SimpleNamespace
import json

import aiosqlite
from unittest.mock import AsyncMock

import pytest

from bot import creator_tariff, creator_tariff_display
from bot.handlers import creator_tariff_admin, generation
from bot.keyboards import get_image_model_selection_keyboard
from bot.services import seedream55_pricing, seedream55_results
from bot.services.preset_manager import preset_manager


@pytest.fixture
def creator55(monkeypatch):
    data = deepcopy(preset_manager.get_price_config())
    # All prices are fixture values, NOT application defaults.
    image_prices = data.setdefault("costs_reference", {}).setdefault("image_models", {})
    image_prices.update({
        "seedream_55_1k": 4.0,
        "seedream_55_1_5k": 5.0,
        "seedream_55_2k": 6.0,
        "seedream_55_ref": 1.25,
    })
    raw = data.get("creator_tariff", {})
    raw.update({"enabled": True})
    raw["video_models"] = {
        model: {"quality_costs": {quality: 1.0 for quality in qualities}}
        for model, qualities in creator_tariff._required_qualities().items()
    }
    raw["image_models"] = {}
    creator_models = raw["image_models"]
    creator_models["seedream_55"] = {
        "quality_costs": {"1K": 2.0, "1.5K": 2.75, "2K": 3.5},
        "reference_unit_cost": 0.5,
    }
    data["creator_tariff"] = raw
    monkeypatch.setattr(preset_manager, "_price_config", data)
    assert creator_tariff.creator_tariff_status()["configured"], creator_tariff.creator_tariff_status()["errors"]
    return data


def test_model_is_in_creator_editor_without_duplicate_layers_model(creator55):
    status = creator_tariff.creator_tariff_status()
    assert status["image_qualities"]["seedream_55"] == ["1K", "1.5K", "2K"]
    options = creator_tariff_admin._editable_qualities(status)
    assert options["seedream_55"] == ["1K", "1.5K", "2K", "ref"]
    assert "seedream_55_layers" not in options
    assert creator_tariff_admin.MODEL_LABELS["seedream_55"] == "Seedream 5.5"


@pytest.mark.parametrize("model,quality,refs,maximum,expected", [
    ("seedream_55", "1K", 0, 30, 2),
    ("seedream_55", "1.5K", 1, 30, 3.25),
    ("seedream_55", "2K", 10, 30, 8.5),
    ("seedream_55_layers", "auto", 1, 4, 14.5),
    ("seedream_55_layers", "1K", 1, 7, 14.5),
])
def test_creator_quote_uses_one_output_rate_per_result_and_one_ref_rate(
    creator55, model, quality, refs, maximum, expected,
):
    assert seedream55_pricing.image_generation_cost(
        model, quality, reference_count=refs, max_images=maximum, tariff="creator",
    ) == expected


def test_standard_and_admin_rates_stay_unchanged(creator55):
    assert seedream55_pricing.image_generation_cost(
        "seedream_55", "2K", reference_count=2, tariff="standard",
    ) == 8.5
    assert seedream55_pricing.image_generation_cost(
        "seedream_55_layers", "auto", reference_count=1, max_images=3,
        tariff="admin",
    ) == 19.25
    assert creator_tariff.resolve_image_unit_cost(
        "banana_pro", "2K", tariff="creator",
    ) == creator_tariff.resolve_image_unit_cost(
        "banana_pro", "2K", tariff="standard",
    )


def test_partial_creator_override_falls_back_without_disabling_membership(creator55):
    item = creator55["creator_tariff"]["image_models"]["seedream_55"]
    item["quality_costs"].pop("1K")
    item.pop("reference_unit_cost")
    assert creator_tariff.creator_tariff_status()["configured"]
    assert seedream55_pricing.image_generation_cost(
        "seedream_55", "1K", reference_count=2, tariff="creator",
    ) == 6.5
    creator55["creator_tariff"]["enabled"] = False
    assert seedream55_pricing.image_generation_cost(
        "seedream_55", "2K", reference_count=1, tariff="creator",
    ) == 7.25


@pytest.mark.parametrize("bad", [0, -0.01, True, float("inf"), float("nan"), "1.0"])
def test_creator_reference_unit_price_rejects_invalid_values(creator55, bad):
    raw = deepcopy(creator55["creator_tariff"])
    raw["image_models"]["seedream_55"]["reference_unit_cost"] = bad
    with pytest.raises(ValueError):
        creator_tariff.validate_creator_tariff_config(raw)


def test_creator_price_rejects_duplicate_internal_layer_model(creator55):
    raw = deepcopy(creator55["creator_tariff"])
    raw["image_models"]["seedream_55_layers"] = {"quality_costs": {"2K": 1}}
    with pytest.raises(ValueError):
        creator_tariff.validate_creator_tariff_config(raw)


def test_creator_price_editor_metadata_is_personal_without_global_leak(creator55):
    for model in ("seedream_55", "seedream_55_layers"):
        original = {
            "id": model,
            "cost": 6,
            "quality_costs": {"1K": 4, "1.5K": 5, "2K": 6},
            "reference_unit_cost": 1.25,
        }
        copy = deepcopy(original)
        creator = creator_tariff_display.price_image_model_metadata(original, tariff="creator")
        ordinary = creator_tariff_display.price_image_model_metadata(original, tariff="standard")
        assert creator["quality_costs"] == {"1K": 2, "1.5K": 2.75, "2K": 3.5}
        assert creator["reference_unit_cost"] == 0.5
        assert creator["cost"] == 3.5
        assert ordinary["quality_costs"] == {"1K": 4, "1.5K": 5, "2K": 6}
        assert ordinary["reference_unit_cost"] == 1.25
        assert original == copy


@pytest.mark.asyncio
async def test_telegram_and_miniapp_quotes_use_server_selected_creator_tariff(creator55, monkeypatch):
    monkeypatch.setattr(creator_tariff_display, "get_actor_tariff", AsyncMock(return_value="creator"))
    from bot import miniapp as m
    assert generation._resolve_image_unit_cost(
        "seedream_55", "2K", tariff="creator", reference_count=2,
    ) == 4.5
    assert m._resolve_image_unit_cost(
        "seedream_55_layers", "2K", tariff="creator", reference_count=1, max_images=4,
    ) == 14.5
    assert await m._resolve_actor_image_unit_cost(
        12345, "seedream_55", "2K", reference_count=2,
    ) == 4.5


def test_telegram_model_list_shows_creator_price_and_only_one_seedream55(creator55):
    kb = get_image_model_selection_keyboard("seedream_55", tariff="creator")
    found = [
        button for row in kb.inline_keyboard for button in row
        if "Seedream 5.5" in button.text
    ]
    assert len(found) == 1
    assert found[0].callback_data == "model_seedream_55"
    assert "3.5🍌" in found[0].text


def test_layers_snapshot_uses_unchanged_creator_quote_after_price_edit(creator55):
    reserved = seedream55_pricing.image_generation_cost(
        "seedream_55_layers", "2K", reference_count=1, max_images=9, tariff="creator",
    )
    rate = seedream55_pricing.image_generation_cost(
        "seedream_55", "2K", tariff="creator",
    )
    ref = seedream55_pricing.image_generation_cost(
        "seedream_55", "2K", reference_count=1, tariff="creator",
    ) - rate
    assert reserved == 32
    assert round(4 * rate + ref, 3) == 14.5
    assert reserved - (4 * rate + ref) == 17.5


@pytest.mark.asyncio
async def test_layers_settlement_uses_frozen_creator_rates_after_admin_change(
    creator55, monkeypatch, tmp_path,
):
    """Accepted debit and refund cannot be repriced by later config edits."""
    database_path = str(tmp_path / "creator_layers.sqlite")
    reserved = seedream55_pricing.image_generation_cost(
        "seedream_55_layers", "2K", reference_count=1,
        max_images=9, tariff="creator",
    )
    unit_out = seedream55_pricing.image_generation_cost(
        "seedream_55", "2K", tariff="creator",
    )
    unit_in = seedream55_pricing.image_generation_cost(
        "seedream_55", "2K", reference_count=1, tariff="creator",
    ) - unit_out
    async with aiosqlite.connect(database_path) as db:
        await db.execute(
            "CREATE TABLE users (id INTEGER PRIMARY KEY, credits REAL, updated_at TEXT)"
        )
        await db.execute(
            """CREATE TABLE generation_tasks (
              id INTEGER PRIMARY KEY, task_id TEXT, user_id INTEGER,
              model TEXT, status TEXT, request_data TEXT,
              result_url TEXT, result_urls TEXT, cost REAL,
              updated_at TEXT, completed_at TEXT)"""
        )
        await db.execute("INSERT INTO users (id, credits) VALUES (7, ?)", (100-reserved,))
        await db.execute(
            """INSERT INTO generation_tasks
            (id,task_id,user_id,model,status,request_data,cost)
            VALUES (1,'creator-task',7,'seedream_55_layers','pending',?,?)""",
            (json.dumps({
                "seedream55_tariff": "creator",
                "seedream55_reserved_cost": reserved,
                "seedream55_output_unit_cost": unit_out,
                "seedream55_input_unit_cost": unit_in,
                "img_layers_max_images": 9,
                "seedream55_charge_exempt": False,
            }), reserved),
        )
        await db.commit()

    async def task_lookup(_id):
        async with aiosqlite.connect(database_path) as db:
            db.row_factory = aiosqlite.Row
            row = await (await db.execute(
                "SELECT * FROM generation_tasks WHERE task_id='creator-task'"
            )).fetchone()
        return SimpleNamespace(**dict(row))

    monkeypatch.setattr(seedream55_results, "get_task_by_id", task_lookup)
    monkeypatch.setattr(seedream55_results, "DATABASE_PATH", database_path)
    # Simulate administrator changing Creator prices after accepted debit.
    prices = creator55["creator_tariff"]["image_models"]["seedream_55"]
    prices["quality_costs"]["2K"] = 0.25
    prices["reference_unit_cost"] = 0.1

    urls = [f"https://example.com/layer-{i}.png" for i in range(4)]
    assert await seedream55_results.settle_layers(
        "creator-task", urls, [{} for _ in urls], "https://example.com/archive.zip",
    )
    assert await seedream55_results.settle_layers(
        "creator-task", urls, [{} for _ in urls], "https://example.com/archive.zip",
    )
    async with aiosqlite.connect(database_path) as db:
        user_credits = (await (await db.execute(
            "SELECT credits FROM users WHERE id=7"
        )).fetchone())[0]
        row = await (await db.execute(
            "SELECT cost,request_data FROM generation_tasks WHERE id=1"
        )).fetchone()
    assert row[0] == 14.5
    assert json.loads(row[1])["seedream55_settlement"]["refund"] == 17.5
    assert user_credits == 85.5  # exactly one refund of unused reserve
