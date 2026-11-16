"""Real natal ephemerides, date/time boundaries, and aspect invariants."""

from __future__ import annotations

import json

import pytest

from bot.services.astro_lunar import AstroEngineUnavailable, AstroInputError
from bot.services.astro_natal import (
    _resolve_civil_time,
    build_natal_facts,
    load_aspect_orbs,
    major_aspects,
)


def _orbs():
    return {
        "conjunction": 8.0, "sextile": 4.0, "square": 6.0,
        "trine": 6.0, "opposition": 8.0,
    }


def test_aspect_wraparound_is_shortest_arc():
    positions = {
        "Sun": {"longitude_deg": 359.0},
        "Moon": {"longitude_deg": 1.0},
        "Venus": {"longitude_deg": 181.0},
    }
    aspects = major_aspects(positions, _orbs())
    assert any(
        row["kind"] == "conjunction" and row["a"] == "Sun"
        and row["b"] == "Moon" and row["orb_deg"] == 2.0
        for row in aspects
    )
    assert any(
        row["kind"] == "opposition" and row["a"] == "Moon"
        and row["b"] == "Venus" and row["orb_deg"] == 0.0
        for row in aspects
    )


@pytest.mark.parametrize("date", ["29.02.2023", "00.01.2000", "01.13.2000", "01.01.1800", "2000-01-01"])
def test_reject_nonexistent_or_out_of_scope_date(date):
    with pytest.raises(AstroInputError):
        _resolve_civil_time(date=date, time="12:00", timezone_name="UTC")


def test_leap_day_and_utc_conversion():
    instant, known, local = _resolve_civil_time(
        date="29.02.2024", time="12:30", timezone_name="Europe/Moscow"
    )
    assert instant.isoformat() == "2024-02-29T09:30:00+00:00"
    assert known is True
    assert local.endswith("+03:00")


def test_ambiguous_dst_requires_fold():
    with pytest.raises(AstroInputError, match="fold"):
        _resolve_civil_time(date="03.11.2024", time="01:30", timezone_name="America/New_York")
    first, _, _ = _resolve_civil_time(
        date="03.11.2024", time="01:30", timezone_name="America/New_York", fold=0
    )
    second, _, _ = _resolve_civil_time(
        date="03.11.2024", time="01:30", timezone_name="America/New_York", fold=1
    )
    assert (second - first).total_seconds() == 3600


def test_nonexistent_dst_gap_rejected():
    with pytest.raises(AstroInputError, match="не существовало"):
        _resolve_civil_time(date="10.03.2024", time="02:30", timezone_name="America/New_York")


def test_unknown_time_does_not_invent_house_or_moon():
    astro = pytest.importorskip("astronomy")
    result = build_natal_facts(
        date="20.03.2024", time="", timezone_name="UTC", engine=astro, orbs=_orbs()
    )
    assert result["birth_time_known"] is False
    assert "Moon" not in result["positions"]
    assert result["aspects"] == []
    assert "asc" in result["not_calculated"]
    assert all(row["approximate"] for row in result["positions"].values())
    assert result["warnings"]


def test_real_2024_equinox_sun_is_early_aries():
    astro = pytest.importorskip("astronomy")
    result = build_natal_facts(
        date="20.03.2024", time="12:00", timezone_name="UTC", engine=astro, orbs=_orbs()
    )
    assert result["schema_version"] == "astro.natal.facts.v1"
    assert len(result["positions"]) == 10
    sun = result["positions"]["Sun"]
    assert sun["sign"] == "Овен"
    assert 0.0 <= sun["longitude_deg"] < 1.0
    assert sun["retrograde"] is False
    assert result["birth_time_known"] is True
    assert "Moon" in result["positions"]
    assert all(0 <= row["orb_deg"] <= 8 for row in result["aspects"])


def test_orb_config_rejects_bad_values(tmp_path):
    p = tmp_path / "astro_settings.json"
    p.write_text(json.dumps({"aspects": {"orbs_deg": {**_orbs(), "conjunction": -1}}}))
    with pytest.raises(AstroEngineUnavailable):
        load_aspect_orbs(p)
    p.write_text(json.dumps({"aspects": {"orbs_deg": _orbs()}}))
    assert load_aspect_orbs(p)["conjunction"] == 8.0
