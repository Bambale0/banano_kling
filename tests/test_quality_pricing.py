"""Regression tests for config-driven Banana image resolution pricing."""

import json
from pathlib import Path

from bot.quality_pricing import (
    DEFAULT_QUALITY,
    QUALITY_COSTS,
    QUALITY_LABELS,
    refresh_quality_pricing,
)


ROOT = Path(__file__).resolve().parents[1]


def _configured_quality_costs() -> dict[str, float]:
    payload = json.loads((ROOT / "data" / "price.json").read_text(encoding="utf-8"))
    return payload["costs_reference"]["image_quality_costs"]


class TestQualityCostsAreConfigDriven:
    def test_all_costs_are_numeric(self):
        for quality, cost in QUALITY_COSTS.items():
            assert isinstance(cost, (int, float)) and not isinstance(cost, bool), (
                f"QUALITY_COSTS[{quality!r}] = {cost} is {type(cost).__name__}, "
                "expected a numeric tariff"
            )

    def test_prices_match_tariff_config(self):
        configured = _configured_quality_costs()
        assert configured == {"1K": 2.5, "2K": 5, "4K": 7}
        for quality, expected in configured.items():
            assert QUALITY_COSTS[quality] == expected
            assert QUALITY_COSTS[quality.lower()] == expected

    def test_default_quality_is_2k(self):
        assert DEFAULT_QUALITY == "2K"

    def test_refresh_mutates_existing_mapping_in_place(self):
        mapping_id = id(QUALITY_COSTS)
        labels_id = id(QUALITY_LABELS)
        try:
            refreshed = refresh_quality_pricing(
                {
                    "costs_reference": {
                        "image_quality_costs": {"1K": 1.5, "2K": 4, "4K": 8}
                    }
                }
            )
            assert refreshed == {"1K": 1.5, "2K": 4.0, "4K": 8.0}
            assert id(QUALITY_COSTS) == mapping_id
            assert id(QUALITY_LABELS) == labels_id
            assert QUALITY_COSTS["2K"] == 4
            assert QUALITY_LABELS["4K"] == "4K качество — 8 🍌"
        finally:
            refresh_quality_pricing()


class TestQualityCostsInvariants:
    def test_4k_not_cheaper_than_2k(self):
        assert QUALITY_COSTS["4K"] >= QUALITY_COSTS["2K"]

    def test_no_negative_costs(self):
        for cost in QUALITY_COSTS.values():
            assert cost >= 0, f"Negative quality cost: {cost}"

    def test_all_keys_have_values(self):
        expected_keys = {"1k", "1K", "2k", "2K", "4k", "4K"}
        assert set(QUALITY_COSTS.keys()) == expected_keys

    def test_labels_match_costs(self):
        for quality, label in QUALITY_LABELS.items():
            cost = QUALITY_COSTS.get(quality)
            assert cost is not None, f"Label {quality} has no matching cost"
            assert f"{float(cost):g}" in label


class TestQualityCostEdgeCases:
    def test_invalid_config_values_fall_back_safely(self):
        try:
            refresh_quality_pricing(
                {
                    "costs_reference": {
                        "image_quality_costs": {"1K": -1, "2K": "bad", "4K": False}
                    }
                }
            )
            assert QUALITY_COSTS["1K"] == 2.5
            assert QUALITY_COSTS["2K"] == 2.5
            assert QUALITY_COSTS["4K"] == 3.5
        finally:
            refresh_quality_pricing()

    def test_quality_pricing_module_imports_cleanly(self):
        import bot.quality_pricing

        assert hasattr(bot.quality_pricing, "QUALITY_COSTS")
        assert hasattr(bot.quality_pricing, "refresh_quality_pricing")
