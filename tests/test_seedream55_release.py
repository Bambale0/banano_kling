"""TDD regression: complete layer output, archive, and exactly-once refund."""
import json
from types import SimpleNamespace

import aiosqlite
import pytest

from bot.services import seedream55_results as results
from bot.services.seedream55_pricing import image_generation_cost


def test_reference_pricing_and_layers_cap():
    assert image_generation_cost("seedream_55", "1K", reference_count=10) > image_generation_cost("seedream_55", "1K", reference_count=1)
    max_quote = image_generation_cost("seedream_55_layers", "2K", reference_count=1, max_images=30)
    assert max_quote == 30 * image_generation_cost("seedream_55", "2K", reference_count=0) + 0.5


def test_complete_layer_result_preserves_all_urls_and_metadata():
    raw = {
        "resultUrls": [
            "https://tempfile.aiquickdraw.com/seedream55/base.png",
            "https://tempfile.aiquickdraw.com/seedream55/shape.png",
        ],
        "resultObject": {"layers_data": [
            {"z_index": 0, "name": "Background", "size": "1024x1024"},
            {"z_index": 1, "name": "Logo", "bounding_box": {"absolute": [1, 2, 3, 4]}},
        ]},
    }
    urls, metadata = results.extract_layers(raw)
    assert urls == raw["resultUrls"]
    assert metadata[1]["name"] == "Logo"
    assert metadata[1]["bounding_box"] == {"absolute": [1, 2, 3, 4]}
    assert metadata[0]["z_index"] == 0


@pytest.mark.parametrize("urls", [
    [], ["https://tempfile.aiquickdraw.com/a.png"],
    ["https://tempfile.aiquickdraw.com/a.png"] * 2,
    ["file:///tmp/a.png", "https://tempfile.aiquickdraw.com/b.png"],
])
def test_incomplete_or_malformed_layer_result_rejected(urls):
    with pytest.raises(ValueError):
        results.extract_layers({"resultUrls": urls})


@pytest.mark.asyncio
async def test_layer_settlement_refunds_once_and_persists_all_urls(tmp_path, monkeypatch):
    db_path = str(tmp_path / "task.sqlite")
    async with aiosqlite.connect(db_path) as conn:
        await conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, credits REAL, updated_at TEXT)")
        await conn.execute("""CREATE TABLE generation_tasks (
            id INTEGER PRIMARY KEY, task_id TEXT, user_id INTEGER,
            model TEXT, status TEXT, request_data TEXT,
            result_url TEXT, result_urls TEXT, cost REAL,
            updated_at TEXT, completed_at TEXT)""")
        await conn.execute("INSERT INTO users (id,credits) VALUES (7,79.5)")
        payload = json.dumps({
            "seedream55_reserved_cost": 20.5,
            "seedream55_output_unit_cost": 2.0,
            "seedream55_input_unit_cost": 0.5,
            "img_layers_max_images": 10,
            "seedream55_charge_exempt": False,
        })
        await conn.execute(
            "INSERT INTO generation_tasks(id,task_id,user_id,model,status,request_data,cost) VALUES(1,'task',7,'seedream_55_layers','pending',?,20.5)",
            (payload,),
        )
        await conn.commit()

    async def find_task(_task_id):
        async with aiosqlite.connect(db_path) as conn:
            conn.row_factory = aiosqlite.Row
            row = await (await conn.execute("SELECT * FROM generation_tasks WHERE task_id='task'")).fetchone()
            return SimpleNamespace(**dict(row))

    monkeypatch.setattr(results, "get_task_by_id", find_task)
    monkeypatch.setattr(results, "DATABASE_PATH", db_path)
    urls = [f"https://neuromixbot.com/uploads/layer-{i}.png" for i in range(3)]
    assert await results.settle_layers("task", urls, [{}, {}, {}], "https://neuromixbot.com/archive.zip")
    assert await results.settle_layers("task", urls, [{}, {}, {}], "https://neuromixbot.com/archive.zip")
    async with aiosqlite.connect(db_path) as conn:
        credits = (await (await conn.execute("SELECT credits FROM users WHERE id=7")).fetchone())[0]
        row = await (await conn.execute("SELECT result_urls,cost,status,request_data FROM generation_tasks WHERE id=1")).fetchone()
    assert credits == 93.5  # 20.5 reserved; only 6.5 actually used => 14 refunded
    assert json.loads(row[0]) == urls
    assert row[1] == 6.5
    assert row[2] == "completed"
    assert json.loads(row[3])["seedream55_settlement"]["refund"] == 14.0

def test_old_persistent_price_file_supports_seedream55_without_overwriting(tmp_path):
    from bot.services.preset_manager import PresetManager
    persisted = {"costs_reference": {"image_models": {"banana_2": 4.5}}, "packages": []}
    price_path = tmp_path / "price.json"
    price_path.write_text(json.dumps(persisted), encoding="utf-8")
    manager = PresetManager(presets_path=str(tmp_path / "missing.json"), price_path=str(price_path))
    assert manager.get_generation_cost("banana_2") == 4.5
    prices = manager.get_price_config()["costs_reference"]["image_models"]
    assert prices["seedream_55_2k"] == 3.0
    assert prices["seedream_55_ref"] == 0.5
    assert json.loads(price_path.read_text()) == persisted  # no startup write
