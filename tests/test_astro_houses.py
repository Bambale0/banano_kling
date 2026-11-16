"""Deterministic house rulership and planet-in-house boundary checks."""

import pytest

from bot.services.astro_houses import AstroHouseError, annotate_houses, overlay_houses


def chart():
    return {
        "cusps": [(350 + i * 30) % 360 for i in range(12)],
        "angles": {"asc": 350, "mc": 260},
        "bodies": {
            "Sun": {"lon": 359.9}, "Moon": {"lon": 5},
            "Mercury": {"lon": 20},
            "Venus": {"lon": 349.999},
        },
    }


def test_traditional_house_rulers_and_zero_degree_boundaries():
    result = annotate_houses(chart(), ruler_system="traditional")
    assert len(result["houses"]) == 12
    assert result["houses"][0] == {
        "house": 1, "cusp_lon": 350.0,
        "sign": "Pisces", "ruler": "Jupiter",
    }
    assert result["houses"][1]["ruler"] == "Mars"
    assert result["houses"][11]["ruler"] == "Saturn"
    assert result["body_houses"] == {
        "Sun": 1, "Moon": 1, "Mercury": 2, "Venus": 12,
    }
    assert result["ruler_scheme"] == "traditional"


def test_modern_rulership_is_explicit_and_configurable():
    result = annotate_houses(chart(), ruler_system="modern")
    assert result["houses"][0]["ruler"] == "Neptune"
    assert result["houses"][11]["ruler"] == "Uranus"


def test_unknown_time_must_never_fabricate_houses_or_overlays():
    without_time = {"cusps": None, "angles": None, "bodies": {"Sun": {"lon": 20}}}
    result = annotate_houses(without_time)
    assert result["houses"] is None and result["body_houses"] is None
    overlays = overlay_houses(without_time, chart())
    assert overlays["first_in_second"] == {"Sun": 2}
    assert overlays["second_in_first"] is None


def test_actual_cross_house_overlays_are_directional():
    first = chart()
    second = {
        "cusps": [(20 + i * 30) % 360 for i in range(12)],
        "angles": {"asc": 20, "mc": 290},
        "bodies": {"Mars": {"lon": 24}},
    }
    result = overlay_houses(first, second)
    assert result["first_in_second"]["Sun"] == 12
    assert result["second_in_first"]["Mars"] == 2
    assert result["first_in_second"]["Mercury"] == 1


@pytest.mark.parametrize("bad", [
    [0] * 12, list(range(11)), [float("nan")] + [i * 30 for i in range(1, 12)],
    [True] + [i * 30 for i in range(1, 12)],
])
def test_invalid_cusps_rejected_without_silent_house_fallback(bad):
    example = chart() | {"cusps": bad}
    with pytest.raises(AstroHouseError):
        annotate_houses(example)


def test_no_unconfigured_house_ruler_scheme():
    with pytest.raises(AstroHouseError):
        annotate_houses(chart(), ruler_system="invented")


def test_partial_cusps_or_angles_are_never_silently_treated_as_unknown_time():
    for broken in (
        chart() | {"cusps": None},
        chart() | {"angles": None},
    ):
        with pytest.raises(AstroHouseError, match="Incomplete"):
            annotate_houses(broken)
