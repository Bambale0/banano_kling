"""Lunar service invariants and astronomical ground truth."""

import pytest

from bot.services.astro_lunar import (
    AstroInputError,
    build_lunar_calendar,
    parse_period,
    resolve_timezone,
)


@pytest.mark.parametrize(
    "bad",
    ["2026-00", "2026-13", "26-11", "2026-11/", "2026-1",
     "2101-01", "1899-12", 202611, None],
)
def test_reject_invalid_period(bad):
    with pytest.raises(AstroInputError):
        parse_period(bad)


@pytest.mark.parametrize(
    "bad",
    ["../etc/passwd", "Europe/NotAZone", "", "UTC\nX", None, 10],
)
def test_reject_invalid_timezone(bad):
    with pytest.raises(AstroInputError):
        resolve_timezone(bad)


def test_leap_month():
    assert parse_period("2024-02") == (2024, 2)
    assert resolve_timezone("Europe/Moscow") is not None


def test_real_2024_march_full_moon_utc():
    pytest.importorskip("astronomy")
    result = build_lunar_calendar("2024-03", "UTC")
    assert result["schema_version"] == "astro.lunar.v1"
    assert len(result["days"]) == 31
    full = [event for event in result["events"] if event["kind"] == "Полнолуние"]
    assert len(full) == 1
    assert full[0]["at_utc"].startswith("2024-03-25T")
    assert all(0 <= day["illumination_percent"] <= 100 for day in result["days"])
    assert all(1 <= day["synodic_day"] <= 31 for day in result["days"])
    assert result["not_calculated"]


def test_real_february_leap_year_and_dst_boundary():
    pytest.importorskip("astronomy")
    feb = build_lunar_calendar("2024-02", "Europe/Moscow")
    mar = build_lunar_calendar("2024-03", "Europe/Berlin")
    assert len(feb["days"]) == 29
    assert len(mar["days"]) == 31
    assert mar["days"][0]["observed_at_local"].endswith("+01:00")
    assert mar["days"][-1]["observed_at_local"].endswith("+02:00")
