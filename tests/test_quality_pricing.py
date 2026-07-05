"""Characterization tests for quality pricing (P2-NEW, P3-04).

These are characterization tests — they pin the ACTUAL behavior
so we can safely refactor. If the business logic changes, update
the assertions deliberately.

Covers:
- QUALITY_COSTS values are int (not float) to prevent fractional credits
- All 4 keys (2k, 2K, 4k, 4K) resolve correctly
- Default quality fallback
- Labels match costs
"""

from bot.quality_pricing import QUALITY_COSTS, DEFAULT_QUALITY, QUALITY_LABELS


class TestQualityCostsAreIntegers:
    """P2-NEW: All quality costs must be int to prevent fractional credits."""

    def test_all_costs_are_int(self):
        for quality, cost in QUALITY_COSTS.items():
            assert isinstance(cost, int), (
                f"QUALITY_COSTS[{quality!r}] = {cost} is {type(cost).__name__}, "
                f"expected int to prevent fractional credits"
            )

    def test_2k_cost(self):
        assert QUALITY_COSTS["2K"] == 2
        assert QUALITY_COSTS["2k"] == 2

    def test_4k_cost(self):
        assert QUALITY_COSTS["4K"] == 4
        assert QUALITY_COSTS["4k"] == 4

    def test_default_quality_is_2k(self):
        assert DEFAULT_QUALITY == "2K"


class TestQualityCostsInvariants:
    """Business invariants that should always hold."""

    def test_4k_not_cheaper_than_2k(self):
        assert QUALITY_COSTS["4K"] >= QUALITY_COSTS["2K"], (
            "4K should not be cheaper than 2K"
        )

    def test_no_negative_costs(self):
        for cost in QUALITY_COSTS.values():
            assert cost >= 0, f"Negative quality cost: {cost}"

    def test_all_keys_have_values(self):
        expected_keys = {"2k", "2K", "4k", "4K"}
        assert set(QUALITY_COSTS.keys()) == expected_keys

    def test_labels_match_costs(self):
        """Labels should display the correct cost values."""
        for quality, label in QUALITY_LABELS.items():
            cost = QUALITY_COSTS.get(quality)
            assert cost is not None, f"Label {quality} has no matching cost"
            assert str(cost) in label, (
                f"Label for {quality}: '{label}' doesn't display cost {cost}"
            )


class TestQualityCostEdgeCases:
    """Edge cases for quality cost lookups."""

    def test_unknown_quality_default_2(self):
        """Unknown quality keys should default to 2 (not silent None/float)."""
        # This mimics the behavior in generation.py: QUALITY_COSTS.get(img_quality, 2)
        for unknown_key in ["", "HD", "8K", "auto", "1080p"]:
            cost = QUALITY_COSTS.get(unknown_key, 2)
            assert isinstance(cost, int), (
                f"Fallback for {unknown_key!r} should be int, got {type(cost).__name__}"
            )
            assert cost == 2

    def test_quality_pricing_module_imports_cleanly(self):
        """Module import should not raise (no circular imports)."""
        import bot.quality_pricing  # noqa: F811
        assert hasattr(bot.quality_pricing, "QUALITY_COSTS")
