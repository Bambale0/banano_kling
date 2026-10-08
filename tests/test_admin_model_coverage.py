"""Isolated callback and tariff tests: never load live credentials or write prices."""
import ast
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from bot.quality_pricing import SEEDREAM_5_PRO_QUALITY_COSTS, refresh_quality_pricing

ROOT = Path(__file__).resolve().parents[1]
COMPAT = ROOT / "bot/handlers/banana_resolution_pricing_compat.py"


def functions(path, names, namespace):
    nodes = []
    for node in ast.parse(path.read_text()).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names:
            node.decorator_list = []
            nodes.append(node)
    tree = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), *nodes], type_ignores=[])
    exec(compile(ast.fix_missing_locations(tree), str(path), "exec"), namespace)
    return namespace


def test_seedream_config_refresh_preserves_imported_mapping_and_defaults():
    identity = id(SEEDREAM_5_PRO_QUALITY_COSTS)
    try:
        refresh_quality_pricing({})
        assert SEEDREAM_5_PRO_QUALITY_COSTS["basic"] == 2
        assert SEEDREAM_5_PRO_QUALITY_COSTS["high"] == 2.5
        refresh_quality_pricing({"costs_reference": {"seedream_5_pro_quality_costs": {"basic": 4.5, "high": 7}}})
        assert id(SEEDREAM_5_PRO_QUALITY_COSTS) == identity
        assert SEEDREAM_5_PRO_QUALITY_COSTS == {"basic": 4.5, "BASIC": 4.5, "high": 7, "HIGH": 7}
    finally:
        refresh_quality_pricing()


@pytest.mark.parametrize("value", [True, -1, 0, "4", float("inf"), float("nan")])
def test_seedream_invalid_tariffs_fall_back(value):
    try:
        refresh_quality_pricing({"costs_reference": {"seedream_5_pro_quality_costs": {"basic": value}}})
        assert SEEDREAM_5_PRO_QUALITY_COSTS["basic"] == 2
    finally:
        refresh_quality_pricing()


def test_seedream_save_changes_only_explicit_tier_and_refreshes_catalog():
    original = {"costs_reference": {"image_models": {"seedream_edit": 19},
                "video_models": {"seedance_2_5": {"quality_costs": {"480p": 5, "720p": 7, "1080p": 13}}},
                "image_quality_costs": {"1K": 1.5, "2K": 1.5, "4K": 2}},
                "packages": [{"id": "keep", "credits": 99}]}
    written = []
    catalog = SimpleNamespace(IMAGE_MODELS=[{"id": "seedream_5_pro"}, {"id": "banana_pro"}])
    ns = functions(COMPAT, {"_patched_update_price_value", "_refresh_loaded_miniapp_catalog"}, {
        "_admin_module": SimpleNamespace(_read_price_config=lambda: deepcopy(original)),
        "_original_update_price_value": lambda *args: None,
        "preset_manager": SimpleNamespace(update_price_config=lambda value: written.append(deepcopy(value)) or True),
        "refresh_quality_pricing": refresh_quality_pricing,
        "SEEDREAM_5_PRO_QUALITY_COSTS": SEEDREAM_5_PRO_QUALITY_COSTS,
        "QUALITY_COSTS": {},
        "sys": SimpleNamespace(modules={"bot.miniapp": catalog}),
    })
    from bot.quality_pricing import QUALITY_COSTS
    ns["QUALITY_COSTS"] = QUALITY_COSTS
    try:
        refresh_quality_pricing(original)
        assert ns["_patched_update_price_value"]("seedream_quality", "seedream_5_pro", "high", 8) == 2.5
        expected = deepcopy(original)
        expected["costs_reference"]["seedream_5_pro_quality_costs"] = {"high": 8}
        assert written == [expected]
        assert catalog.IMAGE_MODELS[0]["quality_costs"] == {"basic": 2, "high": 8}
        assert SEEDREAM_5_PRO_QUALITY_COSTS["HIGH"] == 8
    finally:
        refresh_quality_pricing()


@pytest.mark.asyncio
@pytest.mark.parametrize("authorized", [True, False])
@pytest.mark.parametrize("name", ["admin_seedream_quality_prices", "admin_seedream_quality_value"])
async def test_seedream_callbacks_share_authority(name, authorized):
    ns = functions(COMPAT, {name, "_is_price_admin", "_format_cost"}, {
        "_admin_module": SimpleNamespace(is_admin=lambda uid: authorized),
        "SEEDREAM_5_PRO_QUALITY_COSTS": {"basic": 2, "high": 2.5},
        "types": SimpleNamespace(InlineKeyboardMarkup=lambda **kw: kw, InlineKeyboardButton=lambda **kw: kw),
        "AdminStates": SimpleNamespace(waiting_price_value="waiting"),
    })
    callback = SimpleNamespace(from_user=SimpleNamespace(id=123), data="admin_seedream_quality_high",
        answer=AsyncMock(), message=SimpleNamespace(edit_text=AsyncMock()))
    state = SimpleNamespace(clear=AsyncMock(), set_state=AsyncMock(), update_data=AsyncMock())
    await ns[name](callback, state)
    if authorized:
        callback.message.edit_text.assert_awaited_once()
        if name.endswith("_value"):
            assert state.update_data.await_args.kwargs["price_target"] == "seedream_quality"
            assert state.update_data.await_args.kwargs["current_price_value"] == 2.5
    else:
        callback.answer.assert_awaited_once_with("⛔ Нет доступа")
        callback.message.edit_text.assert_not_awaited()
        state.set_state.assert_not_awaited()


@pytest.mark.asyncio
async def test_price_save_rechecks_admin_before_state_or_write():
    ns = functions(ROOT / "bot/handlers/admin.py", {"admin_process_price_value"}, {"is_admin": lambda uid: False})
    state = SimpleNamespace(clear=AsyncMock(), get_data=AsyncMock())
    message = SimpleNamespace(from_user=SimpleNamespace(id=123), answer=AsyncMock())
    await ns["admin_process_price_value"](message, state)
    state.get_data.assert_not_awaited()
    state.clear.assert_awaited_once()
    message.answer.assert_awaited_once_with("⛔ Нет доступа")


def test_higgs_prices_menu_opens_existing_authenticated_management():
    ns = functions(ROOT / "bot/handlers/admin.py", {"_admin_price_menu_keyboard"}, {
        "config": SimpleNamespace(mini_app_url="https://example.test"),
        "_mini_app_url_with_start_param": lambda value: "https://example.test/?tgWebAppStartParam=" + value,
        "types": SimpleNamespace(InlineKeyboardMarkup=lambda **kw: kw, InlineKeyboardButton=lambda **kw: kw,
                                  WebAppInfo=lambda **kw: kw),
    })
    button = ns["_admin_price_menu_keyboard"]()["inline_keyboard"][0][0]
    assert "Higgsfield" in button["text"]
    assert button["web_app"]["url"].endswith("genjutsu_admin")
    ns["config"].mini_app_url = ""
    assert not any("web_app" in button for row in ns["_admin_price_menu_keyboard"]()["inline_keyboard"] for button in row)


@pytest.mark.parametrize("model", ["avatar_std", "avatar_pro"])
def test_avatar_view_does_not_write_and_save_preserves_other_durations(model):
    original = {"costs_reference": {"video_models": {"seedance_2_5": {"quality_costs": {"480p": 5, "720p": 7, "1080p": 13}}},
        "video_duration_costs": {"3": 9, "5": 15, "10": 30, "15": 45}, "legacy_keys": {}}}
    config = deepcopy(original)
    writes = []
    # Load the real pure pricing methods, without importing module-level runtime manager.
    source = ast.parse((ROOT / "bot/services/preset_manager.py").read_text())
    cls = next(n for n in source.body if isinstance(n, ast.ClassDef) and n.name == "PresetManager")
    selected = {n.name: n for n in cls.body if isinstance(n, ast.FunctionDef)}
    tree = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
                           ast.ClassDef(name="Pricing", bases=[], keywords=[], decorator_list=[],
                            body=[selected[n] for n in ["_costs_reference", "_video_costs", "_legacy_costs",
                                "normalize_video_model_key", "_clamp_video_duration", "_format_cost", "get_video_cost"]])],
                      type_ignores=[])
    price_ns = {"CANONICAL_VIDEO_ALIASES": {}, "DEFAULT_VIDEO_COST": 8}
    exec(compile(ast.fix_missing_locations(tree), "<pure-pricing>", "exec"), price_ns)
    manager = price_ns["Pricing"]()
    manager._price_config = config
    manager.get_price_config = lambda: deepcopy(config)
    def save(value):
        writes.append(deepcopy(value))
        config.clear()
        config.update(value)
        return True
    manager.update_price_config = save
    before = {duration: manager.get_video_cost(model, duration) for duration in range(1, 36)}
    ns = functions(ROOT / "bot/handlers/admin.py", {"_admin_video_price_models", "_update_price_value"}, {
        "AVATAR_ADMIN_PRICE_MODELS": {"avatar_std", "avatar_pro"},
        "SEEDANCE_ADMIN_PRICE_MODELS": {}, "preset_manager": manager,
        "_read_price_config": lambda: deepcopy(config),
    })
    assert ns["_admin_video_price_models"]()[model]["duration_costs"]["5"] == before[5]
    assert config == original and not writes
    assert ns["_update_price_value"]("video", model, "5", 21) == before[5]
    expected = deepcopy(original)
    expected["costs_reference"]["video_models"][model] = {"duration_costs": {"5": 21}}
    assert writes == [expected]
    for duration in range(1, 36):
        assert manager.get_video_cost(model, duration) == (21 if duration == 5 else before[duration])
    with pytest.raises(KeyError):
        ns["_update_price_value"]("video", model, "persec", 4)
    assert len(writes) == 1


@pytest.mark.parametrize("path", ["bot/miniapp.py", "bot/handlers/generation.py"])
def test_seedream_both_charge_surfaces_follow_shared_runtime_tariffs(path):
    ns = functions(ROOT / path, {"_resolve_image_unit_cost"}, {
        "SEEDREAM_5_PRO_QUALITY_COSTS": {"basic": 4, "BASIC": 4, "high": 9, "HIGH": 9},
        "QUALITY_COSTS": {}, "preset_manager": SimpleNamespace(get_generation_cost=lambda model: 17),
    })
    assert ns["_resolve_image_unit_cost"]("seedream_5_pro", "basic") == 4
    assert ns["_resolve_image_unit_cost"]("seedream_5_pro", "HIGH") == 9
    assert ns["_resolve_image_unit_cost"]("seedream_edit", "4K") == 17


def test_base_catalog_models_have_an_admin_tariff_destination():
    import json
    config = json.loads((ROOT / "data/price.json").read_text())["costs_reference"]
    source = ast.parse((ROOT / "bot/miniapp.py").read_text())
    catalog = {}
    for node in source.body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and node.targets[0].id in {"IMAGE_MODELS", "VIDEO_MODELS"}:
            catalog[node.targets[0].id] = [
                ast.literal_eval(value) for model in node.value.elts
                for key, value in zip(model.keys, model.values) if isinstance(key, ast.Constant) and key.value == "id"
            ]
    aliases = {}
    for node in ast.parse((ROOT / "bot/services/preset_manager.py").read_text()).body:
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) and node.targets[0].id in {"CANONICAL_IMAGE_ALIASES", "CANONICAL_VIDEO_ALIASES"}:
            aliases[node.targets[0].id] = ast.literal_eval(node.value)
    for model in catalog["IMAGE_MODELS"]:
        assert model == "seedream_5_pro" or aliases["CANONICAL_IMAGE_ALIASES"].get(model, model) in config["image_models"]
    for model in catalog["VIDEO_MODELS"]:
        assert model in {"avatar_std", "avatar_pro"} or aliases["CANONICAL_VIDEO_ALIASES"].get(model, model) in config["video_models"]
