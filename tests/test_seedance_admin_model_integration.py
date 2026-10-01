from __future__ import annotations

import json
from pathlib import Path

from bot.model_capabilities import get_video_capability, normalize_video_model_key
from bot.services.preset_manager import preset_manager

ROOT = Path(__file__).resolve().parents[1]


def test_seedance_internal_keys_and_mini_capability_are_registered():
    for key in ("seedance_2_5", "seedance_2", "seedance_2_fast"):
        assert get_video_capability(key) is not None

    mini = get_video_capability("seedance_2_mini")
    assert mini is not None
    assert mini.label == "Seedance 2.0 Mini"
    assert mini.provider == "seedance"
    assert mini.durations == tuple(range(4, 16))
    assert mini.resolutions == ("480p", "720p")
    assert {"1:1", "16:9", "9:16", "4:3", "3:4", "21:9"}.issubset(
        set(mini.aspect_ratios)
    )


def test_seedance_provider_ids_normalize_to_internal_keys():
    assert normalize_video_model_key("seedance-2.5") == "seedance_2_5"
    assert normalize_video_model_key("seedance-2.0") == "seedance_2"
    assert normalize_video_model_key("seedance-2.0-mini") == "seedance_2_mini"
    assert normalize_video_model_key("seedance-2.0-fast") == "seedance_2_fast"

    assert preset_manager.normalize_video_model_key("seedance-2.5") == "seedance_2_5"
    assert preset_manager.normalize_video_model_key("seedance-2.0") == "seedance_2"
    assert preset_manager.normalize_video_model_key("seedance-2.0-mini") == "seedance_2_mini"
    assert preset_manager.normalize_video_model_key("seedance-2.0-fast") == "seedance_2_fast"


def test_admin_pricing_registry_covers_all_seedance_models_without_fake_defaults():
    source = (ROOT / "bot/handlers/admin.py").read_text(encoding="utf-8")
    for model in (
        "seedance_2_5",
        "seedance_2",
        "seedance_2_mini",
        "seedance_2_fast",
    ):
        assert f'"{model}": {{' in source

    assert '("480p", "720p", "1080p")' in source
    assert '("480p", "720p", "1080p", "4k")' in source
    assert '("480p", "720p")' in source

    price = json.loads((ROOT / "data/price.json").read_text(encoding="utf-8"))
    video_models = price["costs_reference"]["video_models"]
    assert "seedance_2_mini" not in video_models
    assert "seedance_2_fast" not in video_models


def test_admin_labels_cover_all_seedance_models():
    source = (ROOT / "bot/handlers/admin.py").read_text(encoding="utf-8")
    for key, label in {
        "seedance_2_5": "Seedance 2.5",
        "seedance_2": "Seedance 2.0",
        "seedance_2_mini": "Seedance 2.0 Mini",
        "seedance_2_fast": "Seedance 2.0 Fast",
    }.items():
        assert f'"{key}": "{label}"' in source

